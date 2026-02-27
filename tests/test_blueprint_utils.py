from app.utils.blueprint import derive_expected_question_count, evaluate_blueprint_lock_readiness


def test_derive_expected_question_count_ignores_stale_small_candidate():
    exam = {"num_questions": 1}
    extracted = [{"question_number": n} for n in list(range(1, 20)) + list(range(27, 35))]
    assert derive_expected_question_count(exam, fallback_questions=extracted) == 34


def test_evaluate_blueprint_lock_readiness_flags_missing_questions():
    exam = {"num_questions": 1, "question_paper_pages": 39}
    extracted = [{"question_number": n} for n in list(range(1, 20)) + list(range(27, 35))]
    readiness = evaluate_blueprint_lock_readiness(exam, questions=extracted)

    assert readiness["can_lock"] is False
    assert readiness["health"]["missing"] == [20, 21, 22, 23, 24, 25, 26]
    assert "incomplete_blueprint" in readiness["issues"]


def test_evaluate_blueprint_lock_readiness_passes_contiguous_questions():
    exam = {"question_paper_pages": 12}
    extracted = [{"question_number": n} for n in range(1, 11)]
    readiness = evaluate_blueprint_lock_readiness(exam, questions=extracted)

    assert readiness["can_lock"] is True
    assert readiness["health"]["is_complete"] is True
    assert readiness["issues"] == []
