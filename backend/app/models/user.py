"""User-related Pydantic models"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    role: str = "teacher"  # teacher or student
    batches: List[str] = []
    contact: Optional[str] = None  # Phone number
    teacher_type: Optional[str] = None  # school, college, competitive, others
    exam_category: Optional[str] = None  # For competitive: UPSC, CA, CLAT, JEE, NEET, others
    exam_type: Optional[str] = None  # upsc or college
    profile_completed: bool = False  # Track if initial profile setup is done
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserCreate(BaseModel):
    email: str
    name: str
    role: str = "student"
    student_id: Optional[str] = None
    batches: List[str] = []
    exam_type: Optional[str] = None  # upsc or college


class ProfileUpdate(BaseModel):
    name: str
    contact: str
    email: str
    teacher_type: str  # school, college, competitive, others
    exam_category: Optional[str] = None  # Only for competitive exams
    exam_type: Optional[str] = None  # upsc or college
