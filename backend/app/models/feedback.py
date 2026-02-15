"""Feedback and grading correction Pydantic models"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone


class GradingFeedback(BaseModel):
    """Model for teacher feedback on AI grading"""
    feedback_id: str
    teacher_id: str
    submission_id: Optional[str] = None
    question_number: Optional[int] = None
    feedback_type: str  # "question_grading", "general_suggestion", "correction"
    
    # Context for grading feedback
    question_text: Optional[str] = None
    student_answer_summary: Optional[str] = None
    ai_grade: Optional[float] = None
    ai_feedback: Optional[str] = None
    teacher_expected_grade: Optional[float] = None
    teacher_correction: str  # The actual feedback/correction
    
    # Metadata
    grading_mode: Optional[str] = None
    exam_id: Optional[str] = None
    is_common: bool = False  # Marked if pattern appears across multiple teachers
    upvote_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedbackSubmit(BaseModel):
    """Model for submitting grading feedback"""
    submission_id: Optional[str] = None
    exam_id: Optional[str] = None
    question_number: Optional[int] = None
    sub_question_id: Optional[str] = None  # For sub-question specific feedback
    feedback_type: str
    teacher_correction: str
    question_text: Optional[str] = None
    question_topic: Optional[str] = None  # For pattern matching
    ai_grade: Optional[float] = None
    ai_feedback: Optional[str] = None
    teacher_expected_grade: Optional[float] = None
    apply_to_all_papers: Optional[bool] = False  # Apply to all students
