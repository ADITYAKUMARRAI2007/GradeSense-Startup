"""Contracts for college reconstruction + grading gate pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BlueprintItem:
    question_id: int
    subparts: List[Dict[str, Any]] = field(default_factory=list)
    marks: float = 0.0
    type: str = "theory"
    optional_group: Optional[str] = None
    expected_components: List[str] = field(default_factory=list)
    question_text: str = ""
    rubric: str = ""


@dataclass
class BlueprintHealth:
    completeness_score: float = 0.0
    numbering_contiguous: bool = False
    sections_detected: int = 0
    missing: List[int] = field(default_factory=list)
    duplicates: List[int] = field(default_factory=list)
    unexpected: List[int] = field(default_factory=list)
    parsed_numbers: List[int] = field(default_factory=list)
    expected_count: Optional[int] = None
    question_count: int = 0
    is_complete: bool = False
    failed_chunks: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PagePreprocessMetrics:
    page: int
    width: int = 0
    height: int = 0
    skew_angle: float = 0.0
    shadow_removed: bool = False
    margin_ratio: float = 0.0
    contrast_gain: float = 0.0
    ok: bool = True


@dataclass
class PacketConfidence:
    question_id: int
    anchor_confidence: float = 0.0
    ocr_confidence: float = 0.0
    table_confidence: float = 0.0
    alignment_confidence: float = 0.0
    mapping_confidence: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineGateResult:
    mapping_status: str = "needs_review"  # pass | needs_review | failed
    mapped_question_ratio: float = 0.0
    mapping_coverage: float = 0.0
    unresolved_questions: List[int] = field(default_factory=list)
    mapping_fail_reasons: List[str] = field(default_factory=list)
    low_confidence_questions: List[int] = field(default_factory=list)
    consistency_flags: List[str] = field(default_factory=list)
    anchor_confidence_summary: Dict[str, float] = field(default_factory=dict)
    table_confidence_summary: Dict[str, float] = field(default_factory=dict)
    alignment_confidence_summary: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CollegePipelineResult:
    question_blueprint: List[Dict[str, Any]] = field(default_factory=list)
    blueprint_health: Dict[str, Any] = field(default_factory=dict)
    clean_pages_count: int = 0
    preprocess_metrics: List[Dict[str, Any]] = field(default_factory=list)
    page_layout: List[List[Dict[str, Any]]] = field(default_factory=list)
    layout_recovery_flags: List[Dict[str, Any]] = field(default_factory=list)
    region_text: List[Dict[str, Any]] = field(default_factory=list)
    packets: Dict[Any, Any] = field(default_factory=dict)
    aligned_answers: List[Dict[str, Any]] = field(default_factory=list)
    structured_answers: List[Dict[str, Any]] = field(default_factory=list)
    confidence_vectors: List[Dict[str, Any]] = field(default_factory=list)
    final_output: List[Dict[str, Any]] = field(default_factory=list)
    gate: Dict[str, Any] = field(default_factory=dict)
    phase_timings: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
