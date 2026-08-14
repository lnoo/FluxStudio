import os
from pathlib import Path


class Settings:
    # --- Paths ---
    OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/outputs"))
    UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))

    # --- Database ---
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://flux:flux@localhost:5432/flux")

    # --- Redis ---
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    TASK_QUEUE_NAME = os.getenv("TASK_QUEUE_NAME", "flux:tasks")
    STATUS_CHANNEL = os.getenv("STATUS_CHANNEL", "flux:status")

    # --- Model API (GPT) ---
    MODEL_API_URL = os.getenv("MODEL_API_URL", "http://model-api:8000").rstrip("/")
    PROGRESS_POLL_INTERVAL = float(os.getenv("PROGRESS_POLL_INTERVAL", "1.0"))

    # --- Worker / generation defaults ---
    MAX_INPUT_IMAGES = 8
    # Per-file upload cap (bytes). The nginx proxy also limits total body size,
    # but the backend must enforce it too since port 8081 is directly reachable.
    MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))

    def ensure_dirs(self) -> None:
        for d in (self.OUTPUT_DIR, self.UPLOAD_DIR):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()