import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.config import settings
from app.database.session import async_session_factory, init_db
from app.queue.redis_queue import listen_for_status
from app.services.task_service import apply_status_update

import httpx
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("flux.backend")


def _parse_progress(value: str) -> int:
    """Parse '12.34%' -> 12."""
    try:
        return int(round(float(value.rstrip("%"))))
    except Exception:
        return 0


async def _status_consumer():
    """Background task: subscribe to worker status events and persist them."""
    async def on_event(event):
        async with async_session_factory() as db:
            try:
                await apply_status_update(db, event)
                await db.commit()
            except Exception as e:
                await db.rollback()
                log.exception("status event failed: %s", e)
    await listen_for_status(on_event)


async def _progress_poller():
    """Background task: poll app.py for progress of running tasks."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            await asyncio.sleep(settings.PROGRESS_POLL_INTERVAL)
            async with async_session_factory() as db:
                rows = (await db.execute(text(
                    "SELECT id, progress FROM tasks WHERE status = 'running'"
                ))).all()
                updates = []
                for task_id, current in rows:
                    try:
                        r = await client.get(
                            f"{settings.MODEL_API_URL}/v1/progress/{task_id}"
                        )
                        pct = _parse_progress(r.json().get("progress", "0%"))
                        if pct > current:
                            updates.append((pct, task_id))
                    except Exception as e:
                        log.debug("progress poll failed for task %s: %s", task_id, e)
                for pct, task_id in updates:
                    await db.execute(
                        text("UPDATE tasks SET progress = :pct WHERE id = :id"),
                        {"pct": pct, "id": task_id},
                    )
                await db.commit()


async def _run_status_consumer_and_poller():
    """Run both background tasks."""
    await asyncio.gather(_status_consumer(), _progress_poller())


async def lifespan(app: FastAPI):
    await init_db()
    log.info("database initialized")

    # Start status consumer (worker -> backend Redis -> DB)
    # Start progress poller (backend -> app.py -> DB)
    background_task = asyncio.create_task(_run_status_consumer_and_poller())
    log.info("status listener and progress poller started")

    try:
        yield
    finally:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="FLUX.2-dev Platform", version="1.0.0", lifespan=lifespan)

# CORS for the React dev server.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}