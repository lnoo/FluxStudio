"""Model client: POST tasks to the model-api (model-api/app.py) over HTTP.

After posted, the model-api runs inference and returns the PNG result.
All metadata (progress, cancel, timing) is out of band via Redis pub/sub.
"""
import logging
import os
from typing import Optional, Tuple

import httpx

import config

log = logging.getLogger("flux.worker.model_client")


def generate(
    prompt: str,
    images: list,
    steps: int,
    guidance: Optional[float],
    task_id: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Send a generation request to the model service.

    Args:
        prompt: The text prompt for the generation.
        images: List of disk file paths. Empty list = pure text-to-image.
                images[0] is the background, images[1:] are objects to fuse onto it.
        steps: Number of inference steps.
        guidance: Guidance scale, or None to let the model use its default.
        task_id: The unique task identifier (passed to app.py for cancel/progress keyed lookups).
        width, height: Optional output size in pixels. None = let the model decide.

    Returns:
        (png_bytes, None) on success, or (None, error_message) on failure/cancel.
        On cancel, the message is the string "cancelled".
    """
    fields = {
        "task_id": task_id,
        "prompt": prompt,
        "num_inference_steps": str(steps),
    }
    if guidance is not None:
        fields["guidance_scale"] = str(guidance)
    if width is not None:
        fields["width"] = str(width)
    if height is not None:
        fields["height"] = str(height)

    # Files are optional (empty images = pure text-to-image); background is the
    # first image, the rest are objects. httpx multipart needs a list of
    # (field, (filename, content, mime)) tuples so multiple files can share the
    # same "object_images" field name.
    # app.py sends back PNG on success, or JSON `{"status":"cancelled"}` on client cancel.
    parts: list = []
    for idx, path in enumerate(images):
        if not os.path.exists(path):
            log.warning("model-client: image missing, skipping: %s", path)
            continue
        lower = path.lower()
        if lower.endswith(".png"):
            mime = "image/png"
        elif lower.endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        else:
            mime = "image/webp"
        name = os.path.basename(path)
        with open(path, "rb") as f:
            content = f.read()
        # First successfully-read image is the background, the rest are objects.
        field = "background_image" if not parts else "object_images"
        parts.append((field, (name, content, mime)))

    url = f"{config.MODEL_API_URL}/v1/mix-generation-pro"
    timeout_cfg = httpx.Timeout(timeout=config.MODEL_API_TIMEOUT, connect=30.0)
    try:
        with httpx.Client(timeout=timeout_cfg) as client:
            r = client.post(url, data=fields, files=parts)

        ct = r.headers.get("content-type", "")
        if ct.startswith("image/"):
            return r.content, None
        if ct.startswith("application/json"):
            body = r.json()
            if body.get("status") == "cancelled":
                return None, "cancelled"
            return None, f"app.py: {body.get('error', body)}"
        return None, f"app.py: unexpected {ct}"

    except httpx.ConnectError as e:
        return None, f"model-api unreachable: {e}"
    except httpx.HTTPStatusError as e:
        return None, f"app.py HTTP {e.response.status_code}"
    except Exception as e:
        return None, f"model-api error: {e}"