"""Re-evaluation request Pydantic models"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone


class ReEvaluationRequest(BaseModel):
    """Model for student re-evaluation requests"""
    model_config = ConfigDict(extra="ignore")
    request_id: str
    submission_id: str
    student_id: str
    student_name: str
    exam_id: str
    questions: List[int]
    reason: str
    status: str = "pending"  # pending, in_review, resolved
    response: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReEvaluationCreate(BaseModel):
    """Model for creating a re-evaluation request"""
    submission_id: str
    questions: List[int]
    reason: str
