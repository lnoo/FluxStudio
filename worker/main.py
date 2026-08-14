"""FLUX worker entrypoint.

A thin HTTP client that:
1. Pops tasks from Redis
2. Uploads images to model-api (model-api/app.py) via HTTP multipart
3. Saves the generated PNG
4. Publishes status updates

Worker runs on any host (no GPU needed) — the GPU is in model-api on the remote GPU host.
"""
import logging
import os

import config
import redis_queue as queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("flux.worker")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def image_filename_for(task_id: str, ext: str = ".png") -> str:
    return f"{task_id}{ext}"


def output_path(filename: str) -> str:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    return os.path.join(config.OUTPUT_DIR, filename)


def upload_path(filename: str) -> str:
    return os.path.join(config.UPLOAD_DIR, filename)


def load_task_image_paths(filenames: list[str]) -> list[str]:
    """Return a list of valid file paths (in order) for the task's images."""
    paths = []
    for f in filenames:
        p = upload_path(f)
        if os.path.exists(p):
            paths.append(p)
        else:
            log.warning("task image missing: %s", p)
    return paths


# ---------------------------------------------------------------------------
# Task execution
# ---------------------------------------------------------------------------
def run_task(task: dict) -> None:
    """Execute a single task by calling the model-api."""
    import model_client

    task_id = task["task_id"]
    prompt = task.get("prompt", "")
    steps = int(task.get("steps", config.DEFAULT_STEPS))
    guidance = task.get("guidance")  # None = omit guidance_scale
    width = task.get("width")  # None = let the model pick output size
    height = task.get("height")
    image_filenames = task.get("images", []) or []

    # Pre-flight cancel check (task was cancelled while queued)
    if queue.get_local_cancel_flag(task_id):
        queue.clear_local_cancel_flag(task_id)
        queue.publish_status(task_id, "cancelled", 0)
        log.info("task %s cancelled before run", task_id)
        return

    # Load images from disk (optional — empty means pure text-to-image)
    image_paths = load_task_image_paths(image_filenames)
    if not image_paths:
        log.info("task %s: no images, running text-to-image", task_id)

    # Signal to backend that we're starting
    queue.publish_status(task_id, "running", 0)

    # Call model-api
    png_bytes, err = model_client.generate(
        prompt=prompt,
        images=image_paths,
        steps=steps,
        guidance=guidance,
        width=width,
        height=height,
        task_id=task_id,
    )

    if png_bytes:
        out_name = image_filename_for(task_id, ".png")
        out_path = output_path(out_name)
        with open(out_path, "wb") as f:
            f.write(png_bytes)
        log.info("task %s -> %s", task_id, out_name)
        queue.publish_status(task_id, "completed", 100, output_image=out_name)
    elif err == "cancelled":
        queue.publish_status(task_id, "cancelled", 0)
        log.info("task %s cancelled during run", task_id)
    else:
        queue.publish_status(task_id, "failed", 0, error=err or "unknown error")
        log.error("task %s failed: %s", task_id, err)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("worker ready; waiting for tasks on %s", config.TASK_QUEUE_NAME)

    import redis as _redis

    while True:
        try:
            task = queue.pop_task(timeout=15)
        except _redis.exceptions.RedisError as e:
            log.warning("redis error popping task: %s", e)
            import time

            time.sleep(2)
            continue
        if task is None:
            continue
        log.info("picked up task %s", task.get("task_id"))
        run_task(task)


if __name__ == "__main__":
    main()