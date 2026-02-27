from app.services.question_mapper import map_segments_to_questions


def test_map_segments_to_questions_builds_hierarchy():
    segments_by_page = [[
        {"segment_id": "P1-S1", "text": "Q1 (a) Explain journal entry", "x1": 5, "y1": 50, "x2": 300, "y2": 90, "page": 1, "tables": []},
        {"segment_id": "P1-S2", "text": "(b) Pass adjustment entry", "x1": 10, "y1": 100, "x2": 320, "y2": 130, "page": 1, "tables": []},
        {"segment_id": "P1-S3", "text": "Q2 State two points", "x1": 5, "y1": 200, "x2": 260, "y2": 230, "page": 1, "tables": []},
    ]]
    words_by_page = [[{"text": "word"} for _ in range(30)]]
    out = map_segments_to_questions(
        segments_by_page=segments_by_page,
        words_by_page=words_by_page,
        expected_questions=[1, 2],
        page_widths=[1000.0],
    )
    assert 1 in out and 2 in out
    assert len(out[1]["segments"]) == 2
    assert out[1]["subquestion_count"] >= 1
    assert any(s.get("sub_id") in ("a", "b") for s in out[1]["subanswers"])
    assert out[2]["page_refs"] == [1]
    assert out[1]["segment_ids"] == ["P1-S1", "P1-S2"]
    assert "combined_text" in out[1]
    assert "mapping_confidence" in out[1]


def test_multi_page_continuation_without_new_anchor_merges():
    segments_by_page = [
        [
            {"segment_id": "P1-S1", "text": "Q1 Explain concept", "x1": 8, "y1": 40, "x2": 260, "y2": 70, "page": 1, "tables": []},
            {"segment_id": "P1-S2", "text": "Details of answer", "x1": 30, "y1": 74, "x2": 280, "y2": 105, "page": 1, "tables": []},
        ],
        [
            {"segment_id": "P2-S1", "text": "More details without label", "x1": 30, "y1": 40, "x2": 320, "y2": 80, "page": 2, "tables": []},
        ],
    ]
    words_by_page = [
        [{"text": "Q1"}] * 40,
        [{"text": "word"}] * 40,
    ]
    out = map_segments_to_questions(
        segments_by_page=segments_by_page,
        words_by_page=words_by_page,
        expected_questions=[1],
        page_widths=[1000.0, 1000.0],
    )
    assert out[1]["segment_ids"] == ["P1-S1", "P1-S2", "P2-S1"]
    assert out[1]["page_refs"] == [1, 2]


def test_sparse_page_attaches_to_nearest_previous_question(monkeypatch):
    monkeypatch.setenv("SPARSE_WORD_THRESHOLD", "20")
    segments_by_page = [
        [
            {"segment_id": "P1-S1", "text": "Q1 Main answer starts here", "x1": 10, "y1": 50, "x2": 300, "y2": 90, "page": 1, "tables": []},
            {"segment_id": "P1-S2", "text": "Q2 Another answer block", "x1": 10, "y1": 240, "x2": 300, "y2": 280, "page": 1, "tables": []},
        ],
        [
            {"segment_id": "P2-S1", "text": "Sparse continuation text", "x1": 16, "y1": 52, "x2": 280, "y2": 84, "page": 2, "tables": []},
        ],
    ]
    words_by_page = [
        [{"text": "word"}] * 40,
        [{"text": "few"}, {"text": "words"}],  # sparse page
    ]
    out = map_segments_to_questions(
        segments_by_page=segments_by_page,
        words_by_page=words_by_page,
        expected_questions=[1, 2],
        page_widths=[1000.0, 1000.0],
    )
    assert "P2-S1" in out[1]["segment_ids"]
    assert out["_meta"]["per_page"][1]["sparse"] is True


def test_table_and_working_note_sticky_before_next_anchor():
    segments_by_page = [
        [
            {"segment_id": "P1-S1", "text": "Q1 Journal entries", "x1": 8, "y1": 40, "x2": 260, "y2": 70, "page": 1, "tables": []},
            {"segment_id": "P1-S2", "text": "Particulars Dr Cr 1000 500", "x1": 24, "y1": 74, "x2": 360, "y2": 120, "page": 1, "tables": [{"bbox": [20, 70, 380, 150]}]},
        ],
        [
            {"segment_id": "P2-S1", "text": "Working Note: calculation for Q1", "x1": 24, "y1": 38, "x2": 320, "y2": 72, "page": 2, "tables": []},
            {"segment_id": "P2-S2", "text": "Particulars Dr Cr 900 700", "x1": 20, "y1": 76, "x2": 360, "y2": 126, "page": 2, "tables": [{"bbox": [20, 74, 380, 145]}]},
            {"segment_id": "P2-S3", "text": "Q2 New question starts", "x1": 8, "y1": 200, "x2": 290, "y2": 235, "page": 2, "tables": []},
        ],
    ]
    words_by_page = [
        [{"text": "word"}] * 60,
        [{"text": "word"}] * 60,
    ]
    out = map_segments_to_questions(
        segments_by_page=segments_by_page,
        words_by_page=words_by_page,
        expected_questions=[1, 2],
        page_widths=[1000.0, 1000.0],
    )
    assert "P2-S1" in out[1]["segment_ids"]
    assert "P2-S2" in out[1]["segment_ids"]
    assert "P2-S3" in out[2]["segment_ids"]
    assert "P2-S2" in out[1]["table_segments"]
    assert "P2-S1" in out[1]["working_note_segments"]
