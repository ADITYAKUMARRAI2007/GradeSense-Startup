"""Helpers for exam question-blueprint health and lock state."""

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional
import hashlib
import json
import os
import re


SECTION_MARKERS = (
    "section a",
    "section b",
    "section c",
    "part a",
    "part b",
    "part c",
    "option i",
    "option ii",
)


def parse_question_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = int(value)
        return num if num > 0 else None
    text = str(value).strip()
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    if not m:
        return None
    num = int(m.group(1))
    return num if num > 0 else None


def parse_question_numbers(questions: List[dict]) -> List[int]:
    out = []
    for q in questions or []:
        n = parse_question_number((q or {}).get("question_number"))
        if n is not None:
            out.append(n)
    return out


def _count_sections(questions: List[dict]) -> int:
    seen = set()
    for q in questions or []:
        text = f"{(q or {}).get('question_text', '')} {(q or {}).get('rubric', '')}".lower()
        for marker in SECTION_MARKERS:
            if marker in text:
                seen.add(marker)
    return len(seen)


def compute_blueprint_health(
    questions: List[dict],
    expected_count: Optional[int] = None,
    failed_chunks: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    parsed = parse_question_numbers(questions)
    counter = Counter(parsed)
    duplicates = sorted([k for k, v in counter.items() if v > 1])
    unique_numbers = sorted(set(parsed))

    expected_numbers: List[int] = []
    if expected_count and expected_count > 0:
        expected_numbers = list(range(1, int(expected_count) + 1))
    elif unique_numbers and unique_numbers[0] == 1:
        expected_numbers = list(range(1, unique_numbers[-1] + 1))

    missing = sorted(set(expected_numbers) - set(unique_numbers)) if expected_numbers else []
    unexpected = sorted(set(unique_numbers) - set(expected_numbers)) if expected_numbers else []

    numbering_contiguous = bool(unique_numbers) and unique_numbers == list(range(unique_numbers[0], unique_numbers[-1] + 1))

    target_size = len(expected_numbers) if expected_numbers else len(unique_numbers)
    if target_size <= 0:
        completeness_score = 0.0
    else:
        completeness_score = round(max(0.0, 1.0 - (len(missing) / float(target_size))), 3)

    is_complete = (
        bool(unique_numbers)
        and (len(missing) == 0)
        and (len(duplicates) == 0)
        and numbering_contiguous
    )

    return {
        "question_count": len(unique_numbers),
        "parsed_numbers": unique_numbers,
        "missing": missing,
        "duplicates": duplicates,
        "unexpected": unexpected,
        "expected_count": int(expected_count) if expected_count else None,
        "completeness_score": completeness_score,
        "numbering_contiguous": numbering_contiguous,
        "sections_detected": _count_sections(questions or []),
        "failed_chunks": list(failed_chunks or []),
        "is_complete": is_complete,
    }


def derive_expected_question_count(exam: Dict[str, Any], fallback_questions: Optional[List[dict]] = None) -> Optional[int]:
    src = fallback_questions if fallback_questions is not None else (exam.get("questions") or [])
    nums = parse_question_numbers(src)
    inferred_count: Optional[int] = None
    if nums:
        if min(nums) == 1:
            inferred_count = max(nums)
        else:
            inferred_count = len(sorted(set(nums)))

    candidates = [
        exam.get("questions_count"),
        exam.get("num_questions"),
        exam.get("expected_question_count"),
    ]
    for c in candidates:
        try:
            if c is None:
                continue
            candidate = int(c)
            if candidate <= 0:
                continue
            # Guard against stale/manual metadata such as num_questions=1 when
            # extracted numbering clearly spans a larger contiguous range.
            if (
                inferred_count is not None
                and nums
                and min(nums) == 1
                and candidate < inferred_count
            ):
                return inferred_count
            return candidate
        except Exception:
            continue
    return inferred_count


def evaluate_blueprint_lock_readiness(
    exam: Dict[str, Any],
    questions: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """
    Evaluate whether a blueprint can be safely locked for grading.

    Returns:
      {
        "can_lock": bool,
        "health": {...},
        "issues": [str],
        "question_count": int,
        "question_paper_pages": int,
      }
    """
    q_list = questions if questions is not None else (exam.get("questions") or [])
    expected_count = derive_expected_question_count(exam or {}, fallback_questions=q_list)
    health = compute_blueprint_health(
        q_list or [],
        expected_count=expected_count,
        failed_chunks=((exam or {}).get("blueprint_health", {}) or {}).get("failed_chunks"),
    )

    question_count = int(health.get("question_count", 0) or 0)
    question_paper_pages = int((exam or {}).get("question_paper_pages", 0) or 0)
    completeness_threshold = float(os.getenv("COLLEGE_V2_BLUEPRINT_HEALTH_THRESHOLD", "0.92"))

    issues: List[str] = []
    if not q_list:
        issues.append("no_questions")
    if question_paper_pages >= 30 and question_count < 20:
        issues.append("too_few_questions_for_large_paper")
    elif question_paper_pages >= 15 and question_count < 10:
        issues.append("too_few_questions")
    if not bool(health.get("numbering_contiguous")):
        issues.append("numbering_not_contiguous")
    if float(health.get("completeness_score", 0.0) or 0.0) < completeness_threshold:
        issues.append("blueprint_completeness_below_threshold")
    if not bool(health.get("is_complete")):
        issues.append("incomplete_blueprint")

    return {
        "can_lock": len(issues) == 0,
        "health": health,
        "issues": issues,
        "question_count": question_count,
        "question_paper_pages": question_paper_pages,
    }


def normalize_question_structure_v2(structure: Dict[str, Any]) -> Dict[str, Any]:
    questions = []
    for q in (structure or {}).get("questions", []) or []:
        if not isinstance(q, dict):
            continue
        qn = parse_question_number(q.get("number"))
        if qn is None:
            continue
        subquestions = []
        for sq in q.get("subquestions", []) or []:
            if not isinstance(sq, dict):
                continue
            label = str(sq.get("label") or "").strip()
            if not label:
                continue
            subquestions.append(
                {
                    "label": label,
                    "text": str(sq.get("text") or "").strip(),
                    "marks": float(sq.get("marks") or 0.0),
                }
            )
        subquestions.sort(key=lambda s: s.get("label", ""))
        questions.append(
            {
                "number": int(qn),
                "section": (str(q.get("section") or "").strip() or None),
                "instruction": (str(q.get("instruction") or "").strip() or None),
                "question_text": str(q.get("question_text") or "").strip(),
                "question_type": str(q.get("question_type") or "descriptive").strip().lower(),
                "marks": float(q.get("marks") or 0.0),
                "options": list(q.get("options") or []) or None,
                "subquestions": subquestions,
                "or_group_id": (str(q.get("or_group_id") or "").strip() or None),
                "image_evidence": list(q.get("image_evidence") or []),
                "ai_confidence": float(q.get("ai_confidence") or 0.0),
            }
        )
    questions.sort(key=lambda item: int(item["number"]))
    return {
        "questions": questions,
        "total_questions": int((structure or {}).get("total_questions") or len(questions)),
        "total_marks": float((structure or {}).get("total_marks") or 0.0),
        "numbering_contiguous": bool((structure or {}).get("numbering_contiguous", False)),
    }


def compute_structure_hash(structure: Dict[str, Any]) -> str:
    normalized = normalize_question_structure_v2(structure)
    payload = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_or_groups_map_v2(structure: Dict[str, Any]) -> Dict[str, List[int]]:
    groups: Dict[str, List[int]] = defaultdict(list)
    for q in (normalize_question_structure_v2(structure).get("questions") or []):
        gid = q.get("or_group_id")
        if not gid:
            continue
        groups[str(gid)].append(int(q.get("number")))
    return {k: sorted(set(v)) for k, v in groups.items()}


def compute_effective_total_marks_v2(structure: Dict[str, Any]) -> float:
    normalized = normalize_question_structure_v2(structure)
    grouped: Dict[Optional[str], List[dict]] = defaultdict(list)
    for q in normalized.get("questions") or []:
        grouped[q.get("or_group_id")].append(q)

    total = 0.0
    for gid, group_questions in grouped.items():
        if gid:
            total += max(float(q.get("marks") or 0.0) for q in group_questions) if group_questions else 0.0
        else:
            total += sum(float(q.get("marks") or 0.0) for q in group_questions)
    return round(total, 4)


def compute_attempt_rules_v2(structure: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rules: Dict[str, Dict[str, Any]] = {}
    normalized = normalize_question_structure_v2(structure)
    for q in normalized.get("questions") or []:
        qn = int(q.get("number"))
        qtype = str(q.get("question_type") or "").lower()
        rule = "sum"
        if q.get("or_group_id"):
            rule = "best_of"
        elif qtype in {"mcq", "fill_blank"}:
            rule = "binary"
        rules[str(qn)] = {
            "question_number": qn,
            "rule": rule,
            "subparts": len(q.get("subquestions") or []),
        }
    return rules


def question_structure_v2_from_exam(exam: Dict[str, Any]) -> Dict[str, Any]:
    structure = (exam or {}).get("question_structure_v2")
    if isinstance(structure, dict) and (structure.get("questions") or []):
        return normalize_question_structure_v2(structure)

    questions = (exam or {}).get("questions") or []
    derived = {
        "questions": [
            {
                "number": parse_question_number(q.get("question_number")),
                "section": None,
                "instruction": None,
                "question_text": str(q.get("question_text") or q.get("rubric") or "").strip(),
                "question_type": str(q.get("question_type") or "descriptive").strip().lower(),
                "marks": float(q.get("max_marks") or 0.0),
                "options": list(q.get("options") or []) or None,
                "subquestions": [
                    {
                        "label": str(sq.get("sub_id") or "").strip(),
                        "text": str(sq.get("rubric") or sq.get("text") or "").strip(),
                        "marks": float(sq.get("max_marks") or sq.get("marks") or 0.0),
                    }
                    for sq in (q.get("sub_questions") or [])
                    if str(sq.get("sub_id") or "").strip()
                ],
                "or_group_id": (str(q.get("or_group_id") or "").strip() or None),
                "image_evidence": list(q.get("image_evidence") or []),
                "ai_confidence": float(q.get("ai_confidence") or 0.0),
            }
            for q in questions
            if parse_question_number(q.get("question_number")) is not None
        ],
        "total_questions": int((exam or {}).get("questions_count") or len(questions)),
        "total_marks": float((exam or {}).get("total_marks") or 0.0),
        "numbering_contiguous": True,
    }
    return normalize_question_structure_v2(derived)


def compute_structure_confidence_v2(structure: Dict[str, Any]) -> float:
    normalized = normalize_question_structure_v2(structure)
    confidences = [float(q.get("ai_confidence") or 0.0) for q in (normalized.get("questions") or [])]
    if not confidences:
        return 0.0
    return round(sum(confidences) / float(len(confidences)), 4)


def build_blueprint_freeze_payload(exam: Dict[str, Any]) -> Dict[str, Any]:
    structure = question_structure_v2_from_exam(exam)
    effective_total_marks = compute_effective_total_marks_v2(structure)
    payload = {
        "question_structure_v2": structure,
        "structure_hash": compute_structure_hash(structure),
        "question_count": len(structure.get("questions") or []),
        "effective_total_marks": effective_total_marks,
        "or_groups_map": compute_or_groups_map_v2(structure),
        "attempt_rules": compute_attempt_rules_v2(structure),
        "structure_confidence": compute_structure_confidence_v2(structure),
    }
    return payload
