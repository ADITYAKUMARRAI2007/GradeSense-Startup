import os

# Force local embedding provider for tests.
os.environ.setdefault("UNIVERSAL_CONTINUITY_SEMANTIC_PROVIDER", "local")

from app.layers.college_v3.anchor_detection import detect_anchors
from app.layers.college_v3.global_span_builder import build_global_spans
from app.layers.college_v3.answer_mapping import map_answers


def _page(page_index, lines):
    return {
        "page_index": page_index,
        "full_text": "\n".join(l["text"] for l in lines),
        "blocks": lines,
        "paragraphs": lines,
        "word_boxes": [],
    }


def test_anchor_detection_ignores_sections():
    pages = [
        _page(1, [
            {"text": "SECTION A", "bbox": [0, 10, 100, 30], "confidence": 0.9},
            {"text": "Q1. Explain the process", "bbox": [0, 50, 200, 70], "confidence": 0.9},
        ])
    ]
    anchors = detect_anchors(pages)
    assert len(anchors) == 1
    assert anchors[0]["question_number"] == 1
    assert anchors[0]["anchor_level"] == "question"


def test_global_spans_question_only():
    pages = [
        _page(1, [
            {"text": "Q1. First question", "bbox": [0, 10, 100, 30], "confidence": 0.9},
            {"text": "(a) subpart", "bbox": [0, 40, 100, 60], "confidence": 0.9},
            {"text": "Q2. Second question", "bbox": [0, 80, 100, 100], "confidence": 0.9},
        ])
    ]
    anchors = detect_anchors(pages)
    spans = build_global_spans(pages, anchors, level_filter="question")
    assert len(spans) == 2
    assert spans[0]["question_number"] == 1
    assert spans[1]["question_number"] == 2


def test_mapping_continuity_attach():
    answer_pages = [
        _page(1, [
            {"text": "Q1 Answer starts", "bbox": [0, 10, 200, 30], "confidence": 0.9},
            {"text": "more text", "bbox": [0, 40, 200, 60], "confidence": 0.9},
        ]),
        _page(2, [
            {"text": "continuation text", "bbox": [0, 10, 200, 30], "confidence": 0.9},
        ]),
    ]
    mapping = map_answers(answer_pages, expected_questions=[1])
    buckets = mapping.get("question_page_buckets")
    assert 1 in buckets
    assert len(buckets[1]) == 2
    assert buckets[1][1]["continuation_flag"] is True


def test_mapping_gate_low_confidence_blocks():
    answer_pages = [
        _page(1, [
            {"text": "random text", "bbox": [0, 10, 200, 30], "confidence": 0.9},
        ]),
        _page(2, [
            {"text": "more random", "bbox": [0, 10, 200, 30], "confidence": 0.9},
        ]),
    ]
    mapping = map_answers(answer_pages, expected_questions=[1])
    assert mapping.get("mapping_status") == "needs_review"
