import pytest

from app.layers.aws_pipeline.blueprint_builder import build_spans, build_span_evidence
from app.layers.aws_pipeline.question_identity import generate_question_uuid


def test_question_uuid_stable():
    uuid1 = generate_question_uuid("Q1", 1, "Preview text")
    uuid2 = generate_question_uuid("Q1", 1, "Preview text")
    assert uuid1 == uuid2


def test_build_spans_fallback_when_no_anchors():
    spans = build_spans([], [{"page": 1, "text": "Question text", "bbox": {"top": 0.1}}])
    assert len(spans) == 1
    assert spans[0]["span_id"] == "span_fallback"


def test_span_evidence_fields():
    spans = [
        {
            "span_id": "span_1",
            "question_number": "1",
            "anchor_level": "question",
            "anchor_text": "Q1",
            "anchor_bbox": {"top": 0.1},
            "page_numbers": [1],
            "raw_text_by_page": [{"page": 1, "text": "Q1 text"}],
            "preview_text": "Q1 text",
            "anchor_confidence": 0.9,
            "span_length": 8,
            "next_anchor_text": None,
        }
    ]
    evidence = build_span_evidence(spans)
    assert evidence[0].get("span_evidence")
    assert "layout_features" in evidence[0]["span_evidence"]

