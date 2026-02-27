"""Contracts for Universal V2 pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CleanPage:
    page_id: str
    page_number: int
    image_b64: str
    width: int = 0
    height: int = 0


@dataclass
class OCRBlock:
    block_id: str
    page_number: int
    bbox: List[float]
    text: str = ""
    block_type: str = "text"
    ocr_confidence: float = 0.0
    is_table: bool = False
    is_working_note: bool = False
    question_anchor: Optional[int] = None
    subpart_id: Optional[str] = None


@dataclass
class QuestionBlueprintItem:
    question_id: int
    subparts: List[Dict[str, Any]] = field(default_factory=list)
    marks: float = 0.0
    type: str = "descriptive"
    optional_group: Optional[str] = None
    expected_components: List[str] = field(default_factory=list)
    question_text: str = ""


@dataclass
class ResolvedBlock:
    block_id: str
    assigned_packet_id: Optional[str]
    continuity_score: float
    continuity_trace: Dict[str, Any] = field(default_factory=dict)
    attached_by: str = "unresolved"


@dataclass
class AnswerPacket:
    packet_id: str
    question_id: Optional[int]
    pages: List[int] = field(default_factory=list)
    segment_ids: List[str] = field(default_factory=list)
    text_blocks: List[Dict[str, Any]] = field(default_factory=list)
    table_segments: List[str] = field(default_factory=list)
    working_note_segments: List[str] = field(default_factory=list)
    subanswers: List[Dict[str, Any]] = field(default_factory=list)
    mapping_trace: List[str] = field(default_factory=list)
    mapping_confidence: float = 0.0


@dataclass
class AlignedAnswer:
    question_id: int
    packet_id: Optional[str]
    aligned_by: str
    alignment_confidence: float


@dataclass
class StructuredAnswer:
    question_id: int
    structured_answer: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfidenceVector:
    question_id: int
    anchor_confidence: float = 0.0
    ocr_confidence: float = 0.0
    table_confidence: float = 0.0
    alignment_confidence: float = 0.0
    mapping_confidence: float = 0.0


@dataclass
class GradeResult:
    question_id: int
    score: float
    max_marks: float
    feedback: str
    confidence: float
    mapping_trace: List[str] = field(default_factory=list)


@dataclass
class PipelineAudit:
    phase_timings: Dict[str, float] = field(default_factory=dict)
    continuity_decisions: List[Dict[str, Any]] = field(default_factory=list)
    orphan_block_count: int = 0
    orphan_block_ratio: float = 0.0
    mapping_fail_reasons: List[str] = field(default_factory=list)


@dataclass
class UniversalPipelineResult:
    question_blueprint: List[Dict[str, Any]] = field(default_factory=list)
    blueprint_health: Dict[str, Any] = field(default_factory=dict)
    clean_pages_count: int = 0
    preprocess_metrics: List[Dict[str, Any]] = field(default_factory=list)
    page_layout: List[List[Dict[str, Any]]] = field(default_factory=list)
    region_text: List[Dict[str, Any]] = field(default_factory=list)
    continuity: Dict[str, Any] = field(default_factory=dict)
    packets: Dict[Any, Any] = field(default_factory=dict)
    aligned_answers: List[Dict[str, Any]] = field(default_factory=list)
    structured_answers: List[Dict[str, Any]] = field(default_factory=list)
    confidence_vectors: List[Dict[str, Any]] = field(default_factory=list)
    final_output: List[Dict[str, Any]] = field(default_factory=list)
    gate: Dict[str, Any] = field(default_factory=dict)
    phase_timings: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
