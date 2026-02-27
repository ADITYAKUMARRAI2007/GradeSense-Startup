"""Orchestrator for AI-structured extraction, alignment and deterministic grading."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument

from app.config import logger
from app.database import db, fs
from app.models.submission import QuestionScore
from app.services.gridfs_helpers import get_exam_question_paper_images

from .alignment_service import ALIGNMENT_COVERAGE_GATE, align_answers
from .cache import get_structure_cache, set_structure_cache
from .extraction_service import extract_question_structure
from .grading_interface import GRADING_CONTRACT_VERSION, grade_answers_with_contracts
from .prompts import PROMPT_VERSION
from .validation import (
    compute_attempt_rules,
    compute_effective_total,
    compute_or_groups_map,
    normalize_structure_payload,
    structure_hash,
    validate_structure,
)


PIPELINE_VERSION = "ai_structured_v1"
DEFAULT_MODEL_NAME = "gemini-2.5-flash"
LOCK_TTL_MINUTES = int(os.getenv("AI_STRUCTURED_LOCK_TTL_MINUTES", "20"))
OVERALL_REVIEW_THRESHOLD = float(os.getenv("AI_STRUCTURED_REVIEW_THRESHOLD", "0.6"))
ALIGNMENT_COVERAGE_THRESHOLD = float(os.getenv("AI_STRUCTURED_ALIGNMENT_GATE", str(ALIGNMENT_COVERAGE_GATE)))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _question_structure_to_legacy_questions(structure: Dict[str, Any]) -> List[Dict[str, Any]]:
    legacy = []
    for q in (structure.get("questions") or []):
        legacy.append(
            {
                "question_number": int(q.get("number")),
                "question_uuid": str(q.get("question_uuid") or f"qv2_{int(q.get('number'))}"),
                "max_marks": _to_float(q.get("marks"), 0.0),
                "question_text": str(q.get("question_text") or "").strip(),
                "rubric": str(q.get("question_text") or "").strip(),
                "question_type": str(q.get("question_type") or "descriptive"),
                "or_group_id": q.get("or_group_id"),
                "sub_questions": [
                    {
                        "sub_id": str(sq.get("label") or "").strip(),
                        "max_marks": _to_float(sq.get("marks"), 0.0),
                        "rubric": str(sq.get("text") or "").strip(),
                    }
                    for sq in (q.get("subquestions") or [])
                ],
            }
        )
    return legacy


def _structure_confidence(structure: Dict[str, Any]) -> float:
    confidences = [_to_float(q.get("ai_confidence"), 0.0) for q in (structure.get("questions") or [])]
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 4)


def _apply_audit_tree_marks(structure: Dict[str, Any], question_audit_tree: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    normalized = normalize_structure_payload(structure or {})
    audit_rows = [row for row in (question_audit_tree or []) if isinstance(row, dict)]
    if not audit_rows:
        return normalized

    by_num: Dict[int, Dict[str, Any]] = {
        int(q.get("number")): q
        for q in (normalized.get("questions") or [])
        if str(q.get("number", "")).isdigit()
    }
    for row in audit_rows:
        qn = int(row.get("number") or 0)
        if qn <= 0 or qn not in by_num:
            continue
        q = by_num[qn]
        q["marks"] = _to_float(row.get("total_marks"), _to_float(q.get("marks"), 0.0))
        q["mark_source"] = str(row.get("mark_source") or q.get("mark_source") or "inferred")
        q["distribution_mode"] = str(row.get("distribution_mode") or q.get("distribution_mode") or "direct")
        q["evidence_refs"] = list(row.get("evidence_refs") or q.get("evidence_refs") or [])

        audit_sub = {
            str(s.get("label") or "").strip().lower(): s
            for s in (row.get("subparts") or [])
            if str(s.get("label") or "").strip()
        }
        if audit_sub:
            new_sub = []
            for sq in (q.get("subquestions") or []):
                lbl = str(sq.get("label") or "").strip().lower()
                if not lbl:
                    new_sub.append(sq)
                    continue
                a = audit_sub.get(lbl)
                if not a:
                    new_sub.append(sq)
                    continue
                sq = dict(sq)
                sq["marks"] = _to_float(a.get("marks"), _to_float(sq.get("marks"), 0.0))
                sq["mark_source"] = str(a.get("source") or sq.get("mark_source") or "inferred")
                new_sub.append(sq)
            q["subquestions"] = new_sub
        by_num[qn] = q

    normalized["questions"] = [by_num[int(q.get("number"))] for q in (normalized.get("questions") or []) if str(q.get("number", "")).isdigit()]
    normalized["total_marks"] = compute_effective_total(normalized.get("questions") or [])
    normalized["effective_total_marks"] = normalized["total_marks"]
    return normalized


def _derive_total_marks(structure: Dict[str, Any]) -> float:
    grouped: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for q in (structure.get("questions") or []):
        grouped.setdefault(q.get("or_group_id"), []).append(q)

    def _q_marks(q: Dict[str, Any]) -> float:
        marks = _to_float(q.get("marks"), 0.0)
        if marks > 0:
            return marks
        return sum(_to_float(sq.get("marks"), 0.0) for sq in (q.get("subquestions") or []))

    total = 0.0
    for gid, qs in grouped.items():
        if gid:
            total += max((_q_marks(q) for q in qs), default=0.0)
        else:
            total += sum(_q_marks(q) for q in qs)
    return round(total, 4)


async def _get_submission_images(submission: Dict[str, Any]) -> List[str]:
    images = list(submission.get("file_images") or [])
    if images:
        return images

    gridfs_id = submission.get("images_gridfs_id")
    if not gridfs_id:
        return []

    try:
        oid = ObjectId(gridfs_id)
        if fs.exists(oid):
            import pickle

            return pickle.loads(fs.get(oid).read())
    except Exception as exc:
        logger.error("Could not load submission images from GridFS submission=%s error=%s", submission.get("submission_id"), exc)
    return []


async def _acquire_exam_lock(exam_id: str, *, state: str, owner: str) -> Dict[str, Any]:
    now = _utc_now()
    stale_before = (now - timedelta(minutes=LOCK_TTL_MINUTES)).isoformat()
    now_iso = now.isoformat()

    filter_query = {
        "exam_id": exam_id,
        "$or": [
            {"processing_state": {"$exists": False}},
            {"processing_state": "idle"},
            {"processing_lock_at": {"$lt": stale_before}},
            {"processing_lock_owner": owner},
        ],
    }

    update = {
        "$set": {
            "processing_state": state,
            "processing_lock_at": now_iso,
            "processing_lock_owner": owner,
        }
    }

    locked_exam = await db.exams.find_one_and_update(
        filter_query,
        update,
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )
    if not locked_exam:
        raise RuntimeError(f"processing_lock_busy:{exam_id}:{state}")

    return locked_exam


async def _release_exam_lock(exam_id: str, *, owner: str) -> None:
    await db.exams.update_one(
        {"exam_id": exam_id, "processing_lock_owner": owner},
        {
            "$set": {
                "processing_state": "idle",
                "processing_lock_at": _iso_now(),
            },
            "$unset": {"processing_lock_owner": ""},
        },
    )


async def _create_blueprint_snapshot(
    *,
    exam: Dict[str, Any],
    structure: Dict[str, Any],
    validation_report: Dict[str, Any],
    extraction_hash: str,
    model_name: str,
) -> Tuple[int, Dict[str, Any]]:
    previous_version = int(exam.get("blueprint_version", 0) or 0)
    next_version = previous_version + 1

    normalized = normalize_structure_payload(structure)
    question_count = len(normalized.get("questions") or [])
    effective_total_marks = _to_float(validation_report.get("effective_total_marks"), 0.0)
    or_groups_map = validation_report.get("or_groups_map") or compute_or_groups_map(normalized.get("questions") or [])
    attempt_rules = validation_report.get("attempt_rules") or compute_attempt_rules(normalized.get("questions") or [])
    structure_conf = _structure_confidence(normalized)
    shash = structure_hash(normalized)
    question_audit_tree = list(validation_report.get("question_audit_tree") or structure.get("question_audit_tree") or [])
    unresolved_flags = list(validation_report.get("unresolved_flags") or validation_report.get("errors") or [])

    snapshot_doc = {
        "exam_id": exam.get("exam_id"),
        "blueprint_version": next_version,
        "structure_hash": shash,
        "question_count": question_count,
        "effective_total_marks": effective_total_marks,
        "or_groups_map": or_groups_map,
        "attempt_rules": attempt_rules,
        "locked_at": _iso_now(),
        "question_structure_v2": normalized,
        "question_audit_tree": question_audit_tree,
        "validation_report": validation_report,
        "unresolved_flags": unresolved_flags,
        "structure_confidence": structure_conf,
        "model_name": model_name,
        "prompt_version": PROMPT_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "extraction_hash": extraction_hash,
        "created_at": _iso_now(),
    }

    await db.exam_blueprint_versions.insert_one(snapshot_doc)
    logger.info(
        "BLUEPRINT_VERSION_CREATED exam_id=%s version=%s structure_hash=%s",
        exam.get("exam_id"),
        next_version,
        shash,
    )

    return next_version, snapshot_doc


async def extract_and_persist(
    *,
    exam_id: str,
    force: bool = False,
    lock_owner: Optional[str] = None,
    model_name: str = DEFAULT_MODEL_NAME,
) -> Dict[str, Any]:
    owner = lock_owner or f"extract_{exam_id}"

    locked_exam: Dict[str, Any] = {}
    try:
        locked_exam = await _acquire_exam_lock(exam_id, state="extracting", owner=owner)

        question_paper_images = await get_exam_question_paper_images(exam_id)
        if not question_paper_images:
            logger.error("PIPELINE_BLOCKED_EXTRACTION exam_id=%s reason=missing_question_paper_images", exam_id)
            await db.exams.update_one(
                {"exam_id": exam_id},
                {
                    "$set": {
                        "blueprint_status": "failed",
                        "blueprint_locked": False,
                        "question_extraction_status": "failed",
                        "question_paper_processing": False,
                        "processing_state": "idle",
                    }
                },
            )
            return {
                "success": False,
                "message": "Question paper images not found",
                "source": "question_paper",
            }

        # Marks must be resolved from visual evidence (header/margin/section math), not exam metadata.
        expected_total_marks = None
        expected_question_count = int(locked_exam.get("questions_count") or 0) or None

        extraction_hash_seed = hashlib.sha256(
            (
                str(exam_id)
                + "|"
                + str(len(question_paper_images))
                + "|"
                + "|".join(question_paper_images[:3])
            ).encode("utf-8")
        ).hexdigest()

        cached = get_structure_cache(exam_id, int(locked_exam.get("blueprint_version", 0) or 0), extraction_hash_seed)
        if cached and not force:
            structure = cached.get("structure") or {}
            validation_report = cached.get("validation_report") or {}
            raw_ocr_text = cached.get("raw_ocr_text") or ""
            retry_count = int(cached.get("retry_count") or 0)
        else:
            logger.info("STRUCTURE_EXTRACTION_START exam_id=%s pages=%s", exam_id, len(question_paper_images))
            structure, validation_report, raw_ocr_text, retry_count = await extract_question_structure(
                question_paper_images=question_paper_images,
                expected_total_marks=expected_total_marks,
                expected_question_count=expected_question_count,
                max_retries=3,
                model_name=model_name,
            )
            set_structure_cache(
                exam_id,
                int(locked_exam.get("blueprint_version", 0) or 0),
                extraction_hash_seed,
                {
                    "structure": structure,
                    "validation_report": validation_report,
                    "raw_ocr_text": raw_ocr_text,
                    "retry_count": retry_count,
                },
            )

        unresolved_flags = list(validation_report.get("unresolved_flags") or validation_report.get("errors") or [])
        if unresolved_flags:
            logger.warning(
                "STRUCTURE_VALIDATION_UNRESOLVED exam_id=%s unresolved=%s warnings=%s",
                exam_id,
                unresolved_flags,
                validation_report.get("warnings") or [],
            )

        audit_tree = list(validation_report.get("question_audit_tree") or structure.get("question_audit_tree") or [])
        normalized = _apply_audit_tree_marks(normalize_structure_payload(structure), audit_tree)
        normalized["total_marks"] = _to_float(validation_report.get("effective_total_marks"), 0.0)
        normalized["total_questions"] = len(normalized.get("questions") or [])
        normalized["numbering_contiguous"] = bool(validation_report.get("numbering_contiguous", False))
        normalized["structure_confidence"] = _structure_confidence(normalized)

        extraction_hash = structure_hash(normalized)
        next_version, snapshot = await _create_blueprint_snapshot(
            exam=locked_exam,
            structure=normalized,
            validation_report=validation_report,
            extraction_hash=extraction_hash,
            model_name=model_name,
        )

        legacy_questions = _question_structure_to_legacy_questions(normalized)

        await db.questions.delete_many({"exam_id": exam_id})
        if legacy_questions:
            question_docs = []
            for q in legacy_questions:
                q_doc = {
                    **q,
                    "exam_id": exam_id,
                    "question_id": q.get("question_uuid") or f"q_{exam_id}_{q.get('question_number')}",
                }
                question_docs.append(q_doc)
            await db.questions.insert_many(question_docs)

        effective_total = _to_float(snapshot.get("effective_total_marks"), _to_float(locked_exam.get("total_marks"), 0.0))

        await db.exams.update_one(
            {"exam_id": exam_id},
            {
                "$set": {
                    "processing_state": "idle",
                    "question_extraction_status": "completed",
                    "question_paper_processing": False,
                    "question_extraction_count": len(legacy_questions),
                    "question_extraction_completed_at": _iso_now(),
                    "question_structure_v2": normalized,
                    "question_structure_validation": validation_report,
                    "question_structure_confidence": normalized.get("structure_confidence", 0.0),
                    "question_structure_source": "ai_structured",
                    "question_structure_retry_count": int(retry_count),
                    "question_audit_tree": snapshot.get("question_audit_tree") or audit_tree,
                    "unresolved_flags": snapshot.get("unresolved_flags") or unresolved_flags,
                    "structure_confidence": normalized.get("structure_confidence", 0.0),
                    "active_structure_hash": snapshot.get("structure_hash"),
                    "blueprint_locked": True,
                    "blueprint_status": "ready_locked",
                    "blueprint_version": int(next_version),
                    "locked_at": snapshot.get("locked_at"),
                    "blueprint_locked_at": snapshot.get("locked_at"),
                    "questions": legacy_questions,
                    "questions_count": len(legacy_questions),
                    "total_marks": effective_total if effective_total > 0 else _to_float(locked_exam.get("total_marks"), 0.0),
                    "effective_total_marks": effective_total,
                    "or_groups_map": snapshot.get("or_groups_map"),
                    "attempt_rules": snapshot.get("attempt_rules"),
                    "model_name": model_name,
                    "prompt_version": PROMPT_VERSION,
                    "pipeline_version": PIPELINE_VERSION,
                    "extraction_hash": extraction_hash,
                }
            },
        )

        logger.info("BLUEPRINT_LOCKED exam_id=%s version=%s", exam_id, next_version)
        logger.info(
            "BLUEPRINT_FROZEN exam_id=%s version=%s unresolved_flags=%s",
            exam_id,
            next_version,
            len(snapshot.get("unresolved_flags") or []),
        )
        logger.info("OR_RULES_FROZEN exam_id=%s version=%s", exam_id, next_version)
        logger.info(
            "STRUCTURE_EXTRACTION_DONE exam_id=%s questions=%s total_marks=%s",
            exam_id,
            len(legacy_questions),
            effective_total,
        )

        # Re-alignment required on version bump.
        realign_update = await db.submissions.update_many(
            {
                "exam_id": exam_id,
                "$or": [
                    {"blueprint_version_used": {"$ne": int(next_version)}},
                    {"blueprint_version_used": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "realign_required": True,
                }
            },
        )
        if int(realign_update.modified_count or 0) > 0:
            logger.info(
                "REALIGN_REQUIRED exam_id=%s version=%s affected_submissions=%s",
                exam_id,
                int(next_version),
                int(realign_update.modified_count or 0),
            )

        return {
            "success": True,
            "message": f"Extracted {len(legacy_questions)} questions from question paper",
            "count": len(legacy_questions),
            "source": "question_paper",
            "total_marks": effective_total,
            "blueprint_status": "ready_locked",
            "blueprint_version": int(next_version),
            "unresolved_flags": snapshot.get("unresolved_flags") or [],
            "blueprint_health": validation_report,
        }

    except Exception as exc:
        logger.error("PIPELINE_BLOCKED_EXTRACTION exam_id=%s error=%s", exam_id, exc, exc_info=True)
        await db.exams.update_one(
            {"exam_id": exam_id},
            {
                "$set": {
                    "question_extraction_status": "failed",
                    "question_paper_processing": False,
                    "blueprint_status": "failed",
                    "blueprint_locked": False,
                    "processing_state": "idle",
                }
            },
        )
        return {
            "success": False,
            "message": f"Extraction failed: {exc}",
            "source": "question_paper",
        }
    finally:
        if locked_exam:
            await _release_exam_lock(exam_id, owner=owner)


async def _load_exam_and_submission(submission_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    submission = await db.submissions.find_one({"submission_id": submission_id}, {"_id": 0})
    if not submission:
        raise RuntimeError("submission_not_found")

    exam = await db.exams.find_one({"exam_id": submission.get("exam_id")}, {"_id": 0})
    if not exam:
        raise RuntimeError("exam_not_found")

    return exam, submission


async def align_submission_for_grading(
    *,
    submission_id: str,
    lock_owner: Optional[str] = None,
    force: bool = False,
    model_name: str = DEFAULT_MODEL_NAME,
) -> Dict[str, Any]:
    exam, submission = await _load_exam_and_submission(submission_id)
    latest_version = int(exam.get("blueprint_version", 0) or 0)
    submission_version_raw = submission.get("blueprint_version_used")
    try:
        submission_version = int(submission_version_raw) if submission_version_raw is not None else None
    except Exception:
        submission_version = None

    if submission_version is not None and submission_version != latest_version:
        logger.warning(
            "BLUEPRINT_VERSION_MISMATCH submission=%s exam_id=%s submission_version=%s latest_version=%s",
            submission_id,
            exam.get("exam_id"),
            submission_version,
            latest_version,
        )
        await db.submissions.update_one(
            {"submission_id": submission_id},
            {"$set": {"realign_required": True}},
        )
        logger.info(
            "REALIGN_REQUIRED submission=%s exam_id=%s from_version=%s to_version=%s",
            submission_id,
            exam.get("exam_id"),
            submission_version,
            latest_version,
        )

    if not exam.get("blueprint_locked") and str(exam.get("blueprint_status", "")).lower() != "ready_locked":
        logger.error("PIPELINE_BLOCKED_ALIGNMENT submission=%s reason=blueprint_not_locked", submission_id)
        raise RuntimeError("blueprint_not_locked")

    owner = lock_owner or f"align_{exam.get('exam_id')}_{submission_id}"
    await _acquire_exam_lock(exam.get("exam_id"), state="aligning", owner=owner)
    try:
        structure = exam.get("question_structure_v2") or {
            "questions": [
                {
                    "number": q.get("question_number"),
                    "question_text": q.get("question_text") or q.get("rubric") or "",
                    "marks": q.get("max_marks", 0.0),
                    "question_type": q.get("question_type", "descriptive"),
                    "subquestions": [
                        {
                            "label": sq.get("sub_id"),
                            "text": sq.get("rubric") or "",
                            "marks": sq.get("max_marks", 0.0),
                        }
                        for sq in (q.get("sub_questions") or [])
                    ],
                    "or_group_id": q.get("or_group_id"),
                }
                for q in (exam.get("questions") or [])
            ],
            "total_marks": _to_float(exam.get("total_marks"), 0.0),
            "total_questions": len(exam.get("questions") or []),
            "numbering_contiguous": True,
        }

        audit_tree = list(
            exam.get("question_audit_tree")
            or ((exam.get("question_structure_validation") or {}).get("question_audit_tree") or [])
        )
        structure = _apply_audit_tree_marks(structure, audit_tree)

        blueprint_signature = str(exam.get("active_structure_hash") or structure_hash(structure))
        images = await _get_submission_images(submission)
        if not images:
            raise RuntimeError("missing_submission_images")

        logger.info("ALIGNMENT_START submission=%s exam_id=%s", submission_id, exam.get("exam_id"))
        alignment_result = await align_answers(
            submission_id=submission_id,
            question_structure=structure,
            answer_images=images,
            blueprint_signature=blueprint_signature,
            model_name=model_name,
            use_cache=not force,
        )

        coverage = _to_float(alignment_result.get("alignment_coverage"), 0.0)
        coverage_ratio = _to_float(alignment_result.get("coverage_ratio"), 0.0)
        alignment_conf = _to_float(alignment_result.get("alignment_confidence_score"), 0.0)
        unresolved_questions = [
            int(qn)
            for qn, ok in (alignment_result.get("question_coverage_map") or {}).items()
            if not ok and str(qn).isdigit()
        ]

        alignment_status = "pass" if coverage >= ALIGNMENT_COVERAGE_THRESHOLD else "needs_review"
        grading_state = "pending" if alignment_status == "pass" else "blocked"
        if unresolved_questions or (alignment_result.get("unmapped_answers") or []) or (alignment_result.get("duplicate_answers") or []):
            logger.warning(
                "ALIGNMENT_GAP_DETECTED submission=%s unresolved=%s unmapped=%s duplicates=%s",
                submission_id,
                unresolved_questions,
                len(alignment_result.get("unmapped_answers") or []),
                len(alignment_result.get("duplicate_answers") or []),
            )

        if alignment_status != "pass":
            logger.warning(
                "ALIGNMENT_CONFIDENCE_LOW submission=%s coverage=%.3f ratio=%.3f confidence=%.3f",
                submission_id,
                coverage,
                coverage_ratio,
                alignment_conf,
            )
            logger.warning("ALIGNMENT_GRADE_BLOCKED submission=%s", submission_id)
            logger.warning(
                "PIPELINE_BLOCKED_ALIGNMENT submission=%s reason=alignment_coverage_low coverage=%.3f threshold=%.3f",
                submission_id,
                coverage,
                ALIGNMENT_COVERAGE_THRESHOLD,
            )
        else:
            logger.info(
                "ALIGNMENT_APPROVED submission=%s coverage=%.3f confidence=%.3f",
                submission_id,
                coverage,
                alignment_conf,
            )

        await db.submissions.update_one(
            {"submission_id": submission_id},
            {
                "$set": {
                    "grading_state": grading_state,
                    "alignment_status": alignment_status,
                    "alignment_coverage": coverage,
                    "alignment_confidence": alignment_conf,
                    "question_coverage_map": alignment_result.get("question_coverage_map", {}),
                    "unmapped_answers": alignment_result.get("unmapped_answers", []),
                    "duplicate_answers": alignment_result.get("duplicate_answers", []),
                    "orphan_pages": alignment_result.get("orphan_pages", []),
                    "blueprint_version_used": int(exam.get("blueprint_version", 0) or 0),
                    "realign_required": False,
                    "pipeline_version": PIPELINE_VERSION,
                    "prompt_version": PROMPT_VERSION,
                    "model_name": model_name,
                    "aligned_answers": alignment_result.get("answers", []),
                    "updated_at": _iso_now(),
                }
            },
        )

        logger.info(
            "ALIGNMENT_DONE submission=%s coverage=%.3f confidence=%.3f",
            submission_id,
            coverage,
            alignment_conf,
        )

        return {
            "submission_id": submission_id,
            "exam_id": exam.get("exam_id"),
            "mapping_status": alignment_status,
            "mapped_question_ratio": round(coverage_ratio, 4),
            "mapping_coverage": round(coverage, 4),
            "alignment_confidence_score": round(alignment_conf, 4),
            "expected_questions": sorted(
                int(q.get("number"))
                for q in (structure.get("questions") or [])
                if str(q.get("number", "")).isdigit()
            ),
            "detected_questions": sorted(
                {
                    int(a.get("question_number"))
                    for a in (alignment_result.get("answers") or [])
                    if str(a.get("question_number", "")).isdigit()
                }
            ),
            "unresolved_questions": [
                int(qn)
                for qn in unresolved_questions
            ],
            "fail_reasons": (
                ["alignment_coverage_below_threshold"] if alignment_status != "pass" else []
            ),
            "packet_summary": {},
            "question_coverage_map": alignment_result.get("question_coverage_map", {}),
            "unmapped_answers": alignment_result.get("unmapped_answers", []),
            "duplicate_answers": alignment_result.get("duplicate_answers", []),
            "orphan_pages": alignment_result.get("orphan_pages", []),
            "answers": alignment_result.get("answers", []),
        }
    finally:
        await _release_exam_lock(exam.get("exam_id"), owner=owner)


async def preflight_submission_mapping(
    *,
    submission_id: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    result = await align_submission_for_grading(submission_id=submission_id, force=True)
    return result


async def grade_images_with_locked_blueprint(
    *,
    exam: Dict[str, Any],
    images: List[str],
    model_answer_text: str,
    model_answer_map: Optional[Dict[str, Any]] = None,
    model_answer_images: Optional[List[str]] = None,
    question_paper_images: Optional[List[str]] = None,
    grading_mode: str,
    exam_id: Optional[str],
    model_name: str = DEFAULT_MODEL_NAME,
) -> Tuple[List[QuestionScore], Dict[str, Any]]:
    if not exam:
        raise RuntimeError("exam_required")

    if not exam.get("blueprint_locked") and str(exam.get("blueprint_status", "")).lower() != "ready_locked":
        logger.error("PIPELINE_BLOCKED_ALIGNMENT exam_id=%s reason=blueprint_not_locked", exam_id or exam.get("exam_id"))
        raise RuntimeError("blueprint_not_locked")

    logger.info(
        "BLUEPRINT_VERSION_USED exam_id=%s version=%s",
        exam_id or exam.get("exam_id"),
        int(exam.get("blueprint_version", 0) or 0),
    )

    structure = exam.get("question_structure_v2")
    if not structure:
        # Compatibility fallback for legacy exams.
        structure = {
            "questions": [
                {
                    "number": q.get("question_number"),
                    "question_text": q.get("question_text") or q.get("rubric") or "",
                    "question_type": q.get("question_type", "descriptive"),
                    "marks": q.get("max_marks", 0.0),
                    "subquestions": [
                        {
                            "label": sq.get("sub_id"),
                            "text": sq.get("rubric") or "",
                            "marks": sq.get("max_marks", 0.0),
                        }
                        for sq in (q.get("sub_questions") or [])
                    ],
                    "or_group_id": q.get("or_group_id"),
                }
                for q in (exam.get("questions") or [])
            ],
            "total_questions": len(exam.get("questions") or []),
            "total_marks": _to_float(exam.get("effective_total_marks"), _to_float(exam.get("total_marks"), 0.0)),
            "numbering_contiguous": True,
        }

    audit_tree = list(
        exam.get("question_audit_tree")
        or ((exam.get("question_structure_validation") or {}).get("question_audit_tree") or [])
    )
    structure = _apply_audit_tree_marks(structure, audit_tree)
    derived_total = _derive_total_marks(structure)
    declared_total = _to_float(structure.get("total_marks"), 0.0)
    validation_meta = exam.get("question_structure_validation") or {}
    header_total_marks = _to_float(validation_meta.get("header_total_marks"), 0.0)
    header_total_reliable = bool(validation_meta.get("header_total_reliable"))

    if header_total_reliable and header_total_marks > 0:
        if abs(declared_total - header_total_marks) > 0.5:
            logger.warning(
                "TOTAL_MARKS_HEADER_OVERRIDE exam_id=%s declared=%.2f header=%.2f",
                exam_id or exam.get("exam_id"),
                declared_total,
                header_total_marks,
            )
        structure["total_marks"] = header_total_marks
        structure["effective_total_marks"] = header_total_marks
        if exam_id:
            try:
                await db.exams.update_one(
                    {"exam_id": exam_id},
                    {"$set": {"total_marks": header_total_marks, "effective_total_marks": header_total_marks}},
                )
            except Exception as exc:
                logger.warning("TOTAL_MARKS_UPDATE_FAILED exam_id=%s error=%s", exam_id, exc)
    elif derived_total > 0 and (declared_total <= 0 or abs(derived_total - declared_total) > 0.5):
        logger.warning(
            "TOTAL_MARKS_MISMATCH exam_id=%s declared=%.2f derived=%.2f",
            exam_id or exam.get("exam_id"),
            declared_total,
            derived_total,
        )
        structure["total_marks"] = derived_total
        structure["effective_total_marks"] = derived_total
        if exam_id:
            try:
                await db.exams.update_one(
                    {"exam_id": exam_id},
                    {"$set": {"total_marks": derived_total, "effective_total_marks": derived_total}},
                )
            except Exception as exc:
                logger.warning("TOTAL_MARKS_UPDATE_FAILED exam_id=%s error=%s", exam_id, exc)

    validation = validate_structure(structure)
    if not validation.get("is_valid"):
        logger.warning(
            "BLUEPRINT_VALIDATION_WARNING exam_id=%s errors=%s",
            exam_id or exam.get("exam_id"),
            validation.get("errors") or [],
        )

    alignment_result = await align_answers(
        submission_id=f"adhoc_{exam_id or exam.get('exam_id')}",
        question_structure=structure,
        answer_images=images,
        blueprint_signature=str(exam.get("active_structure_hash") or structure_hash(structure)),
        model_name=model_name,
        use_cache=False,
    )

    mapping_coverage = _to_float(alignment_result.get("alignment_coverage"), 0.0)
    mapped_ratio = _to_float(alignment_result.get("coverage_ratio"), 0.0)
    unresolved_questions = [
        int(qn)
        for qn, ok in (alignment_result.get("question_coverage_map") or {}).items()
        if not ok and str(qn).isdigit()
    ]
    if unresolved_questions or (alignment_result.get("unmapped_answers") or []) or (alignment_result.get("duplicate_answers") or []):
        logger.warning(
            "ALIGNMENT_GAP_DETECTED exam_id=%s unresolved=%s unmapped=%s duplicates=%s",
            exam_id or exam.get("exam_id"),
            unresolved_questions,
            len(alignment_result.get("unmapped_answers") or []),
            len(alignment_result.get("duplicate_answers") or []),
        )
    if mapping_coverage < ALIGNMENT_COVERAGE_THRESHOLD:
        logger.warning(
            "PIPELINE_BLOCKED_ALIGNMENT exam_id=%s coverage=%.3f threshold=%.3f",
            exam_id or exam.get("exam_id"),
            mapping_coverage,
            ALIGNMENT_COVERAGE_THRESHOLD,
        )
        raise RuntimeError("alignment_coverage_low")

    grading_result = await grade_answers_with_contracts(
        question_structure=structure,
        alignment_result=alignment_result,
        model_answer_text=model_answer_text,
        model_answer_map=model_answer_map or {},
        answer_images=images,
        model_answer_images=model_answer_images or [],
        question_paper_images=question_paper_images or [],
        grading_mode=grading_mode,
        exam_id=exam_id or exam.get("exam_id"),
        model_name=model_name,
    )

    structure_conf = _to_float(exam.get("structure_confidence"), _structure_confidence(structure))
    alignment_conf = _to_float(alignment_result.get("alignment_confidence_score"), 0.0)
    grading_conf = _to_float(grading_result.get("grading_confidence"), 0.0)
    overall_conf = round(min(structure_conf, alignment_conf, grading_conf), 4)

    packet_meta = {
        "pipeline": "ai_structured",
        "mapping_status": "pass",
        "mapped_question_ratio": round(mapped_ratio, 4),
        "mapping_coverage": round(mapping_coverage, 4),
        "unresolved_questions": [
            int(qn)
            for qn in unresolved_questions
        ],
        "mapping_fail_reasons": [],
        "packets_generated": int(alignment_result.get("mapped_questions", 0) or 0),
        "subpacket_count": 0,
        "low_confidence_questions": [],
        "consistency_flags": [],
        "grading_reference_mode": "rubric_only",
        "structure_confidence": structure_conf,
        "alignment_confidence": alignment_conf,
        "grading_confidence": grading_conf,
        "overall_confidence": overall_conf,
        "question_coverage_map": alignment_result.get("question_coverage_map", {}),
        "unmapped_answers": alignment_result.get("unmapped_answers", []),
        "duplicate_answers": alignment_result.get("duplicate_answers", []),
        "orphan_pages": alignment_result.get("orphan_pages", []),
        "objective_key_flags": grading_result.get("objective_key_flags", {}),
        "grading_report": grading_result.get("grading_report", {}),
        "blueprint_version_used": int(exam.get("blueprint_version", 0) or 0),
        "grading_contract_version": grading_result.get("grading_contract_version", GRADING_CONTRACT_VERSION),
        "prompt_version": PROMPT_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "model_name": model_name,
    }

    return grading_result.get("question_scores", []), packet_meta


__all__ = [
    "ALIGNMENT_COVERAGE_THRESHOLD",
    "LOCK_TTL_MINUTES",
    "OVERALL_REVIEW_THRESHOLD",
    "PIPELINE_VERSION",
    "align_submission_for_grading",
    "extract_and_persist",
    "grade_images_with_locked_blueprint",
    "preflight_submission_mapping",
]
