"""Deterministic blueprint enrichment and contract-based scoring."""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple


QUESTION_TYPES = {
    "mcq",
    "fill_blank",
    "short_answer",
    "descriptive",
    "descriptive_choice",
    "passage_subparts",
    "or_group",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_sub_id(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _normalize_quality(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1.0 and score <= 100.0:
        score = score / 100.0
    return max(0.0, min(1.0, score))


def _extract_attempt_k_of_n(text: str) -> Tuple[Optional[int], Optional[int]]:
    t = (text or "").lower()
    direct = re.search(r"\battempt\s+any\s+(\d+)(?:\s+out\s+of\s+(\d+))?", t)
    if direct:
        k = int(direct.group(1))
        n = int(direct.group(2)) if direct.group(2) else None
        return k, n
    by_word = re.search(r"\bany\s+(one|two|three|four|five)\b", t)
    if by_word:
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        return words.get(by_word.group(1), 1), None
    return None, None


def _contains_choice_signal(text: str) -> bool:
    t = (text or "").lower()
    patterns = (
        r"\bany\s+one\b",
        r"\bany\s+two\b",
        r"\beither\b",
        r"\bor\b",
        r"\battempt\s+any\b",
    )
    return any(re.search(p, t) for p in patterns)


def classify_question_type(question: Dict[str, Any]) -> str:
    """Classify question type using deterministic text/layout signals."""
    existing = str(question.get("question_type") or "").strip().lower()
    mapped_existing = {
        "mcq": "mcq",
        "objective": "mcq",
        "fill_blank": "fill_blank",
        "fill_in_the_blank": "fill_blank",
        "very_short": "short_answer",
        "short": "short_answer",
        "short_answer": "short_answer",
        "long": "descriptive",
        "passage": "passage_subparts",
        "writing": "descriptive",
        "letter": "descriptive",
        "essay": "descriptive",
        "long_answer": "descriptive",
        "theory": "descriptive",
        "descriptive": "descriptive",
    }
    if existing in mapped_existing:
        existing = mapped_existing[existing]
    else:
        existing = ""

    texts: List[str] = [
        str(question.get("rubric") or ""),
        str(question.get("question_text") or ""),
    ]
    for sq in question.get("sub_questions") or []:
        texts.append(str(sq.get("rubric") or sq.get("question_text") or ""))
    combined = " ".join(t for t in texts if t).strip()
    lower = combined.lower()

    has_subparts = bool(question.get("sub_questions"))
    has_option_letters = bool(
        re.search(r"\(([a-dA-D])\)", combined)
        and re.search(r"\(([a-dA-D])\).+?\(([a-dA-D])\)", combined, flags=re.DOTALL)
    )
    has_blank_markers = bool(
        re.search(r"_{3,}", combined)
        or re.search(r"\bfill\s+in\s+the\s+blank", lower)
        or re.search(r"\bblank\b", lower)
    )
    has_word_limit = bool(
        re.search(r"\b\d+\s*[-to]+\s*\d+\s*words?\b", lower)
        or re.search(r"\b\d+\s*words?\b", lower)
    )
    has_instruction_verbs = bool(
        re.search(
            r"\b(state|define|describe|explain|justify|analyze|write|attempt|choose|tick|answer)\b",
            lower,
        )
    )
    has_choice = _contains_choice_signal(combined)
    has_passage = bool(
        re.search(r"\b(read|passage|extract|based on the above)\b", lower)
        and has_subparts
    )

    if has_option_letters or re.search(r"\b(mcq|multiple choice|choose the correct|tick the correct|true/false)\b", lower):
        return "mcq"
    if has_blank_markers:
        return "fill_blank"
    if has_choice and has_subparts:
        return "or_group"
    if has_choice:
        return "descriptive_choice"
    if has_passage:
        return "passage_subparts"
    if has_word_limit or re.search(r"\b(one line|very short|short answer|in 30-40 words|in 40-50 words)\b", lower):
        return "short_answer"
    if has_instruction_verbs and has_subparts:
        return "passage_subparts"
    if existing:
        return existing
    return "descriptive"


def _build_subparts(question: Dict[str, Any], total_marks: float) -> List[Dict[str, Any]]:
    source_subs = question.get("sub_questions") or []
    if not source_subs:
        return []

    subparts: List[Dict[str, Any]] = []
    for sq in source_subs:
        sid = str(sq.get("sub_id") or "").strip()
        if not sid:
            continue
        marks = _to_float(sq.get("max_marks"), 0.0)
        subparts.append(
            {
                "id": sid,
                "marks": marks,
                "rule": "independent",
            }
        )

    if not subparts:
        return []

    positive_marks = [sp["marks"] for sp in subparts if sp["marks"] > 0]
    if not positive_marks and total_marks > 0:
        even = total_marks / float(max(1, len(subparts)))
        for sp in subparts:
            sp["marks"] = even
        positive_marks = [sp["marks"] for sp in subparts if sp["marks"] > 0]

    if total_marks > 0 and positive_marks:
        sum_sub = sum(positive_marks)
        # Keep subpart total aligned with parent marks so marks cannot inflate.
        if sum_sub > 0 and abs(sum_sub - total_marks) > 1e-6:
            scale = total_marks / sum_sub
            for sp in subparts:
                if sp["marks"] > 0:
                    sp["marks"] = sp["marks"] * scale

    for sp in subparts:
        sp["marks"] = round(float(sp["marks"]), 4)

    return subparts


def build_grading_contract(question: Dict[str, Any]) -> Dict[str, Any]:
    q_num = int(question.get("question_number"))
    q_type = classify_question_type(question)
    total_marks = _to_float(question.get("max_marks"), 0.0)
    if total_marks <= 0:
        sub_sum = sum(_to_float(sq.get("max_marks"), 0.0) for sq in (question.get("sub_questions") or []))
        if sub_sum > 0:
            total_marks = sub_sum
        elif q_type in {"mcq", "fill_blank"}:
            total_marks = 1.0

    subparts = _build_subparts(question, total_marks)
    full_text = " ".join(
        [
            str(question.get("rubric") or ""),
            str(question.get("question_text") or ""),
            " ".join(str(sq.get("rubric") or "") for sq in (question.get("sub_questions") or [])),
        ]
    )
    attempt_k, attempt_n = _extract_attempt_k_of_n(full_text)

    aggregation_rule = "sum"
    if q_type in {"mcq", "fill_blank"} and not subparts:
        aggregation_rule = "binary"
    elif attempt_k and attempt_k > 1:
        aggregation_rule = "attempt_k_of_n"
    elif q_type in {"or_group", "descriptive_choice"} or _contains_choice_signal(full_text):
        aggregation_rule = "best_of"
    elif subparts and abs(sum(sp["marks"] for sp in subparts) - total_marks) > 1e-6:
        aggregation_rule = "combined_subparts"

    strictness = "binary" if q_type in {"mcq", "fill_blank"} else "rubric"
    allow_fractional = False if q_type in {"mcq", "fill_blank"} else True

    if aggregation_rule in {"best_of", "attempt_k_of_n"}:
        for sp in subparts:
            sp["rule"] = "combined"

    return {
        "question_number": q_num,
        "question_type": q_type,
        "total_marks": round(float(total_marks), 4),
        "subparts": subparts,
        "aggregation_rule": aggregation_rule,
        "strictness": strictness,
        "allow_fractional": allow_fractional,
        "attempt_k": int(attempt_k) if attempt_k else None,
        "attempt_n": int(attempt_n) if attempt_n else (len(subparts) if subparts else None),
    }


def build_blueprint_enrichment(questions: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for q in questions or []:
        qn = q.get("question_number")
        if qn is None or not str(qn).isdigit():
            continue
        contract = build_grading_contract(q)
        out[int(qn)] = {
            "question_type": contract["question_type"],
            "grading_contract": contract,
        }
    return out


def extract_quality_score(payload: Dict[str, Any], max_marks: float = 0.0) -> float:
    """
    Return quality score in [-1, 1].
    -1 means not found/unavailable, [0..1] means usable quality.
    """
    status = str(payload.get("status") or "").strip().lower()
    if status == "not_found":
        return -1.0

    for key in ("quality_score", "quality", "score_quality", "quality_ratio"):
        score = _normalize_quality(payload.get(key))
        if score is not None:
            return score

    obtained = payload.get("obtained_marks")
    obtained_val = _to_float(obtained, math.nan)
    if not math.isnan(obtained_val):
        if obtained_val < 0:
            return -1.0
        if max_marks > 0:
            return max(0.0, min(1.0, obtained_val / max_marks))
        return max(0.0, min(1.0, obtained_val))

    confidence = _normalize_quality(payload.get("confidence"))
    if confidence is not None:
        return confidence

    if status == "not_attempted":
        return 0.0

    feedback = str(payload.get("ai_feedback") or "").strip()
    return 0.4 if feedback else 0.0


def _binary_mark(quality: float, max_marks: float) -> float:
    return float(max_marks) if quality >= 0.65 else 0.0


def _quantize_step(value: float, step: float, *, mode: str = "down") -> float:
    if step <= 0:
        return float(value)
    units = value / float(step)
    if mode == "down":
        units = math.floor(units + 1e-9)
    else:
        units = round(units)
    return float(units * step)


def _rubric_mark(quality: float, max_marks: float, allow_fractional: bool) -> float:
    raw = max(0.0, min(1.0, quality)) * float(max_marks)
    if allow_fractional:
        # Lenient: for 1-mark school-style answers, a correct meaning should earn full marks.
        if max_marks <= 1.0 and quality >= 0.6:
            return float(max_marks)
        step = 0.5 if max_marks >= 0.5 else float(max_marks)
        mode = "round" if max_marks <= 1.0 else "down"
        return round(_quantize_step(raw, step, mode=mode), 4)
    return float(round(raw))


def apply_grading_contract(
    contract: Dict[str, Any],
    question_quality: float,
    sub_qualities: Optional[Dict[str, float]] = None,
    question_status: str = "graded",
    sub_status: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Apply deterministic scoring contract to quality outputs."""
    sub_qualities = sub_qualities or {}
    sub_status = sub_status or {}

    total_marks = _to_float(contract.get("total_marks"), 1.0)
    aggregation_rule = str(contract.get("aggregation_rule") or "sum")
    strictness = str(contract.get("strictness") or "rubric")
    allow_fractional = bool(contract.get("allow_fractional", True))
    subparts = contract.get("subparts") or []

    q_status = str(question_status or "graded").lower()
    if q_status == "not_found":
        return {
            "obtained_marks": 0.0,
            "subpart_marks": {},
            "selected_subparts": [],
            "cap_applied": False,
        }

    subpart_marks: Dict[str, float] = {}
    selected_subparts: List[str] = []

    if not subparts:
        q_quality = float(question_quality) if question_quality is not None else 0.0
        if q_quality < 0:
            q_mark = 0.0
        elif strictness == "binary":
            q_mark = _binary_mark(q_quality, total_marks)
        else:
            q_mark = _rubric_mark(q_quality, total_marks, allow_fractional)
        obtained = min(total_marks, max(0.0, float(q_mark)))
        return {
            "obtained_marks": round(obtained, 4),
            "subpart_marks": {},
            "selected_subparts": [],
            "cap_applied": False,
        }

    for sp in subparts:
        sid = _normalize_sub_id(sp.get("id"))
        marks = _to_float(sp.get("marks"), 0.0)
        status = str(sub_status.get(sid, "graded") or "graded").lower()
        quality = sub_qualities.get(sid, None)
        if quality is None:
            quality = -1.0 if status == "not_found" else 0.0
        quality_val = float(quality)
        if quality_val < 0:
            sub_mark = 0.0
        elif strictness == "binary":
            sub_mark = _binary_mark(quality_val, marks)
        else:
            sub_mark = _rubric_mark(quality_val, marks, allow_fractional)
        sub_mark = min(marks, max(0.0, float(sub_mark)))
        subpart_marks[sid] = round(sub_mark, 4)

    values = sorted(subpart_marks.items(), key=lambda kv: kv[1], reverse=True)
    if aggregation_rule == "best_of":
        if values:
            selected_subparts = [values[0][0]]
            obtained = values[0][1]
        else:
            obtained = 0.0
    elif aggregation_rule == "attempt_k_of_n":
        k = int(contract.get("attempt_k") or 1)
        k = max(1, min(k, len(values)))
        selected_subparts = [sid for sid, _ in values[:k]]
        obtained = sum(v for _, v in values[:k])
    elif aggregation_rule == "binary":
        # For objective groups, require full binary correctness on counted units.
        if not values:
            obtained = 0.0
        else:
            full_binary = all(
                abs(subpart_marks.get(_normalize_sub_id(sp.get("id")), 0.0) - _to_float(sp.get("marks"), 0.0)) <= 1e-6
                for sp in subparts
                if _to_float(sp.get("marks"), 0.0) > 0
            )
            obtained = total_marks if full_binary else 0.0
    else:
        obtained = sum(v for _, v in values)

    cap_applied = False
    if obtained > total_marks + 1e-6:
        obtained = total_marks
        cap_applied = True

    if not allow_fractional:
        # Ensure objective scores stay on deterministic quantized steps.
        positive_steps = sorted(
            {
                round(_to_float(sp.get("marks"), 0.0), 4)
                for sp in subparts
                if _to_float(sp.get("marks"), 0.0) > 0
            }
        )
        step = positive_steps[0] if positive_steps else total_marks
        if step > 0:
            obtained = round(round(obtained / step) * step, 4)
            obtained = min(total_marks, max(0.0, obtained))

    return {
        "obtained_marks": round(float(obtained), 4),
        "subpart_marks": subpart_marks,
        "selected_subparts": selected_subparts,
        "cap_applied": cap_applied,
    }
