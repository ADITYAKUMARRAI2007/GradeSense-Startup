from app.layers.upsc.policy import enforce_upsc_strict_caps
from app.models.submission import QuestionScore, SubQuestionScore


def _q(
    question_number: int,
    max_marks: float,
    obtained_marks: float,
    sub_scores=None,
):
    return QuestionScore(
        question_number=question_number,
        max_marks=max_marks,
        obtained_marks=obtained_marks,
        ai_feedback="ok",
        sub_scores=sub_scores or [],
    )


def test_strict_caps_not_applied_for_non_upsc():
    scores = [_q(1, 10, 9)]
    questions = [{"question_number": 1, "max_marks": 10}]
    out = enforce_upsc_strict_caps(scores, questions, grading_mode="strict", is_upsc=False)
    assert out[0].obtained_marks == 9


def test_strict_caps_keep_low_mark_questions_non_zero():
    scores = [_q(1, 1, 1), _q(2, 2, 2)]
    questions = [
        {"question_number": 1, "max_marks": 1},
        {"question_number": 2, "max_marks": 2},
    ]
    out = enforce_upsc_strict_caps(scores, questions, grading_mode="strict", is_upsc=True)
    assert out[0].obtained_marks == 1
    assert out[1].obtained_marks == 2


def test_strict_caps_apply_for_higher_marks():
    scores = [_q(1, 10, 9)]
    questions = [{"question_number": 1, "max_marks": 10}]
    out = enforce_upsc_strict_caps(scores, questions, grading_mode="strict", is_upsc=True)
    # cap = (0.5 * 10) - 1 = 4
    assert out[0].obtained_marks == 4


def test_strict_caps_apply_to_sub_scores():
    sub = SubQuestionScore(
        sub_id="a",
        max_marks=10,
        obtained_marks=8,
        ai_feedback="ok",
    )
    score = _q(1, 10, 8, sub_scores=[sub])
    questions = [{"question_number": 1, "max_marks": 10}]
    out = enforce_upsc_strict_caps([score], questions, grading_mode="strict", is_upsc=True)
    assert out[0].sub_scores[0].obtained_marks == 4

