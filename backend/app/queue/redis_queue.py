"""Redis task queue + status pub/sub for the backend side.

Backend pushes new tasks onto a Redis list (LPUSH); worker pops them (BRPOP).
Progress/completion is reported by the worker onto a pub/sub channel which the
backend subscribes to and persists into PostgreSQL.
"""
import asyncio
import json
from typing import Any, Optional

import redis.asyncio as redis

from app.config import settings

_pool = redis.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


async def push_task(task_id: str, payload: dict[str, Any]) -> None:
    r = get_redis()
    await r.lpush(settings.TASK_QUEUE_NAME, json.dumps({"task_id": task_id, **payload}))


async def publish_status(
    task_id: str,
    status: str,
    progress: int = 0,
    output_image: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    r = get_redis()
    payload = json.dumps({
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "output_image": output_image,
        "error": error,
    })
    await r.publish(settings.STATUS_CHANNEL, payload)


async def set_cancel_flag(task_id: str) -> None:
    """Set a short-TTL cancel flag for a queued task.

    This allows a task that was cancelled while still in the Redis queue
    (not yet popped by the worker) to be aborted on pre-flight check.
    """
    r = get_redis()
    await r.set(f"flux:cancel:{task_id}", "1", ex=3600)


async def clear_cancel_flag(task_id: str) -> None:
    """Clear any cancel flag for a task in Redis."""
    r = get_redis()
    await r.delete(f"flux:cancel:{task_id}")


async def listen_for_status(on_event) -> None:
    """Subscribe to status channel forever, calling on_event(dict) per message.

    Intended to run as a background task started on app startup.
    """
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(settings.STATUS_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            try:
                await on_event(data)
            except Exception:
                # Status listener must never die on a single bad event.
                continue
    except asyncio.CancelledError:
        raise
    finally:
        try:
            await pubsub.unsubscribe(settings.STATUS_CHANNEL)
        except Exception:
            pass