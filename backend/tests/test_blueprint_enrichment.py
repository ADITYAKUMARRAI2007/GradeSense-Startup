from app.services.blueprint_enrichment import (
    apply_grading_contract,
    build_grading_contract,
    classify_question_type,
)


def test_classify_mcq_and_fill_blank():
    mcq_q = {
        "question_number": 1,
        "max_marks": 1,
        "rubric": "Choose the correct option: (A) cat (B) dog (C) fox (D) owl",
    }
    fill_q = {
        "question_number": 2,
        "max_marks": 1,
        "rubric": "Fill in the blank: The sun ____ in the east.",
    }
    assert classify_question_type(mcq_q) == "mcq"
    assert classify_question_type(fill_q) == "fill_blank"


def test_contract_scales_subparts_to_parent_total():
    q = {
        "question_number": 3,
        "max_marks": 5,
        "rubric": "Answer all parts.",
        "sub_questions": [
            {"sub_id": "a", "max_marks": 5},
            {"sub_id": "b", "max_marks": 5},
        ],
    }
    contract = build_grading_contract(q)
    assert contract["total_marks"] == 5
    sub_total = sum(sp["marks"] for sp in contract["subparts"])
    assert round(sub_total, 4) == 5.0


def test_binary_mcq_marks_are_zero_or_full():
    q = {
        "question_number": 4,
        "max_marks": 1,
        "rubric": "Choose the correct option.",
    }
    contract = build_grading_contract(q)
    high = apply_grading_contract(contract, question_quality=0.9)
    low = apply_grading_contract(contract, question_quality=0.2)
    assert high["obtained_marks"] == 1.0
    assert low["obtained_marks"] == 0.0


def test_best_of_selection_for_choice_question():
    q = {
        "question_number": 5,
        "max_marks": 6,
        "rubric": "Answer any one of the following.",
        "sub_questions": [
            {"sub_id": "a", "max_marks": 6},
            {"sub_id": "b", "max_marks": 6},
        ],
    }
    contract = build_grading_contract(q)
    result = apply_grading_contract(
        contract,
        question_quality=0.0,
        sub_qualities={"a": 0.2, "b": 0.8},
    )
    assert contract["aggregation_rule"] == "best_of"
    assert result["obtained_marks"] <= contract["total_marks"]
    assert result["selected_subparts"] == ["b"]

