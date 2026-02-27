from app.layers.universal.confidence import build_confidence_gate
from app.layers.universal.continuity import resolve_continuity
from app.layers.universal.embeddings import SemanticEmbeddingService


def _blueprint():
    return [
        {"question_id": 1, "marks": 5, "type": "descriptive"},
        {"question_id": 2, "marks": 5, "type": "descriptive"},
    ]


def test_missing_anchor_continuation_attaches_to_active_packet():
    region_text = [
        {
            "block_id": "b1",
            "page_number": 1,
            "bbox": [10, 10, 200, 60],
            "text": "Q1 Explain ledger",
            "question_anchor": 1,
            "is_table": False,
            "is_working_note": False,
        },
        {
            "block_id": "b2",
            "page_number": 1,
            "bbox": [12, 65, 210, 120],
            "text": "Ledger posting continues with balancing.",
            "question_anchor": None,
            "is_table": False,
            "is_working_note": False,
        },
    ]
    out = resolve_continuity(region_text, _blueprint())
    b2 = next(r for r in out["resolved_blocks"] if r["block_id"] == "b2")
    assert b2["attached_by"] == "continuity"
    assert b2["assigned_packet_id"] == "upkt_q1"


def test_multi_page_without_numbering_continues_packet():
    region_text = [
        {
            "block_id": "b1",
            "page_number": 1,
            "bbox": [10, 10, 200, 60],
            "text": "Q1 Define journal entry",
            "question_anchor": 1,
            "is_table": False,
            "is_working_note": False,
        },
        {
            "block_id": "b2",
            "page_number": 2,
            "bbox": [10, 20, 220, 90],
            "text": "Further explanation of journal entry principles",
            "question_anchor": None,
            "is_table": False,
            "is_working_note": False,
        },
    ]
    out = resolve_continuity(region_text, _blueprint())
    b2 = next(r for r in out["resolved_blocks"] if r["block_id"] == "b2")
    assert b2["assigned_packet_id"] == "upkt_q1"


def test_table_spanning_pages_is_sticky():
    region_text = [
        {
            "block_id": "b1",
            "page_number": 1,
            "bbox": [10, 10, 300, 120],
            "text": "Q1",
            "question_anchor": 1,
            "is_table": False,
            "is_working_note": False,
        },
        {
            "block_id": "b2",
            "page_number": 1,
            "bbox": [15, 130, 310, 260],
            "text": "Particulars Dr Cr",
            "question_anchor": None,
            "is_table": True,
            "is_working_note": False,
        },
        {
            "block_id": "b3",
            "page_number": 2,
            "bbox": [15, 20, 305, 150],
            "text": "continued table rows",
            "question_anchor": None,
            "is_table": True,
            "is_working_note": False,
        },
    ]
    out = resolve_continuity(region_text, _blueprint())
    b3 = next(r for r in out["resolved_blocks"] if r["block_id"] == "b3")
    assert b3["assigned_packet_id"] == "upkt_q1"


def test_working_notes_attach_to_active_packet():
    region_text = [
        {
            "block_id": "b1",
            "page_number": 1,
            "bbox": [10, 10, 200, 60],
            "text": "Q1",
            "question_anchor": 1,
            "is_table": False,
            "is_working_note": False,
        },
        {
            "block_id": "b2",
            "page_number": 1,
            "bbox": [20, 70, 210, 120],
            "text": "Working note: goodwill adjustment",
            "question_anchor": None,
            "is_table": False,
            "is_working_note": True,
        },
    ]
    out = resolve_continuity(region_text, _blueprint())
    b2 = next(r for r in out["resolved_blocks"] if r["block_id"] == "b2")
    assert b2["attached_by"] == "recovered"
    assert b2["assigned_packet_id"] == "upkt_q1"


def test_anchor_override_beats_continuity_attach():
    region_text = [
        {
            "block_id": "b1",
            "page_number": 1,
            "bbox": [10, 10, 200, 60],
            "text": "Q1",
            "question_anchor": 1,
            "is_table": False,
            "is_working_note": False,
        },
        {
            "block_id": "b2",
            "page_number": 1,
            "bbox": [10, 70, 200, 120],
            "text": "Q2",
            "question_anchor": 2,
            "is_table": False,
            "is_working_note": False,
        },
    ]
    out = resolve_continuity(region_text, _blueprint())
    b2 = next(r for r in out["resolved_blocks"] if r["block_id"] == "b2")
    assert b2["attached_by"] == "anchor"
    assert b2["assigned_packet_id"] == "upkt_q2"


def test_orphan_ratio_gate_blocks_mapping():
    gate = build_confidence_gate(
        expected_question_ids=[1, 2, 3],
        aligned_answers=[],
        confidence_vectors=[],
        mapping_coverage=0.1,
        orphan_block_ratio=0.5,
        orphan_block_ratio_threshold=0.15,
    )
    assert gate["mapping_status"] == "needs_review"
    assert any("orphan_block_ratio" in reason for reason in gate["mapping_fail_reasons"])


def test_embedding_provider_fallback_returns_vectors():
    svc = SemanticEmbeddingService()
    vectors = svc.embed(["journal entry", "ledger entry"])
    assert len(vectors) == 2
    assert all(isinstance(v, list) for v in vectors)
