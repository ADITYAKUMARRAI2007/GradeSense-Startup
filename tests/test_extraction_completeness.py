from app.services.extraction import (
    _dedupe_and_sort_questions,
    _parse_question_number,
    _validate_extraction_completeness,
)


def test_parse_question_number_variants():
    assert _parse_question_number(1) == 1
    assert _parse_question_number("Q10") == 10
    assert _parse_question_number("Question 3") == 3
    assert _parse_question_number(" 2 ") == 2
    assert _parse_question_number("abc") is None


def test_validate_completeness_with_expected_count_missing():
    extracted = [{"question_number": "Q1"}, {"question_number": "Q2"}, {"question_number": "Q4"}]
    result = _validate_extraction_completeness(extracted, expected_question_count=4)
    assert result["ok"] is False
    assert result["missing"] == [3]


def test_validate_completeness_gap_when_starting_at_q1():
    extracted = [{"question_number": "1"}, {"question_number": "3"}]
    result = _validate_extraction_completeness(extracted, expected_question_count=None)
    assert result["ok"] is False
    assert result["missing"] == [2]


def test_validate_completeness_no_forced_gap_if_not_starting_at_q1():
    extracted = [{"question_number": "3"}, {"question_number": "5"}]
    result = _validate_extraction_completeness(extracted, expected_question_count=None)
    assert result["ok"] is True
    assert result["missing"] == []


def test_dedupe_and_sort_questions_merges_bilingual_duplicates():
    extracted = [
        {
            "question_number": "Q2",
            "question_text": "Q2:",
            "rubric": "Short English rubric",
            "max_marks": 3,
            "sub_questions": [{"sub_id": "a", "rubric": "A eng", "max_marks": 1}],
        },
        {
            "question_number": "1",
            "question_text": "Q1:",
            "rubric": "Hindi rubric text",
            "max_marks": 1,
            "sub_questions": [],
        },
        {
            "question_number": "2",
            "question_text": "Question 2 detailed text",
            "rubric": "Longer English rubric for question two",
            "max_marks": 4,
            "sub_questions": [{"sub_id": "(a)", "rubric": "A better", "max_marks": 2}],
        },
    ]
    out = _dedupe_and_sort_questions(extracted)
    assert [q["question_number"] for q in out] == [1, 2]
    assert out[1]["max_marks"] == 4
    assert len(out[1]["sub_questions"]) == 1
    assert out[1]["sub_questions"][0]["rubric"] == "A better"
