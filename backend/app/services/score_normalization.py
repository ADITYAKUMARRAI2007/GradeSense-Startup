"""Normalize submission score metadata (max marks, totals, percentage)."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_question_key(value: Any) -> str:
    """Normalize question keys used in exam definitions and AI outputs.

    Handles 'Q1', '1.', 'Question 1', etc., and returns the numeric part as string.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = re.sub(r'^(?:q(?:uestion)?)[\s:\.\-]*', '', text, flags=re.IGNORECASE)
    m = re.search(r"(\d+)", text)
    if m:
        return m.group(1)
    return re.sub(r"[^a-z0-9]", "", text.strip().lower())


def _normalize_sub_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _question_sort_key(q_key: str) -> Tuple[int, str]:
    m = re.search(r"(\d+)", str(q_key))
    if m:
        return (int(m.group(1)), str(q_key))
    return (10**9, str(q_key))


def _question_quality_score(question_score: Dict[str, Any]) -> float:
    score = 0.0
    status = str(question_score.get("status") or "").lower()
    if status and status != "not_found":
        score += 4
    if (_safe_float(question_score.get("max_marks"), 0.0) or 0.0) > 0:
        score += 3
    if (_safe_float(question_score.get("obtained_marks"), 0.0) or 0.0) > 0:
        score += 2
    score += min(len(question_score.get("sub_scores") or []), 5) * 0.2
    if len(str(question_score.get("ai_feedback") or "").strip()) > 20:
        score += 1
    return score


def _sub_quality_score(sub_score: Dict[str, Any]) -> float:
    score = 0.0
    if (_safe_float(sub_score.get("max_marks"), 0.0) or 0.0) > 0:
        score += 3
    if (_safe_float(sub_score.get("obtained_marks"), 0.0) or 0.0) > 0:
        score += 2
    status = str(sub_score.get("status") or "").lower()
    if status and status != "not_found":
        score += 1
    return score


def _merge_sub_scores(sub_scores_a: List[dict], sub_scores_b: List[dict]) -> List[dict]:
    merged: Dict[str, Dict[str, Any]] = {}
    ordered_keys: List[str] = []

    for sub_score in (sub_scores_a or []) + (sub_scores_b or []):
        key = _normalize_sub_key(sub_score.get("sub_id"))
        if not key:
            continue
        if key not in merged:
            merged[key] = deepcopy(sub_score)
            ordered_keys.append(key)
            continue

        existing = merged[key]
        prefer_incoming = _sub_quality_score(sub_score) > _sub_quality_score(existing)
        preferred = sub_score if prefer_incoming else existing
        fallback = existing if prefer_incoming else sub_score
        merged[key] = {
            **fallback,
            **preferred,
            "sub_id": preferred.get("sub_id") or fallback.get("sub_id"),
            "annotations": [
                *(existing.get("annotations") or []),
                *(sub_score.get("annotations") or []),
            ],
        }

    return [merged[k] for k in ordered_keys]


def _merge_question_scores(score_a: Dict[str, Any], score_b: Dict[str, Any]) -> Dict[str, Any]:
    prefer_b = _question_quality_score(score_b) > _question_quality_score(score_a)
    preferred = score_b if prefer_b else score_a
    fallback = score_a if prefer_b else score_b

    return {
        **fallback,
        **preferred,
        "question_number": preferred.get("question_number") or fallback.get("question_number"),
        "annotations": [
            *(score_a.get("annotations") or []),
            *(score_b.get("annotations") or []),
        ],
        "sub_scores": _merge_sub_scores(score_a.get("sub_scores") or [], score_b.get("sub_scores") or []),
    }


