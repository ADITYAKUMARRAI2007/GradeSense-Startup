from app.services import grading


def test_partial_grading_override_enabled_for_usable_mapping(monkeypatch):
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_GRADING_ENABLED", True)
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_MIN_MAPPED", 1)
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_MIN_COVERAGE", 0.85)

    assert grading._allow_college_v2_partial_grading(
        college_v2_active=True,
        mapped_questions_count=4,
        mapping_coverage=0.97,
    )


def test_partial_grading_override_disabled_when_coverage_low(monkeypatch):
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_GRADING_ENABLED", True)
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_MIN_MAPPED", 1)
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_MIN_COVERAGE", 0.85)

    assert not grading._allow_college_v2_partial_grading(
        college_v2_active=True,
        mapped_questions_count=4,
        mapping_coverage=0.50,
    )


def test_partial_grading_override_disabled_for_non_college(monkeypatch):
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_GRADING_ENABLED", True)
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_MIN_MAPPED", 1)
    monkeypatch.setattr(grading, "COLLEGE_V2_PARTIAL_MIN_COVERAGE", 0.85)

    assert not grading._allow_college_v2_partial_grading(
        college_v2_active=False,
        mapped_questions_count=10,
        mapping_coverage=1.0,
    )

