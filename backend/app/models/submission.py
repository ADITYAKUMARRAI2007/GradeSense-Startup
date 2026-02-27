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
    question_uuid: Optional[str] = None
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
    grading_state: Optional[str] = None  # pending, aligning, grading, done, blocked
    blueprint_version_used: Optional[int] = None
    grading_contract_version: Optional[str] = None
    structure_confidence: Optional[float] = None
    alignment_confidence: Optional[float] = None
    grading_confidence: Optional[float] = None
    overall_confidence: Optional[float] = None
    alignment_status: Optional[str] = None  # pass, needs_review, blocked
    alignment_coverage: Optional[float] = None
    question_coverage_map: Optional[dict] = None
    unmapped_answers: Optional[List[dict]] = None
    duplicate_answers: Optional[List[dict]] = None
    realign_required: Optional[bool] = None
    objective_key_flags: Optional[dict] = None
    model_name: Optional[str] = None
    prompt_version: Optional[str] = None
    pipeline_version: Optional[str] = None
    mapping_status: Optional[str] = None  # pass, needs_review, failed
    mapping_confidence: Optional[float] = None
    continuity_confidence: Optional[float] = None
    mapped_question_ratio: Optional[float] = None
    mapping_coverage: Optional[float] = None
    unresolved_questions: Optional[List[int]] = None
    mapping_fail_reasons: Optional[List[str]] = None
    answer_pages: Optional[List[dict]] = None
    question_page_buckets: Optional[dict] = None
    continuation_merges: Optional[List[dict]] = None
    orphan_pages: Optional[List[int]] = None
    anchor_confidence_summary: Optional[dict] = None
    table_confidence_summary: Optional[dict] = None
    alignment_confidence_summary: Optional[dict] = None
    continuity_confidence_summary: Optional[dict] = None
    orphan_block_count: Optional[int] = None
    orphan_block_ratio: Optional[float] = None
    packet_trace_ref: Optional[str] = None
    graded_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
