import mimetypes
import uuid
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    BulkUploadResponse,
    CancelResponse,
    DeleteResponse,
    GenerateRequest,
    GenerateResponse,
    TaskParams,
    TaskStatusResponse,
)
from app.config import settings
from app.database.session import get_db
from app.models import Image, Task
from app.queue.redis_queue import clear_cancel_flag, publish_status, set_cancel_flag
from app.services.file_service import save_images
from app.services.task_service import (
    cancel_task,
    create_batch_tasks,
    create_task,
    delete_task,
    enqueue_task,
    get_avg_sec_per_step,
    retry_task,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Upload images -> returns stored filenames to send in /generate
# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload_images(files: List[UploadFile] = File(...), db: AsyncSession = Depends(get_db)):
    if len(files) > settings.MAX_INPUT_IMAGES:
        raise HTTPException(400, f"too many images (max {settings.MAX_INPUT_IMAGES})")
    saved = await save_images(files)
    for s in saved:
        db.add(Image(
            id=uuid.uuid4().hex,
            filename=s["filename"],
            original_name=s.get("original_name"),
            kind="input",
            size_bytes=s.get("size_bytes"),
        ))
    await db.commit()
    return {"images": [s["filename"] for s in saved]}


# ---------------------------------------------------------------------------
# Bulk upload: register a large pool of images (e.g. 200 backgrounds / 300
# objects). The frontend chunks the files client-side to respect the nginx
# body-size limit; `tag` labels the role ("background" | "object").
# ---------------------------------------------------------------------------
@router.post("/upload/bulk", response_model=BulkUploadResponse)
async def upload_bulk(
    files: List[UploadFile] = File(...),
    tag: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if tag not in ("", "background", "object"):
        raise HTTPException(400, f"invalid tag '{tag}' (must be background, object, or empty)")
    saved = await save_images(files)
    for s in saved:
        db.add(Image(
            id=uuid.uuid4().hex,
            filename=s["filename"],
            original_name=s.get("original_name"),
            kind="input",
            size_bytes=s.get("size_bytes"),
            tag=tag or None,
        ))
    await db.commit()
    return {"images": [
        {"filename": s["filename"], "original_name": s.get("original_name") or s["filename"], "tag": tag or None}
        for s in saved
    ]}


# ---------------------------------------------------------------------------
# Batch generation: every background image gets `k` randomly-sampled objects
# composited onto it (one independent task per background × rounds).
# ---------------------------------------------------------------------------
async def _ensure_uploaded_filenames(db: AsyncSession, filenames: list[str]) -> set[str]:
    if not filenames:
        return set()
    result = await db.execute(select(Image.filename).where(
        Image.filename.in_(filenames), Image.kind == "input"
    ))
    return set(result.scalars().all())


@router.post("/batch/generate", response_model=BatchGenerateResponse)
async def batch_generate(req: BatchGenerateRequest, db: AsyncSession = Depends(get_db)):
    total = len(req.background_images) * req.rounds
    if total > settings.MAX_BATCH_JOBS:
        raise HTTPException(400, f"batch too large: {total} tasks (max {settings.MAX_BATCH_JOBS})")
    if req.k > settings.MAX_INPUT_IMAGES - 1:
        raise HTTPException(400, f"k={req.k} exceeds max objects per task ({settings.MAX_INPUT_IMAGES - 1})")

    existing = await _ensure_uploaded_filenames(db, req.background_images + req.object_images)
    missing = [f for f in set(req.background_images + req.object_images) if f not in existing]
    if missing:
        raise HTTPException(400, f"unknown/unregistered image filenames: {missing[:5]}...")

    tasks = await create_batch_tasks(
        db,
        req.background_images,
        req.object_images,
        k=req.k,
        rounds=req.rounds,
        prompt=req.prompt,
        steps=req.steps,
        guidance=req.guidance,
        width=req.width,
        height=req.height,
    )
    await db.commit()  # persist every task before any enqueue

    task_ids: list[str] = []
    for task in tasks:
        images = task.input_images.split(",") if task.input_images else []
        await publish_status(task.id, "queued", 0)
        await enqueue_task(task, images, task.width, task.height)
        task_ids.append(task.id)

    return BatchGenerateResponse(task_ids=task_ids, count=len(task_ids))


# ---------------------------------------------------------------------------
# Create a generation task
# ---------------------------------------------------------------------------
@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest, db: AsyncSession = Depends(get_db)):
    task = await create_task(db, req.prompt, req.steps, req.guidance, list(req.images), req.width, req.height)
    await db.commit()  # persist first so failures never orphan a queued task
    # Publish "queued" BEFORE enqueueing: the worker is a separate pub/sub
    # publisher, so a "queued" published after the enqueue could race past the
    # worker's "running"/"completed" events and regress the status.
    await publish_status(task.id, "queued", 0)
    await enqueue_task(task, list(req.images), req.width, req.height)
    return {"task_id": task.id, "status": "queued"}


# ---------------------------------------------------------------------------
# Query task status
# ---------------------------------------------------------------------------
def _task_params(task: Task) -> TaskParams:
    """Reconstruct the generation params from the stored task row."""
    return TaskParams(
        prompt=task.prompt,
        steps=task.steps,
        guidance=task.guidance,
        input_images=task.input_images.split(",") if task.input_images else [],
        width=task.width,
        height=task.height,
    )


def _task_duration(t: Task) -> Optional[float]:
    if t.started_at and t.completed_at:
        return round((t.completed_at - t.started_at).total_seconds(), 1)
    return None


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "task not found")
    avg_sec = await get_avg_sec_per_step(db)
    return TaskStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=task.progress,
        output_image=task.output_image,
        error=task.error,
        params=_task_params(task),
        avg_sec_per_step=avg_sec,
        duration_seconds=_task_duration(task),
    )


