"""File management: accept uploads, store under uploads-dir, return saved filenames."""
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import settings

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return ext if ext in ALLOWED_IMAGE_EXTS else ".jpg"


async def save_upload(upload: UploadFile) -> tuple[str, str, int]:
    """Save one uploaded file. Returns (stored_filename, original_name, size_bytes)."""
    ext = _safe_ext(upload.filename or "upload.jpg")
    stored = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOAD_DIR / stored
    size = 0
    with open(dest, "wb") as f:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > settings.MAX_UPLOAD_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    413,
                    f"upload too large (max {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
                )
            f.write(chunk)
    return stored, upload.filename or stored, size


async def save_images(uploads: list[UploadFile]) -> list[dict]:
    saved = []
    for u in uploads:
        stored, original, size = await save_upload(u)
        saved.append({"filename": stored, "original_name": original, "size_bytes": size})
    return saved
