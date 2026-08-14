import os

# Model service endpoint; worker POSTs tasks here and polls for progress.
MODEL_API_URL = os.getenv("MODEL_API_URL", "http://model-api:8000").rstrip("/")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
TASK_QUEUE_NAME = os.getenv("TASK_QUEUE_NAME", "flux:tasks")
STATUS_CHANNEL = os.getenv("STATUS_CHANNEL", "flux:status")

# Paths for saving outputs; mounted volumes in the compose stack.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/uploads")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/outputs")

# Generation defaults (overridden per-task from the queue payload).
DEFAULT_STEPS = int(os.getenv("DEFAULT_STEPS", "30"))
MODEL_API_TIMEOUT = float(os.getenv("MODEL_API_TIMEOUT", "1800.0"))