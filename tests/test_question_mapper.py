from app.services.question_mapper import normalize_question_number, detect_margin_labels


def test_normalize_question_number_handles_noisy_tokens():
    expected = {1, 7, 26, 31}
    assert normalize_question_number("Q.07", expected, page_num=2) == 7
    assert normalize_question_number("926", expected, page_num=2) == 26
    assert normalize_question_number("031", expected, page_num=2) == 31
    assert normalize_question_number("2", expected, page_num=2) is None


def test_detect_margin_labels_left_and_right_margin():
    words = [
        {"text": "Q12", "x1": 8, "x2": 42, "y1": 100, "y2": 120},
        {"text": "15.", "x1": 980, "x2": 998, "y1": 200, "y2": 220},
        {"text": "random", "x1": 400, "x2": 500, "y1": 300, "y2": 320},
    ]
    labels = detect_margin_labels(words, expected_qs={12, 15}, width=1000, page_num=3)
    nums = [l["question_number"] for l in labels]
    assert nums == [12, 15]