def _build_exam_question_maps(exam_questions: List[dict]) -> Tuple[Dict[str, dict], List[str]]:
    question_map: Dict[str, dict] = {}
    ordered_keys: List[str] = []

    for question in exam_questions or []:
        q_key = _normalize_question_key(question.get("question_number"))
        if not q_key:
            continue
        if q_key not in ordered_keys:
            ordered_keys.append(q_key)

        sub_map: Dict[str, float] = {}
        for sub in question.get("sub_questions") or []:
            sub_id = _normalize_sub_key(sub.get("sub_id"))
            sub_max = _safe_float(sub.get("max_marks"), 0.0) or 0.0
            if sub_id and sub_max > 0:
                sub_map[sub_id] = sub_max

        q_max = _safe_float(question.get("max_marks"), None)
        if (q_max is None or q_max <= 0) and sub_map:
            q_max = float(sum(sub_map.values()))

        existing = question_map.get(q_key)
        if existing:
            existing_max = _safe_float(existing.get("max_marks"), None)
            if (existing_max is None or existing_max <= 0) and (q_max is not None and q_max > 0):
                existing["max_marks"] = q_max
            if (existing_max is not None and q_max is not None) and q_max > existing_max:
                existing["max_marks"] = q_max
            existing["sub_marks"].update(sub_map)
            continue

        question_map[q_key] = {
            "question_number": question.get("question_number"),
            "max_marks": q_max if (q_max is not None and q_max > 0) else None,
            "sub_marks": sub_map,
        }

    ordered_keys.sort(key=_question_sort_key)
    return question_map, ordered_keys


