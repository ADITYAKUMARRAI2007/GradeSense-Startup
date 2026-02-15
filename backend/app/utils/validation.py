"""Validation utilities for questions, files, etc."""

from typing import List, Dict, Any, Optional


def validate_question_structure(questions: List[dict]) -> Dict[str, Any]:
    """
    Validate question structure for consistency.
    Returns validation result with warnings/errors.
    """
    warnings = []
    errors = []

    if not questions:
        errors.append("No questions found")
        return {"valid": False, "errors": errors, "warnings": warnings}

    total_marks = 0
    question_numbers = set()

    for idx, q in enumerate(questions):
        q_num = q.get("question_number")

        if not q_num:
            errors.append(f"Question at index {idx} is missing question_number")
            continue

        if q_num in question_numbers:
            errors.append(f"Duplicate question number: Q{q_num}")
        question_numbers.add(q_num)

        q_marks = q.get("max_marks", 0)
        if q_marks <= 0:
            errors.append(f"Q{q_num}: Missing or invalid max_marks")

        total_marks += q_marks

        sub_questions = q.get("sub_questions", [])
        if sub_questions:
            sub_total = 0
            for sub in sub_questions:
                sub_marks = sub.get("max_marks", 0)
                sub_total += sub_marks

                if "sub_questions" in sub and sub["sub_questions"]:
                    nested_total = sum(ssub.get("max_marks", 0) for ssub in sub["sub_questions"])
                    if abs(nested_total - sub_marks) > 0.1:
                        warnings.append(f"Q{q_num}({sub.get('sub_id')}): Sub-question marks ({nested_total}) don't match parent ({sub_marks})")

            if abs(sub_total - q_marks) > 0.1:
                warnings.append(f"Q{q_num}: Sub-question total ({sub_total}) doesn't match question total ({q_marks})")

    if question_numbers:
        max_num = max(question_numbers)
        expected = set(range(1, max_num + 1))
        missing = expected - question_numbers
        if missing:
            warnings.append(f"Missing question numbers: {sorted(missing)}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "total_marks": total_marks,
        "question_count": len(questions)
    }


def infer_upsc_paper(exam_name: str = None, subject_name: str = None) -> Optional[str]:
    """Infer UPSC paper type from exam/subject name."""
    text = f"{exam_name or ''} {subject_name or ''}".lower()
    if "essay" in text:
        return "Essay"
    if "gs1" in text or "gs-1" in text or "gs 1" in text or "general studies 1" in text:
        return "GS-1"
    if "gs2" in text or "gs-2" in text or "gs 2" in text or "general studies 2" in text:
        return "GS-2"
    if "gs3" in text or "gs-3" in text or "gs 3" in text or "general studies 3" in text:
        return "GS-3"
    if "gs4" in text or "gs-4" in text or "gs 4" in text or "general studies 4" in text or "ethics" in text:
        return "GS-4"
    return None