@router.get("/tasks", response_model=List[TaskStatusResponse])
async def list_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).order_by(Task.created_at.desc()).limit(50))
    tasks = result.scalars().all()
    avg_sec = await get_avg_sec_per_step(db)
    return [
        TaskStatusResponse(
            task_id=t.id, status=t.status, progress=t.progress,
            output_image=t.output_image, error=t.error,
            params=_task_params(t),
            avg_sec_per_step=avg_sec,
            duration_seconds=_task_duration(t),
        )
        for t in tasks
    ]


# ---------------------------------------------------------------------------
# Cancel a queued/running task (idempotent — mirrors model-api/app.py's
# /v1/cancel/{task_id}, adapted to the queue/worker split).
# ---------------------------------------------------------------------------
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


async def _cancel_in_model_api(task_id: str) -> bool:
    """Attempt to cancel a running task in the model-api. Returns True if done."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(f"{settings.MODEL_API_URL}/v1/cancel/{task_id}")
            return r.status_code == 200
    except Exception:
        pass
    return False


@router.post("/tasks/{task_id}/cancel", response_model=CancelResponse)
async def cancel_task_route(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "task not found")
    if task.status in TERMINAL_STATUSES:
        # Already terminal: report the current status without re-publishing.
        return CancelResponse(task_id=task.id, status=task.status)

    # Snapshot the status BEFORE mutating it: cancel_task sets task.status to
    # "cancelled", so checking task.status afterwards can never equal "running".
    status_before = task.status

    # Mark task as cancelled in DB (durable)
    await cancel_task(db, task)
    await db.commit()

    # For tasks that is already running in model-api, send HTTP cancel
    if status_before == "running":
        await _cancel_in_model_api(task.id)

    # Set Redis pre-flight flag for a queued-not-yet-popped task
    await set_cancel_flag(task.id)

    # Publish status so watchers see the transition
    await publish_status(task.id, "cancelled", progress=task.progress)
    return CancelResponse(task_id=task.id, status="cancelled")


@router.delete("/tasks/{task_id}", response_model=DeleteResponse)
async def delete_task_route(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "task not found")

    status_before = task.status

    # Cancel in-flight work first so the worker/model-api stop touching it.
    if status_before == "running":
        await _cancel_in_model_api(task.id)
    if status_before in ("queued", "running"):
        await set_cancel_flag(task.id)

    # Remove DB rows (task + its image rows); commit so the delete is durable
    # before we touch the filesystem.
    filenames = await delete_task(db, task)
    await db.commit()

    # Best-effort removal of the physical files (uploads + outputs).
    for fn in filenames:
        for base in (settings.UPLOAD_DIR, settings.OUTPUT_DIR):
            p = base / fn
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    return DeleteResponse(task_id=task.id, status="deleted")


@router.post("/tasks/{task_id}/retry", response_model=TaskStatusResponse)
async def retry_task_route(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "task not found")
    if task.status not in TERMINAL_STATUSES:
        raise HTTPException(400, f"cannot retry task in '{task.status}' status (must be completed, failed, or cancelled)")

    # Clear cancel flag in Redis if previously cancelled
    await clear_cancel_flag(task.id)

    # Reset task in DB
    await retry_task(db, task)
    await db.commit()

    # Publish status so watchers see the transition to queued
    await publish_status(task.id, "queued", 0)

    # Re-enqueue task
    input_images = task.input_images.split(",") if task.input_images else []
    await enqueue_task(task, input_images, task.width, task.height)

    avg_sec = await get_avg_sec_per_step(db)
    return TaskStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=task.progress,
        output_image=task.output_image,
        error=task.error,
        params=_task_params(task),
        avg_sec_per_step=avg_sec,
        duration_seconds=_task_duration(task),
    )


# ---------------------------------------------------------------------------
# Images: listing + download (by id or by filename)
# ---------------------------------------------------------------------------
def _resolve_image_file(filename: str):
    # Never trust client-supplied filenames: strip any path components to
    # prevent directory traversal out of the upload/output dirs.
    safe_name = Path(filename).name
    for base in (settings.OUTPUT_DIR, settings.UPLOAD_DIR):
        candidate = base / safe_name
        if candidate.exists():
            return candidate
    return None


@router.get("/images")
async def list_images(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Image).order_by(Image.created_at.desc()).limit(200))
    rows = result.scalars().all()
    return {"images": [
        {"id": r.id, "filename": r.filename, "kind": r.kind, "task_id": r.task_id}
        for r in rows
    ]}


@router.get("/images/by-name/{filename}")
async def download_image_by_name(filename: str, name: Optional[str] = None):
    path = _resolve_image_file(filename)
    if path is None:
        raise HTTPException(404, "image not found")
    # Optional friendly download name: strip path/suffix to prevent traversal,
    # then append the real file's extension so the label is always accurate.
    download_name = Path(name).stem + path.suffix if name else path.name
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path=str(path), media_type=media_type, filename=download_name)


@router.get("/images/{image_id}")
async def download_image(image_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Image).where(Image.id == image_id))
    img = result.scalar_one_or_none()
    if img is None:
        raise HTTPException(404, "image not found")
    path = _resolve_image_file(img.filename)
    if path is None:
        raise HTTPException(404, "file missing from disk")
    media_type = mimetypes.guess_type(img.filename)[0] or "application/octet-stream"
    return FileResponse(path=str(path), media_type=media_type, filename=img.original_name or img.filename)