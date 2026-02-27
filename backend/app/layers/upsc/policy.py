"""UPSC grading policies."""

from typing import List

from app.models.submission import QuestionScore


def enforce_upsc_strict_caps(
    scores: List[QuestionScore],
    questions: List[dict],
    grading_mode: str,
    is_upsc: bool = False,
) -> List[QuestionScore]:
    """
    Apply strict-mode UPSC caps to question and sub-question scores.
    Caps are only enforced for UPSC exams in strict mode.
    """
    if not is_upsc or grading_mode != "strict":
        return scores

    q_max_map = {q.get("question_number"): float(q.get("max_marks") or 0) for q in questions}
    for score in scores:
        q_max = q_max_map.get(score.question_number, 0)
        obtained = score.obtained_marks if score.obtained_marks is not None else 0
        if q_max > 0:
            # Avoid zeroing low-mark questions (1-2 marks) in strict mode.
            if q_max <= 2:
                cap = q_max
            else:
                half = 0.5 * q_max
                cap = max(0.0, half - 1.0)
            if obtained > cap:
                score.obtained_marks = cap
            elif score.obtained_marks is None:
                score.obtained_marks = obtained

        if score.sub_scores:
            for sub in score.sub_scores:
                sub_max = getattr(sub, "max_marks", None)
                sub_obtained = getattr(sub, "obtained_marks", None)
                sub_max_val = float(sub_max or 0)
                sub_obtained_val = float(sub_obtained or 0)
                if sub_max_val > 0:
                    if sub_max_val <= 2:
                        sub_cap = sub_max_val
                    else:
                        sub_half = 0.5 * sub_max_val
                        sub_cap = max(0.0, sub_half - 1.0)
                    if sub_obtained_val > sub_cap:
                        setattr(sub, "obtained_marks", sub_cap)
                    elif sub_obtained is None:
                        setattr(sub, "obtained_marks", sub_obtained_val)

    return scores
