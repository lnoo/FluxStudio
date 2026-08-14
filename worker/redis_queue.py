"""Worker-side Redis helpers: BRPOP the task queue, publish status events."""
import json
from typing import Optional

import redis

import config

_client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True, socket_timeout=30.0, socket_keepalive=True)


def pop_task(timeout: int = 15) -> Optional[dict]:
    """Block until a task is available, then decode it.

    Returns None on timeout.
    """
    try:
        raw = _client.brpop(config.TASK_QUEUE_NAME, timeout=timeout)
        if raw is None:
            return None
        _queue_name, payload = raw
        return json.loads(payload)
    except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError):
        return None


def publish_status(
    task_id: str,
    status: str,
    progress: int = 0,
    output_image: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    payload = json.dumps({
        "task_id": task_id,
        "status": status,
        "progress": progress,
        "output_image": output_image,
        "error": error,
    })
    _client.publish(config.STATUS_CHANNEL, payload)


def get_local_cancel_flag(task_id: str) -> bool:
    """Check if the backend flagged this task for cancellation while it was queued."""
    key = f"flux:cancel:{task_id}"
    return _client.get(key) is not None


def clear_local_cancel_flag(task_id: str) -> None:
    """Remove the cancel flag after honoring it."""
    _client.delete(f"flux:cancel:{task_id}")