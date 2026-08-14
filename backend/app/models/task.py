from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(
        Enum("queued", "running", "completed", "failed", "cancelled", name="task_status"),
        default="queued",
        nullable=False,
        index=True,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0..100

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # None => use the model's default guidance (mirrors model-api/app.py omitting
    # guidance_scale from the pipeline kwargs when it is not provided).
    guidance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # None => 不指定输出尺寸（文生图 1024×1024、图生图跟随背景图）
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # CSV of input image filenames in request order
    input_images: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Output image filename once generation completes
    output_image: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Declared relationship so the ORM knows Image rows depend on this Task and
    # inserts the parent before any children (FK ordering without flush tricks).
    images: Mapped[list["Image"]] = relationship("Image", back_populates="task")
