from app.services.score_normalization import normalize_submission_scores


def test_normalization_backfills_missing_questions_in_exam_order():
    submission = {
        "submission_id": "sub_1",
        "question_scores": [
            {
                "question_number": 1,
                "obtained_marks": 5,
                "max_marks": 10,
                "status": "graded",
            }
        ],
    }
    exam = {
        "total_marks": 40,
        "questions": [
            {"question_number": 1, "max_marks": 10, "sub_questions": []},
            {"question_number": 2, "max_marks": 15, "sub_questions": []},
            {
                "question_number": 3,
                "max_marks": 15,
                "sub_questions": [
                    {"sub_id": "a", "max_marks": 5},
                    {"sub_id": "b", "max_marks": 10},
                ],
            },
        ],
    }

    result = normalize_submission_scores(submission, exam, source="test")
    scores = result["question_scores"]

    assert [q["question_number"] for q in scores] == [1, 2, 3]
    assert scores[1]["status"] == "not_found"
    assert scores[1]["obtained_marks"] == 0
    assert len(scores[2]["sub_scores"]) == 2
    assert result["total_score"] == 5
    assert result["percentage"] == 12.5


def test_normalization_drops_unknown_questions_when_exam_structure_exists():
    submission = {
        "submission_id": "sub_2",
        "question_scores": [
            {"question_number": 1, "obtained_marks": 1, "max_marks": 0, "status": "graded"},
            {"question_number": "Q1", "obtained_marks": 2, "max_marks": 5, "status": "graded"},
            {"question_number": 99, "obtained_marks": 8, "max_marks": 10, "status": "graded"},
        ],
    }
    exam = {
        "total_marks": 20,
        "questions": [
            {"question_number": 1, "max_marks": 10, "sub_questions": []},
            {"question_number": 2, "max_marks": 10, "sub_questions": []},
        ],
    }

    result = normalize_submission_scores(submission, exam, source="test")
    scores = result["question_scores"]

    assert [q["question_number"] for q in scores] == [1, 2]
    assert scores[0]["obtained_marks"] == 2
    assert scores[1]["status"] == "not_found"
    assert result["total_score"] == 2

