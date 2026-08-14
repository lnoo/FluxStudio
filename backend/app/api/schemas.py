from typing import Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    images: list[str] = Field(default_factory=list)
    prompt: str
    steps: int = 30
    # Omitting guidance lets the model use its default (matches model-api/app.py,
    # which only passes guidance_scale to the pipeline when it is not None).
    guidance: Optional[float] = None
    # None = 不指定输出尺寸（文生图 1024×1024、图生图跟随背景图）
    width: Optional[int] = Field(default=None, ge=8, le=4096)
    height: Optional[int] = Field(default=None, ge=8, le=4096)


class GenerateResponse(BaseModel):
    task_id: str
    status: str


class TaskParams(BaseModel):
    """The generation parameters the task was submitted with (mirrors GenerateRequest)."""
    prompt: str
    steps: int
    guidance: Optional[float] = None
    input_images: list[str] = Field(default_factory=list)
    width: Optional[int] = None
    height: Optional[int] = None


class TaskStatusResponse(BaseModel):
    status: str
    progress: int
    task_id: str
    output_image: str | None = None
    error: str | None = None
    params: TaskParams
    avg_sec_per_step: float | None = None
    duration_seconds: float | None = None


class CancelResponse(BaseModel):
    task_id: str
    status: str


class DeleteResponse(BaseModel):
    task_id: str
    status: str


class BulkUploadImage(BaseModel):
    filename: str
    original_name: str
    tag: Optional[str] = None


class BulkUploadResponse(BaseModel):
    images: list[BulkUploadImage]


class BatchGenerateRequest(BaseModel):
    """Batch generation: every background gets `k` randomly-sampled objects."""
    background_images: list[str] = Field(min_length=1)
    object_images: list[str] = Field(min_length=1)
    k: int = Field(default=3, ge=1)
    rounds: int = Field(default=1, ge=1)
    prompt: str
    steps: int = Field(default=20, ge=1, le=60)
    guidance: Optional[float] = None
    width: Optional[int] = Field(default=None, ge=8, le=4096)
    height: Optional[int] = Field(default=None, ge=8, le=4096)


class BatchGenerateResponse(BaseModel):
    task_ids: list[str]
    count: int
