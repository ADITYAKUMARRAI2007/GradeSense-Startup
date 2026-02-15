"""Submission and scoring-related Pydantic models"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone
from .exam import AnnotationData


class SubQuestionScore(BaseModel):
    sub_id: str
    max_marks: float
    obtained_marks: float
    ai_feedback: str
    annotations: List[AnnotationData] = []  # Annotations for this sub-question


class QuestionScore(BaseModel):
    question_number: int
    max_marks: float
    obtained_marks: float
    ai_feedback: str
    teacher_comment: Optional[str] = None
    rubric_preference: Optional[str] = None
    is_reviewed: bool = False
    sub_scores: List[SubQuestionScore] = []  # For sub-question scores
    question_text: Optional[str] = None  # The question text
    status: str = "graded"  # graded, not_attempted, not_found, error
    annotations: List[AnnotationData] = []  # Annotations for this question
    page_number: Optional[int] = None  # Which page (1-indexed) the answer is on
    y_position: Optional[int] = None  # Vertical position (0-1000) on the page


class Submission(BaseModel):
    """Model for student paper submission"""
    model_config = ConfigDict(extra="ignore")
    submission_id: str
    exam_id: str
    student_id: str
    student_name: str
    file_data: Optional[str] = None
    file_images: Optional[List[str]] = None  # Original student answer images
    annotated_images: Optional[List[str]] = None  # Annotated images with grading marks
    total_score: float = 0
    percentage: float = 0
    question_scores: List[QuestionScore] = []
    status: str = "pending"  # pending, ai_graded, teacher_reviewed
    graded_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
