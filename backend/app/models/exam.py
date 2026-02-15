"""Exam-related Pydantic models"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone


class SubQuestion(BaseModel):
    """Model for sub-questions (e.g., 1a, 1b, 1c)"""
    sub_id: str  # e.g., "a", "b", "c"
    max_marks: float
    rubric: Optional[str] = None


class ExamQuestion(BaseModel):
    """Model for exam questions with optional sub-questions"""
    question_number: int
    max_marks: float
    rubric: Optional[str] = None
    sub_questions: List[SubQuestion] = []  # For questions like 1a, 1b, 1c


class Exam(BaseModel):
    model_config = ConfigDict(extra="ignore")
    exam_id: str
    batch_id: str
    subject_id: str
    exam_type: str
    exam_name: str
    total_marks: float
    exam_date: str
    grading_mode: str
    questions: List[ExamQuestion] = []
    model_answer_file: Optional[str] = None
    teacher_id: str
    status: str = "draft"  # draft, processing, completed
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExamCreate(BaseModel):
    """Model for creating a teacher-upload mode exam"""
    batch_id: str
    subject_id: str
    exam_type: str
    exam_name: str
    total_marks: float = 100  # Default to 100, will be updated after extraction
    exam_date: str
    grading_mode: str
    questions: List[dict] = []  # Optional, will be populated by auto-extraction
    exam_mode: str = "teacher_upload"  # "teacher_upload" or "student_upload"
    show_question_paper: bool = False  # For student mode, whether to show question paper


class StudentExamCreate(BaseModel):
    """Model for creating exam in student-upload mode"""
    batch_id: str
    exam_name: str
    total_marks: float
    grading_mode: str = "balanced"
    student_ids: List[str]  # Selected students
    show_question_paper: bool = False
    questions: List[ExamQuestion]


class StudentSubmission(BaseModel):
    """Model for student answer submission"""
    submission_id: str
    exam_id: str
    student_id: str
    student_name: str
    student_email: str
    answer_file_ref: str  # GridFS reference
    submitted_at: str
    status: str  # "submitted", "graded"


class AnnotationData(BaseModel):
    """Represents a single annotation on an answer paper"""
    type: str  # checkmark, score_circle, flag_circle, step_label, point_number, cross_mark, error_underline
    x: int = 0
    y: int = 0
    text: str = ""
    label: Optional[str] = None
    feedback: Optional[str] = None
    color: str = "green"
    size: int = 30
    page_index: int = 0  # Which page/image this annotation belongs to
    box_2d: Optional[List[int]] = None  # [ymin, xmin, ymax, xmax] normalized 0-1000
    anchor_text: Optional[str] = None  # Optional text anchor for OCR positioning
    line_id: Optional[str] = None  # Line identifier (e.g., Q1-L3)
    line_id_start: Optional[str] = None  # Line range start (e.g., Q1-L2)
    line_id_end: Optional[str] = None  # Line range end (e.g., Q1-L5)
    anchor_x: Optional[float] = None
    anchor_y: Optional[float] = None
    margin_x: Optional[float] = None
    margin_y: Optional[float] = None
    x_percent: Optional[float] = None
    y_percent: Optional[float] = None
    w_percent: Optional[float] = None
    h_percent: Optional[float] = None
    y_start: Optional[float] = None
    y_end: Optional[float] = None
    y_start_percent: Optional[float] = None
    y_end_percent: Optional[float] = None
