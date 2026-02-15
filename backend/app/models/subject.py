"""Subject-related Pydantic models"""

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone


class Subject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject_id: str
    name: str
    teacher_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SubjectCreate(BaseModel):
    name: str
