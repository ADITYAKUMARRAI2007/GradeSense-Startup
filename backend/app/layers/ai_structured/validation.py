"""Deterministic validators and hash helpers for question structures."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _normalize_subquestion(sub: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "label": str(sub.get("label") or "").strip(),
        "text": str(sub.get("text") or "").strip(),
        "marks": round(_to_float(sub.get("marks"), 0.0), 4),
        "mark_source": str(sub.get("mark_source") or "inferred").strip().lower(),
        "mark_confidence": round(_to_float(sub.get("mark_confidence"), 0.0), 4),
        "confidence": round(_to_float(sub.get("confidence"), 0.0), 4),
    }


def normalize_structure_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    questions = payload.get("questions") or []
    normalized_questions: List[Dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        subquestions = [_normalize_subquestion(sq) for sq in (q.get("subquestions") or []) if isinstance(sq, dict)]
        subquestions.sort(key=lambda item: str(item.get("label") or ""))
        normalized_questions.append(
            {
                "number": qn,
                "section": (str(q.get("section") or "").strip() or None),
                "instruction": (str(q.get("instruction") or "").strip() or None),
                "question_text": str(q.get("question_text") or "").strip(),
                "question_type": str(q.get("question_type") or "descriptive").strip().lower(),
                "marks": round(_to_float(q.get("marks"), 0.0), 4),
                "options": list(q.get("options") or []) or None,
                "subquestions": subquestions,
                "or_group_id": (str(q.get("or_group_id") or "").strip() or None),
                "image_evidence": list(q.get("image_evidence") or []),
                "ai_confidence": round(_to_float(q.get("ai_confidence"), 0.0), 4),
                "mark_source": str(q.get("mark_source") or "inferred").strip().lower(),
                "mark_confidence": round(_to_float(q.get("mark_confidence"), 0.0), 4),
                "confidence": round(_to_float(q.get("confidence"), _to_float(q.get("ai_confidence"), 0.0)), 4),
            }
        )

    normalized_questions.sort(key=lambda item: int(item["number"]))

    # Drop singleton OR groups; OR semantics require at least two branches.
    or_counts = Counter(
        str(q.get("or_group_id"))
        for q in normalized_questions
        if q.get("or_group_id") is not None
    )
    for q in normalized_questions:
        gid = q.get("or_group_id")
        if gid is None:
            continue
        if or_counts.get(str(gid), 0) < 2:
            q["or_group_id"] = None

    total_questions = _to_int(payload.get("total_questions"), len(normalized_questions))
    total_marks = round(_to_float(payload.get("total_marks"), 0.0), 4)
    effective_total_marks = round(_to_float(payload.get("effective_total_marks"), total_marks), 4)
    section_math_blocks = []
    for block in (payload.get("section_math_blocks") or []):
        if not isinstance(block, dict):
            continue
        range_raw = block.get("range")
        range_obj = None
        if isinstance(range_raw, dict):
            start = _to_int(range_raw.get("start"), 0)
            end = _to_int(range_raw.get("end"), 0)
            if start > 0 and end >= start:
                range_obj = {"start": start, "end": end}
        section_math_blocks.append(
            {
                "section": (str(block.get("section") or "").strip() or None),
                "expression": str(block.get("expression") or "").strip(),
                "question_count": _to_int(block.get("question_count"), 0),
                "per_question_marks": round(_to_float(block.get("per_question_marks"), 0.0), 4),
                "total_marks": round(_to_float(block.get("total_marks"), 0.0), 4),
                "page_index": _to_int(block.get("page_index"), 0),
                "confidence": round(_to_float(block.get("confidence"), 0.0), 4),
                "range": range_obj,
            }
        )

    section_math_rules = []
    for rule in (payload.get("section_math_rules") or []):
        if not isinstance(rule, dict):
            continue
        start_q = _to_int(rule.get("start_question"), 0)
        count = _to_int(rule.get("count"), 0)
        per = round(_to_float(rule.get("marks_per_question"), 0.0), 4)
        total = round(_to_float(rule.get("total"), 0.0), 4)
        if start_q <= 0 or count <= 0 or per <= 0 or total <= 0:
            continue
        section_math_rules.append(
            {
                "start_question": start_q,
                "count": count,
                "marks_per_question": per,
                "total": total,
                "source_page": _to_int(rule.get("source_page"), 0),
            }
        )

    return {
        "questions": normalized_questions,
        "section_math_blocks": section_math_blocks,
        "section_math_rules": section_math_rules,
        "total_questions": max(total_questions, len(normalized_questions)),
        "total_marks": total_marks,
        "effective_total_marks": effective_total_marks,
        "numbering_contiguous": bool(payload.get("numbering_contiguous", False)),
    }


def compute_or_groups_map(questions: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    grouped: Dict[str, List[int]] = defaultdict(list)
    for q in questions:
        gid = str(q.get("or_group_id") or "").strip()
        if not gid:
            continue
        grouped[gid].append(int(q.get("number")))
    return {k: sorted(set(v)) for k, v in grouped.items()}


def compute_attempt_rules(questions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    rules: Dict[str, Dict[str, Any]] = {}
    for q in questions:
        qn = int(q.get("number"))
        sub_count = len(q.get("subquestions") or [])
        q_type = str(q.get("question_type") or "").lower()
        attempt_rule = "sum"
        if q.get("or_group_id"):
            attempt_rule = "best_of"
        elif q_type in {"mcq", "fill_blank"} and sub_count <= 1:
            attempt_rule = "binary"
        rules[str(qn)] = {
            "question_number": qn,
            "rule": attempt_rule,
            "subparts": sub_count,
        }
    return rules


def compute_effective_total(questions: List[Dict[str, Any]]) -> float:
    grouped: Dict[Optional[str], List[Dict[str, Any]]] = defaultdict(list)
    for q in questions:
        grouped[q.get("or_group_id")].append(q)

    total = 0.0
    for gid, qs in grouped.items():
        if gid:
            # OR block counts once, pick max branch marks.
            branch_marks = [max(_to_float(q.get("marks"), 0.0), 0.0) for q in qs]
            total += max(branch_marks) if branch_marks else 0.0
        else:
            for q in qs:
                total += max(_to_float(q.get("marks"), 0.0), 0.0)
    return round(total, 4)


def _contiguous(numbers: List[int]) -> Tuple[bool, List[int], List[int]]:
    if not numbers:
        return False, [], []
    sorted_nums = sorted(set(numbers))
    expected = list(range(sorted_nums[0], sorted_nums[-1] + 1))
    missing = sorted(set(expected) - set(sorted_nums))
    return sorted_nums == expected, sorted_nums, missing


def validate_structure(
    structure: Dict[str, Any],
    *,
    expected_total_marks: Optional[float] = None,
    expected_question_count: Optional[int] = None,
    baseline_numbers: Optional[List[int]] = None,
    baseline_total_marks: Optional[float] = None,
) -> Dict[str, Any]:
    normalized = normalize_structure_payload(structure)
    questions = normalized["questions"]
    question_numbers = [int(q["number"]) for q in questions]
    number_counter = Counter(question_numbers)
    duplicate_numbers = sorted([n for n, c in number_counter.items() if c > 1])

    contiguous, unique_numbers, missing_numbers = _contiguous(question_numbers)

    subpart_overflow: List[Dict[str, Any]] = []
    visual_evidence_missing: List[int] = []
    for q in questions:
        parent_marks = _to_float(q.get("marks"), 0.0)
        sub_sum = sum(_to_float(sq.get("marks"), 0.0) for sq in (q.get("subquestions") or []))
        if parent_marks > 0 and sub_sum > parent_marks + 1e-6:
            subpart_overflow.append(
                {
                    "question_number": int(q.get("number")),
                    "subpart_sum": round(sub_sum, 4),
                    "parent_marks": round(parent_marks, 4),
                }
            )
        evidence = q.get("image_evidence") or []
        if len(evidence) == 0:
            visual_evidence_missing.append(int(q.get("number")))

    effective_total_marks = compute_effective_total(questions)

    errors: List[str] = []
    warnings: List[str] = []

    if not questions:
        errors.append("no_questions_extracted")
    if duplicate_numbers:
        errors.append(f"duplicate_question_numbers:{duplicate_numbers}")
    if not contiguous:
        errors.append(f"numbering_not_contiguous:missing={missing_numbers}")
    if subpart_overflow:
        errors.append(f"subpart_overflow:{len(subpart_overflow)}")
    if visual_evidence_missing:
        errors.append(f"visual_evidence_missing:{sorted(set(visual_evidence_missing))}")

    if expected_question_count and expected_question_count > 0 and len(unique_numbers) != int(expected_question_count):
        mismatch = abs(len(unique_numbers) - int(expected_question_count))
        if mismatch <= 1:
            warnings.append(
                f"question_count_mismatch:actual={len(unique_numbers)} expected={int(expected_question_count)}"
            )
        else:
            errors.append(
                f"question_count_mismatch:actual={len(unique_numbers)} expected={int(expected_question_count)}"
            )

    if expected_total_marks is not None and expected_total_marks > 0:
        if abs(effective_total_marks - float(expected_total_marks)) > 1e-6:
            errors.append(
                f"total_marks_mismatch:actual={effective_total_marks} expected={round(float(expected_total_marks), 4)}"
            )

    if baseline_numbers is not None and sorted(set(baseline_numbers)) != unique_numbers:
        errors.append("reconstruction_number_set_changed")

    if baseline_total_marks is not None and abs(float(baseline_total_marks) - effective_total_marks) > 1e-6:
        errors.append("reconstruction_total_marks_changed")

    validated = {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "question_numbers": unique_numbers,
        "duplicate_numbers": duplicate_numbers,
        "missing_numbers": missing_numbers,
        "numbering_contiguous": contiguous,
        "subpart_overflow": subpart_overflow,
        "visual_evidence_missing": sorted(set(visual_evidence_missing)),
        "effective_total_marks": effective_total_marks,
        "question_count": len(unique_numbers),
        "or_groups_map": compute_or_groups_map(questions),
        "attempt_rules": compute_attempt_rules(questions),
        "normalized": normalized,
    }
    return validated


def validate_reconstruction_guardrails(
    previous_structure: Dict[str, Any],
    next_structure: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    prev_norm = normalize_structure_payload(previous_structure)
    next_norm = normalize_structure_payload(next_structure)

    prev_numbers = [int(q["number"]) for q in prev_norm["questions"]]
    next_numbers = [int(q["number"]) for q in next_norm["questions"]]
    prev_total = compute_effective_total(prev_norm["questions"])
    next_total = compute_effective_total(next_norm["questions"])

    errors: List[str] = []
    if sorted(set(prev_numbers)) != sorted(set(next_numbers)):
        errors.append("question_numbers_before_after_mismatch")
    if abs(prev_total - next_total) > 1e-6:
        errors.append("total_marks_before_after_mismatch")
    return len(errors) == 0, errors


def structure_hash(structure: Dict[str, Any]) -> str:
    normalized = normalize_structure_payload(structure)
    encoded = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
