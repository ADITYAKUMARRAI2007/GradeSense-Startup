from app.services.answer_sheet_pipeline import build_packets, structure_accounting_answer


def test_build_packets_respects_anchor_table_and_working_note_rules():
    blueprint = [
        {"question_id": 1, "parts": [], "marks": 5, "type": "journal", "expected_components": []},
        {"question_id": 2, "parts": [], "marks": 5, "type": "journal", "expected_components": []},
    ]
    regions = [
        {
            "block_id": "P1-B1",
            "page_number": 1,
            "bbox": [20, 100, 120, 140],
            "block_type": "question_anchor_candidate",
            "text": "Q1",
            "ocr_confidence": 0.9,
            "fallback_used": False,
            "question_anchor": 1,
            "subpart_id": None,
            "is_working_note": False,
            "is_table": False,
            "ocr_provider": "vision",
        },
        {
            "block_id": "P1-B2",
            "page_number": 1,
            "bbox": [130, 150, 900, 450],
            "block_type": "table",
            "text": "To Bank A/c 5000",
            "ocr_confidence": 0.85,
            "fallback_used": False,
            "question_anchor": None,
            "subpart_id": "a",
            "is_working_note": False,
            "is_table": True,
            "ocr_provider": "vision",
        },
        {
            "block_id": "P2-B1",
            "page_number": 2,
            "bbox": [150, 70, 900, 150],
            "block_type": "text",
            "text": "Working note: amount calculation",
            "ocr_confidence": 0.8,
            "fallback_used": False,
            "question_anchor": None,
            "subpart_id": None,
            "is_working_note": True,
            "is_table": False,
            "ocr_provider": "vision",
        },
        {
            "block_id": "P2-B2",
            "page_number": 2,
            "bbox": [20, 220, 120, 260],
            "block_type": "question_anchor_candidate",
            "text": "Q2",
            "ocr_confidence": 0.91,
            "fallback_used": False,
            "question_anchor": 2,
            "subpart_id": None,
            "is_working_note": False,
            "is_table": False,
            "ocr_provider": "vision",
        },
    ]

    packets = build_packets(regions=regions, blueprint=blueprint)
    q1 = packets[1]
    q2 = packets[2]

    assert q1["table_segments"] == ["P1-B2"]
    assert q1["working_note_segments"] == ["P2-B1"]
    assert q1["pages"] == [1, 2]
    assert q2["pages"] == [2]
    assert packets["_meta"]["packets_generated"] == 2


def test_structure_accounting_answer_extracts_entries_totals_and_calculations():
    packet = {
        "text_blocks": [
            {"text": "To Bank A/c 50,000"},
            {"text": "By Realisation A/c 60,000"},
            {"text": "Working note: 75000-17000+2000 = 60000"},
            {"text": "Total 60,000"},
        ]
    }
    structured = structure_accounting_answer(packet)
    assert "Bank" in " ".join(structured["accounts"])
    assert len(structured["journal_entries"]) >= 2
    assert len(structured["calculations"]) >= 1
    assert len(structured["totals"]) >= 1
    assert len(structured["reasoning"]) >= 1
