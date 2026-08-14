from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Image(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    original_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # "input" | "output"
    task_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=True, index=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Optional role label for batch pools: "background" | "object" | None.
    tag: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    task: Mapped[Optional["Task"]] = relationship("Task", back_populates="images")
