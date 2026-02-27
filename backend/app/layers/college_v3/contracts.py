"""Contracts for college_v3 pipeline (Vision OCR, global spans)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PageOCR:
    page_index: int
    full_text: str
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    paragraphs: List[Dict[str, Any]] = field(default_factory=list)
    word_boxes: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Anchor:
    question_number: Optional[int]
    anchor_level: str  # question | subquestion | subsubquestion
    parent_question_number: Optional[int]
    page_index: int
    bbox: List[float]
    text_snippet: str
    confidence: float = 0.0
    y_position: float = 0.0
    line_index: Optional[int] = None


@dataclass
class QuestionSpan:
    question_number: int
    anchor_level: str
    parent_question_number: Optional[int]
    page_numbers: List[int] = field(default_factory=list)
    raw_text_by_page: List[Dict[str, Any]] = field(default_factory=list)
    span_blocks: List[Dict[str, Any]] = field(default_factory=list)
    preview_text: str = ""
    anchor_confidence: float = 0.0
    span_length: int = 0


@dataclass
class BlueprintResult:
    questions: List[Dict[str, Any]] = field(default_factory=list)
    blueprint_pages: List[Dict[str, Any]] = field(default_factory=list)
    global_anchor_list: List[Dict[str, Any]] = field(default_factory=list)
    question_spans: List[Dict[str, Any]] = field(default_factory=list)
    blueprint_question_pages: Dict[int, List[int]] = field(default_factory=dict)
    blueprint_health: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)


@dataclass
class AnswerPage:
    page_index: int
    full_text: str
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    paragraphs: List[Dict[str, Any]] = field(default_factory=list)
    word_boxes: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MappingResult:
    question_page_buckets: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    mapping_status: str = "needs_review"
    mapping_confidence: float = 0.0
    continuity_confidence: float = 0.0
    continuation_merges: List[Dict[str, Any]] = field(default_factory=list)
    missing_questions: List[int] = field(default_factory=list)
    low_confidence_questions: List[int] = field(default_factory=list)
    orphan_pages: List[int] = field(default_factory=list)


@dataclass
class CollegeV3Result:
    blueprint: BlueprintResult
    answer_pages: List[Dict[str, Any]]
    mapping: MappingResult
    phase_timings: Dict[str, float] = field(default_factory=dict)
    gate: Dict[str, Any] = field(default_factory=dict)

