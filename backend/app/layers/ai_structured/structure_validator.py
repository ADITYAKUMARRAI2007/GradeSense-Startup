"""Layer-5 consistency validation with repair task generation."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger

from .safe_numeric import parse_section_math_expression, safe_float, safe_int
from .validation import normalize_structure_payload


def _contiguous(numbers: List[int]) -> Tuple[bool, List[int], List[int]]:
    if not numbers:
        return False, [], []
    uniq = sorted(set(numbers))
    expected = list(range(uniq[0], uniq[-1] + 1))
    missing = sorted(set(expected) - set(uniq))
    return uniq == expected, uniq, missing


def _compute_or_groups_map(questions: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    grouped: Dict[str, List[int]] = defaultdict(list)
    for q in questions:
        gid = str(q.get("or_group_id") or "").strip()
        if not gid:
            continue
        grouped[gid].append(safe_int(q.get("number"), 0))
    return {gid: sorted({n for n in nums if n > 0}) for gid, nums in grouped.items() if len(set(nums)) >= 2}


def _compute_attempt_rules(questions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    rules: Dict[str, Dict[str, Any]] = {}
    for q in questions:
        qn = safe_int(q.get("number"), 0)
        if qn <= 0:
            continue
        sub_count = len(q.get("subquestions") or [])
        q_type = str(q.get("question_type") or "").strip().lower()
        if q.get("or_group_id"):
            rule = "best_of"
        elif q_type in {"mcq", "fill_blank"} and sub_count <= 1:
            rule = "binary"
        else:
            rule = "sum"
        rules[str(qn)] = {
            "question_number": qn,
            "rule": rule,
            "subparts": sub_count,
        }
    return rules


def _compute_effective_total(questions: List[Dict[str, Any]]) -> float:
    groups: Dict[str, List[float]] = defaultdict(list)
    total = 0.0
    for q in questions:
        marks = max(0.0, safe_float(q.get("marks"), 0.0))
        gid = str(q.get("or_group_id") or "").strip()
        if gid:
            groups[gid].append(marks)
        else:
            total += marks
    for _, vals in groups.items():
        total += max(vals) if vals else 0.0
    return round(total, 4)


def validate_structure(
    structure: Dict[str, Any],
    *,
    header_total_marks: Optional[float] = None,
    header_total_reliable: bool = False,
    expected_question_count: Optional[int] = None,
    visual_entities: Optional[Dict[str, Any]] = None,
    question_audit_tree: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    normalized = normalize_structure_payload(structure or {})
    questions = list(normalized.get("questions") or [])
    q_numbers = [safe_int(q.get("number"), 0) for q in questions if safe_int(q.get("number"), 0) > 0]

    errors: List[str] = []
    warnings: List[str] = []
    repair_tasks: List[str] = []

    counter = Counter(q_numbers)
    duplicate_numbers = sorted([n for n, c in counter.items() if c > 1])
    contiguous, unique_numbers, missing_numbers = _contiguous(q_numbers)

    if not questions:
        errors.append("no_questions_extracted")
        repair_tasks.append("missing_marks")
    if duplicate_numbers:
        errors.append(f"duplicate_question_numbers:{duplicate_numbers}")
        repair_tasks.append("numbering_explosion")
    if unique_numbers and unique_numbers[0] != 1:
        errors.append(f"ghost_question_numbers:start={unique_numbers[0]}")
        repair_tasks.append("numbering_explosion")
    if not contiguous:
        errors.append(f"numbering_not_contiguous:missing={missing_numbers}")
        repair_tasks.append("numbering_explosion")

    # Duplicate subparts + subpart sum check.
    subpart_sum_errors = 0
    duplicate_subparts = 0
    subpart_overflow: List[Dict[str, Any]] = []
    for q in questions:
        qn = safe_int(q.get("number"), 0)
        q_marks = max(0.0, safe_float(q.get("marks"), 0.0))
        subparts = list(q.get("subquestions") or [])
        labels = [str(sq.get("label") or "").strip().lower() for sq in subparts if str(sq.get("label") or "").strip()]
        if len(labels) != len(set(labels)):
            duplicate_subparts += 1

        sub_sum = round(sum(max(0.0, safe_float(sq.get("marks"), 0.0)) for sq in subparts), 4)
        logger.info("SUBPART_SUM_CHECK q=%s parent=%s sub_sum=%s subparts=%s", qn, round(q_marks, 4), sub_sum, len(subparts))
        if subparts and abs(sub_sum - q_marks) > 1e-6:
            subpart_sum_errors += 1
            subpart_overflow.append(
                {
                    "question_number": qn,
                    "subpart_sum": sub_sum,
                    "parent_marks": round(q_marks, 4),
                }
            )

    if duplicate_subparts > 0:
        errors.append(f"duplicate_subparts:{duplicate_subparts}")
        repair_tasks.append("duplicate_subparts")
    if subpart_sum_errors > 0:
        errors.append(f"subpart_sum_mismatch:{subpart_sum_errors}")
        repair_tasks.append("subpart_sum_mismatch")
        logger.warning("SUBPART_SUM_MISMATCH count=%s", subpart_sum_errors)
        logger.warning("SUBPART_SUM_DETAILS items=%s", subpart_overflow)
    else:
        logger.info("SUBPART_SUM_OK questions=%s", len(questions))

    # Section math consistency.
    section_mismatch = 0
    ordered = sorted(questions, key=lambda q: safe_int(q.get("number"), 0))
    by_num = {safe_int(q.get("number"), 0): q for q in ordered}
    qnums = [safe_int(q.get("number"), 0) for q in ordered if safe_int(q.get("number"), 0) > 0]

    rules = list(normalized.get("section_math_rules") or [])
    if rules:
        for rule in rules:
            start_q = safe_int(rule.get("start_question"), 0)
            count = safe_int(rule.get("count"), 0)
            per = safe_float(rule.get("marks_per_question"), 0.0)
            total = safe_float(rule.get("total"), 0.0)
            if start_q <= 0 or count <= 0 or per <= 0 or start_q not in qnums:
                continue
            start_idx = qnums.index(start_q)
            run_nums = qnums[start_idx:start_idx + count]
            run_sum = round(sum(max(0.0, safe_float((by_num.get(qn) or {}).get("marks"), 0.0)) for qn in run_nums), 4)
            if abs(run_sum - round(total, 4)) > 1e-6:
                section_mismatch += 1
            for qn in run_nums:
                q = by_num.get(qn) or {}
                if abs(max(0.0, safe_float(q.get("marks"), 0.0)) - per) > 1e-6:
                    section_mismatch += 1
    else:
        cursor = 0
        for block in (normalized.get("section_math_blocks") or []):
            parsed = parse_section_math_expression((block or {}).get("expression"))
            if parsed:
                count, per, _ = parsed
            else:
                count = safe_int((block or {}).get("question_count"), 0)
                per = safe_float((block or {}).get("per_question_marks"), 0.0)
            if count <= 0 or per <= 0:
                continue
            start_q = safe_int(((block or {}).get("range") or {}).get("start"), 0)
            if start_q > 0 and start_q in qnums:
                start_idx = qnums.index(start_q)
                run = [by_num.get(qn) for qn in qnums[start_idx:start_idx + count]]
            else:
                run = ordered[cursor:cursor + count]
                cursor += count
            for q in run:
                if not q:
                    continue
                if abs(max(0.0, safe_float(q.get("marks"), 0.0)) - per) > 1e-6 and str(q.get("mark_source") or "").strip().lower() != "margin":
                    section_mismatch += 1
    if section_mismatch > 0:
        errors.append(f"section_math_inconsistency:{section_mismatch}")
        repair_tasks.append("section_math_inconsistency")

    # OR integrity.
    or_groups_map = _compute_or_groups_map(questions)
    or_integrity_errors = 0
    by_num = {safe_int(q.get("number"), 0): q for q in questions}
    for _, members in or_groups_map.items():
        if len(members) < 2:
            or_integrity_errors += 1
            continue
        marks = [round(max(0.0, safe_float((by_num.get(qn) or {}).get("marks"), 0.0)), 4) for qn in members]
        if len(set(marks)) > 1:
            or_integrity_errors += 1
    if or_integrity_errors > 0:
        errors.append(f"or_group_integrity:{or_integrity_errors}")
        repair_tasks.append("or_group_integrity")

    # Visual evidence coverage.
    visual_map = {
        safe_int(row.get("number"), 0)
        for row in ((visual_entities or {}).get("questions") or [])
        if safe_int(row.get("number"), 0) > 0
    }
    evidence_covered = 0
    evidence_missing: List[int] = []
    for q in questions:
        qn = safe_int(q.get("number"), 0)
        has_image = bool(q.get("image_evidence") or [])
        has_visual = qn in visual_map
        if has_image or has_visual:
            evidence_covered += 1
        else:
            evidence_missing.append(qn)
    visual_coverage = round((evidence_covered / float(len(questions))) if questions else 0.0, 4)
    if visual_coverage < 0.8:
        warnings.append(f"visual_coverage_low:{visual_coverage}")
        repair_tasks.append("low_visual_coverage")

    # Mark coverage and total.
    marked_questions = sum(1 for q in questions if max(0.0, safe_float(q.get("marks"), 0.0)) > 0)
    mark_coverage = round((marked_questions / float(len(questions))) if questions else 0.0, 4)
    if mark_coverage < 0.8:
        errors.append(f"mark_coverage_low:{mark_coverage}")
        repair_tasks.append("missing_marks")

    effective_total = _compute_effective_total(questions)
    if header_total_reliable and header_total_marks is not None and header_total_marks > 0:
        expected = round(float(header_total_marks), 4)
        if abs(effective_total - expected) > 1e-6:
            errors.append(f"total_marks_mismatch:actual={effective_total} expected={expected}")
            repair_tasks.append("missing_marks")
        else:
            logger.info("MARK_SUM_OK total=%s", expected)
    else:
        logger.info("MARK_SUM_OK total=%s source=effective_only", effective_total)

    if expected_question_count and expected_question_count > 0 and len(unique_numbers) != int(expected_question_count):
        errors.append(f"question_count_mismatch:actual={len(unique_numbers)} expected={int(expected_question_count)}")
        repair_tasks.append("numbering_explosion")

    # Audit tree availability check.
    if question_audit_tree is None or len(question_audit_tree) != len(unique_numbers):
        warnings.append("audit_tree_incomplete")

    # Dedupe tasks while preserving order.
    deduped_tasks: List[str] = []
    seen = set()
    for task in repair_tasks:
        if task in seen:
            continue
        seen.add(task)
        deduped_tasks.append(task)

    report = {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "repair_tasks": deduped_tasks,
        "question_numbers": unique_numbers,
        "duplicate_numbers": duplicate_numbers,
        "missing_numbers": missing_numbers,
        "numbering_contiguous": contiguous,
        "subpart_overflow": subpart_overflow,
        "visual_evidence_missing": sorted(set(evidence_missing)),
        "effective_total_marks": effective_total,
        "question_count": len(unique_numbers),
        "mark_coverage": mark_coverage,
        "visual_coverage": visual_coverage,
        "or_groups_map": or_groups_map,
        "attempt_rules": _compute_attempt_rules(questions),
        "normalized": normalized,
        "section_math_rules": list(normalized.get("section_math_rules") or []),
    }

    logger.info(
        "STRUCTURE_VALIDATED valid=%s questions=%s total=%s coverage=%.4f errors=%s repair_tasks=%s",
        report["is_valid"],
        len(unique_numbers),
        effective_total,
        mark_coverage,
        len(errors),
        len(deduped_tasks),
    )
    return report


__all__ = ["validate_structure"]
