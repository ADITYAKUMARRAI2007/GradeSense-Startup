"""Batch-related Pydantic models"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List
from datetime import datetime, timezone


class Batch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    batch_id: str
    name: str
    teacher_id: str
    students: List[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BatchCreate(BaseModel):
    name: str