def normalize_submission_scores(
    submission: Dict[str, Any],
    exam: Dict[str, Any],
    source: str = "unknown",
) -> Dict[str, Any]:
    """
    Normalize submission score metadata while preserving obtained marks and feedback.
    """
    submission_id = submission.get("submission_id", "unknown_submission")
    original_question_scores = submission.get("question_scores") or []
    question_scores = deepcopy(original_question_scores)
    exam_questions = exam.get("questions") or []
    exam_total_marks = _safe_float(exam.get("total_marks"), 100.0) or 100.0
    if exam_total_marks <= 0:
        exam_total_marks = 100.0

    question_map, ordered_question_keys = _build_exam_question_maps(exam_questions)

    # Build a deterministic, deduplicated question list.
    # If exam questions are present, enforce that exact sequence and backfill missing entries.
    deduped_scores: Dict[str, Dict[str, Any]] = {}
    unknown_scores: List[Dict[str, Any]] = []

    for question_score in question_scores:
        q_key = _normalize_question_key(question_score.get("question_number"))
        if not q_key:
            unknown_scores.append(question_score)
            continue
        existing = deduped_scores.get(q_key)
        if not existing:
            deduped_scores[q_key] = question_score
        else:
            deduped_scores[q_key] = _merge_question_scores(existing, question_score)

    if ordered_question_keys:
        normalized_scores: List[Dict[str, Any]] = []
        for q_key in ordered_question_keys:
            reference = question_map.get(q_key, {})
            existing = deduped_scores.get(q_key)
            if existing:
                existing["question_number"] = reference.get("question_number", existing.get("question_number"))
                normalized_scores.append(existing)
                continue

            ref_sub_map = reference.get("sub_marks", {})
            placeholder_sub_scores = [
                {
                    "sub_id": sub_id,
                    "obtained_marks": 0.0,
                    "max_marks": float(sub_max),
                    "status": "not_found",
                    "ai_feedback": "Answer not found on sheet.",
                    "is_reviewed": False,
                }
                for sub_id, sub_max in ref_sub_map.items()
            ]

            placeholder_max = _safe_float(reference.get("max_marks"), None)
            if (placeholder_max is None or placeholder_max <= 0) and placeholder_sub_scores:
                placeholder_max = float(sum(s["max_marks"] for s in placeholder_sub_scores))
            if placeholder_max is None or placeholder_max <= 0:
                placeholder_max = 1.0

            normalized_scores.append({
                "question_number": reference.get("question_number"),
                "obtained_marks": 0.0,
                "max_marks": float(placeholder_max),
                "status": "not_found",
                "ai_feedback": "Answer not found on sheet.",
                "is_reviewed": False,
                "sub_scores": placeholder_sub_scores,
                "annotations": [],
            })

        if unknown_scores:
            logger.warning(
                "score_normalization source=%s submission_id=%s dropped_unknown_question_scores=%s",
                source,
                submission_id,
                len(unknown_scores),
            )
        question_scores = normalized_scores
    else:
        # No exam question structure to anchor to; keep deduped + unknown in stable order.
        question_scores = list(deduped_scores.values()) + unknown_scores

    updated_questions = 0
    updated_sub_questions = 0
    total_score = 0.0

    for question_score in question_scores:
        q_num = question_score.get("question_number")
        q_key = _normalize_question_key(q_num)
        reference = question_map.get(q_key, {})
        reference_q_max = _safe_float(reference.get("max_marks"), None)
        reference_sub_map = reference.get("sub_marks", {})

        sub_scores = question_score.get("sub_scores") or []
        merged_sub_scores = _merge_sub_scores(sub_scores, [])
        sub_scores = merged_sub_scores
        question_score["sub_scores"] = sub_scores

        # Ensure every expected sub-part exists when exam reference provides it.
        if reference_sub_map:
            existing_sub_map = {
                _normalize_sub_key(ss.get("sub_id")): ss
                for ss in sub_scores
                if _normalize_sub_key(ss.get("sub_id"))
            }
            for sub_id, sub_max in reference_sub_map.items():
                if sub_id in existing_sub_map:
                    continue
                sub_scores.append({
                    "sub_id": sub_id,
                    "obtained_marks": 0.0,
                    "max_marks": float(sub_max),
                    "status": "not_found",
                    "ai_feedback": "Answer not found on sheet.",
                    "is_reviewed": False,
                    "annotations": [],
                })
                updated_sub_questions += 1

        normalized_sub_total = 0.0

        for sub_score in sub_scores:
            sub_id = _normalize_sub_key(sub_score.get("sub_id"))
            old_sub_max = _safe_float(sub_score.get("max_marks"), None)
            new_sub_max = old_sub_max

            if old_sub_max is None or old_sub_max <= 0:
                ref_sub_max = _safe_float(reference_sub_map.get(sub_id), None)
                new_sub_max = ref_sub_max if (ref_sub_max is not None and ref_sub_max > 0) else 1.0
                sub_score["max_marks"] = float(new_sub_max)
                updated_sub_questions += 1
                logger.info(
                    "score_normalization source=%s submission_id=%s question=%s sub_id=%s old_max=%s new_max=%s",
                    source,
                    submission_id,
                    q_num,
                    sub_id or "unknown_sub",
                    old_sub_max,
                    new_sub_max,
                )

            normalized_sub_total += _safe_float(sub_score.get("max_marks"), 0.0) or 0.0

        old_q_max = _safe_float(question_score.get("max_marks"), None)
        new_q_max = old_q_max

        if old_q_max is None or old_q_max <= 0:
            if reference_q_max is not None and reference_q_max > 0:
                new_q_max = reference_q_max
            elif sub_scores and normalized_sub_total > 0:
                new_q_max = normalized_sub_total
            else:
                new_q_max = 1.0

            question_score["max_marks"] = float(new_q_max)
            updated_questions += 1
            logger.info(
                "score_normalization source=%s submission_id=%s question=%s old_max=%s new_max=%s",
                source,
                submission_id,
                q_num,
                old_q_max,
                new_q_max,
            )

        total_score += _safe_float(question_score.get("obtained_marks"), 0.0) or 0.0

    percentage = round((total_score / exam_total_marks) * 100, 2) if exam_total_marks > 0 else 0.0

    previous_total = _safe_float(submission.get("total_score"), _safe_float(submission.get("obtained_marks"), 0.0) or 0.0) or 0.0
    previous_percentage = _safe_float(submission.get("percentage"), 0.0) or 0.0

    totals_changed = abs(previous_total - total_score) > 1e-9 or abs(previous_percentage - percentage) > 1e-9
    count_changed = len(original_question_scores) != len(question_scores)
    changed = (updated_questions > 0) or (updated_sub_questions > 0) or totals_changed or count_changed

    return {
        "question_scores": question_scores,
        "total_score": total_score,
        "percentage": percentage,
        "updated_questions": updated_questions,
        "updated_sub_questions": updated_sub_questions,
        "changed": changed,
    }
