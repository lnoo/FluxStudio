"""Task creation + status update logic (DB writes happen here)."""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Image, Task
from app.queue.redis_queue import push_task


async def create_task(
    db: AsyncSession,
    prompt: str,
    steps: int,
    guidance: Optional[float],
    image_filenames: list[str],
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Task:
    """Create a Task row + its input Image rows. Does NOT enqueue.

    The caller commits the DB first, then enqueues, so a failed commit never
    leaves an orphan task sitting in Redis. guidance == None means "let the
    model decide" (stored as SQL NULL, mirrorred by omitting guidance_scale in
    the worker per model-api/app.py). width/height == None means "let the model
    pick the output size" (T2I 1024×1024, image mode follows the background).
    """
    task_id = uuid.uuid4().hex
    task = Task(
        id=task_id,
        status="queued",
        progress=0,
        prompt=prompt,
        steps=steps,
        guidance=guidance,
        input_images=",".join(image_filenames),
        width=width,
        height=height,
    )
    # Link children via the relationship (not raw task_id): the ORM's unit of
    # work then inserts the parent task before the input images, satisfying the
    # images_task_id_fkey foreign key on Postgres.
    for fn in image_filenames:
        task.images.append(Image(
            id=uuid.uuid4().hex,
            filename=fn,
            kind="input",
        ))
    db.add(task)
    await db.flush()
    return task


async def enqueue_task(
    task: Task,
    image_filenames: list[str],
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> None:
    """Push a committed task onto the Redis queue for the worker.

    Image role contract (mirrors model-api/app.py's background_image / object_images
    split): images[0] is the background; images[1:] are the objects, appended in
    order. An empty list is allowed and runs pure text-to-image.
    """
    await push_task(task.id, {
        "prompt": task.prompt,
        "steps": task.steps,
        "guidance": task.guidance,
        "images": list(image_filenames),
        "width": width,
        "height": height,
    })


async def cancel_task(db: AsyncSession, task: Task) -> None:
    """Mark a queued/running task as cancelled. Caller commits.

    Idempotent: skips the write if the task is already cancelled. The caller
    still publishes the cancel signal + status event so the worker (if running)
    aborts the in-flight generation and so watchers see the transition.
    """
    if task.status == "cancelled":
        return
    task.status = "cancelled"
    if task.completed_at is None:
        task.completed_at = datetime.utcnow()
    await db.flush()


async def retry_task(db: AsyncSession, task: Task) -> None:
    """Reset a terminal task to queued state. Caller commits.

    Clears error message, output image reference, and timestamps so the task
    can be re-processed cleanly.
    """
    if task.output_image:
        await db.execute(delete(Image).where(
            Image.filename == task.output_image,
            Image.kind == "output",
            Image.task_id == task.id,
        ))
        task.output_image = None

    task.status = "queued"
    task.progress = 0
    task.error = None
    task.started_at = None
    task.completed_at = None
    await db.flush()


async def delete_task(db: AsyncSession, task: Task) -> list[str]:
    """Delete a task and its image rows. Returns discarded disk filenames.

    The caller commits. Returns the list of filenames (inputs + output) that
    are no longer referenced by the DB so the caller can remove the physical
    files from disk.
    """
    filenames = []
    if task.input_images:
        filenames += [f for f in task.input_images.split(",") if f]
    if task.output_image:
        filenames.append(task.output_image)
    if filenames:
        await db.execute(delete(Image).where(Image.filename.in_(filenames)))
    await db.delete(task)
    return filenames


async def apply_status_update(db: AsyncSession, event: dict[str, Any]) -> None:
    """Apply one status pub/sub event onto the matching Task row, then commit."""
    task_id = event.get("task_id")
    if not task_id:
        return
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        return

    status = event.get("status") or task.status

    # Statuses are monotonic (queued < running < terminal). All terminal states
    # are mutually exclusive and final. Reject any event that would regress the
    # current status — e.g. a late "queued" racing in after the worker already
    # finished, or a late "completed"/"cancelled" arriving after the task is
    # already terminal. Progress carried by a stale event is still applied.
    _RANK = {"queued": 0, "running": 1, "cancelled": 3, "completed": 3, "failed": 3}
    if _RANK.get(status, 1) <= _RANK.get(task.status, 0):
        progress = event.get("progress")
        if progress is not None:
            task.progress = max(task.progress, int(progress))
        await db.flush()
        return

    task.status = status
    progress = event.get("progress")
    if progress is not None:
        task.progress = max(task.progress, int(progress))
    if status == "running" and task.started_at is None:
        task.started_at = datetime.utcnow()
    if status in ("completed", "failed", "cancelled") and task.completed_at is None:
        task.completed_at = datetime.utcnow()
    output_image: Optional[str] = event.get("output_image")
    if output_image:
        task.output_image = output_image
        existing = await db.execute(select(Image).where(
            Image.filename == output_image, Image.kind == "output", Image.task_id == task_id
        ))
        if existing.scalar_one_or_none() is None:
            db.add(Image(
                id=uuid.uuid4().hex,
                filename=output_image,
                kind="output",
                task_id=task_id,
            ))
    error = event.get("error")
    if error:
        task.error = error
    await db.flush()


async def get_avg_sec_per_step(db: AsyncSession, limit: int = 10) -> Optional[float]:
    """Compute average seconds per step across recent completed tasks.

    Returns None if no historical completed task with duration exists.
    """
    result = await db.execute(
        select(Task)
        .where(
            Task.status == "completed",
            Task.started_at.is_not(None),
            Task.completed_at.is_not(None),
            Task.steps > 0,
        )
        .order_by(Task.completed_at.desc())
        .limit(limit)
    )
    completed_tasks = result.scalars().all()
    if not completed_tasks:
        return None

    rates = []
    for t in completed_tasks:
        if t.started_at and t.completed_at:
            duration = (t.completed_at - t.started_at).total_seconds()
            if duration > 0 and t.steps > 0:
                rates.append(duration / t.steps)

    if not rates:
        return None
    return round(sum(rates) / len(rates), 2)