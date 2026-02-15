"""Analytics and metrics Pydantic models"""

from pydantic import BaseModel
from typing import Optional, Dict, Any


class NaturalLanguageQuery(BaseModel):
    """Model for natural language analytics queries"""
    query: str
    batch_id: Optional[str] = None
    exam_id: Optional[str] = None
    subject_id: Optional[str] = None


class FrontendEvent(BaseModel):
    """Model for tracking frontend user interactions"""
    event_type: str  # 'button_click', 'tab_switch', 'feature_use'
    element_id: Optional[str] = None
    page: str
    metadata: Optional[Dict[str, Any]] = None


class GradingAnalytics(BaseModel):
    """Model for tracking detailed grading analytics"""
    submission_id: str
    exam_id: str
    teacher_id: str
    original_ai_grade: float
    final_grade: float
    grade_delta: float
    original_ai_feedback: str
    final_feedback: str
    edit_distance: int  # Levenshtein distance or simple char diff
    ai_confidence_score: float  # 0-100
    tokens_input: int
    tokens_output: int
    estimated_cost: float  # in USD
    edited_by_teacher: bool
    edited_at: Optional[str] = None
    grading_duration_seconds: float
    timestamp: str
