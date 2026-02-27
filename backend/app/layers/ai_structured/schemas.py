"""Typed schemas for AI-structured extraction, alignment and grading."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


QUESTION_TYPE_LITERAL = Literal[
    "mcq",
    "fill_blank",
    "very_short",
    "short",
    "long",
    "passage",
    "writing",
    "letter",
    "essay",
    "short_answer",
    "descriptive",
    "descriptive_choice",
    "passage_subparts",
    "or_group",
]


ANSWER_TYPE_LITERAL = Literal["mcq", "written", "blank"]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_index: int = Field(ge=0)
    bbox: Optional[List[float]] = None
    visual_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("bbox")
    @classmethod
    def _bbox_shape(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is None:
            return value
        if len(value) != 4:
            raise ValueError("bbox must contain 4 values [x1,y1,x2,y2]")
        return [float(v) for v in value]


class SubQuestionV2(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    text: str = ""
    marks: float = Field(default=0.0, ge=0.0)
    mark_source: str = "inferred"
    mark_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    image_evidence: List[EvidenceRef] = Field(default_factory=list)


class QuestionV2(BaseModel):
    model_config = ConfigDict(extra="ignore")

    number: int = Field(ge=1)
    section: Optional[str] = None
    instruction: Optional[str] = None
    question_text: str = ""
    question_type: str = "descriptive"
    marks: float = Field(default=0.0, ge=0.0)
    mark_source: str = "inferred"
    mark_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    options: Optional[List[str]] = None
    subquestions: List[SubQuestionV2] = Field(default_factory=list)
    or_group_id: Optional[str] = None
    image_evidence: List[EvidenceRef] = Field(default_factory=list)
    ai_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SectionMathBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    section: Optional[str] = None
    expression: str = ""
    question_count: int = Field(default=0, ge=0)
    per_question_marks: float = Field(default=0.0, ge=0.0)
    total_marks: float = Field(default=0.0, ge=0.0)
    page_index: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class QuestionStructureV2(BaseModel):
    model_config = ConfigDict(extra="ignore")

    questions: List[QuestionV2] = Field(default_factory=list)
    section_math_blocks: List[SectionMathBlock] = Field(default_factory=list)
    total_questions: int = Field(default=0, ge=0)
    total_marks: float = Field(default=0.0, ge=0.0)
    effective_total_marks: float = Field(default=0.0, ge=0.0)
    numbering_contiguous: bool = False
    structure_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_errors: List[str] = Field(default_factory=list)


class AlignedAnswerV2(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_number: int = Field(ge=1)
    sub_label: Optional[str] = None
    answer_text: str = ""
    detected_type: ANSWER_TYPE_LITERAL = "written"
    page_index: Optional[int] = Field(default=None, ge=0)
    bbox: Optional[List[float]] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("bbox")
    @classmethod
    def _bbox_shape(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is None:
            return value
        if len(value) != 4:
            raise ValueError("bbox must contain 4 values [x1,y1,x2,y2]")
        return [float(v) for v in value]


class AlignmentResultV2(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: List[AlignedAnswerV2] = Field(default_factory=list)
    coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    alignment_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    question_coverage_map: Dict[str, bool] = Field(default_factory=dict)
    unmapped_answers: List[dict] = Field(default_factory=list)
    duplicate_answers: List[dict] = Field(default_factory=list)
    orphan_pages: List[int] = Field(default_factory=list)
    alignment_confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    expected_questions: int = Field(default=0, ge=0)
    answered_questions: int = Field(default=0, ge=0)


class StageConfidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    structure_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    alignment_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    grading_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ObjectiveKeyConsensus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_number: int = Field(ge=1)
    inferred_key: Optional[str] = None
    consensus_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_flag: Literal["high", "low"] = "low"
    variance: float = Field(default=1.0, ge=0.0, le=1.0)
    candidates: List[str] = Field(default_factory=list)


class GradingQualityResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_quality: float = Field(default=0.0)
    question_status: str = "graded"
    question_feedback: str = ""
    sub_qualities: Dict[str, float] = Field(default_factory=dict)
    sub_status: Dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
