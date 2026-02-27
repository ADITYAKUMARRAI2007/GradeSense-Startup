#!/usr/bin/env python3
"""Migration for AI-structured pipeline v1 fields/indexes/snapshots."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from pymongo import ASCENDING, DESCENDING, MongoClient


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _legacy_questions_to_structure(questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for q in questions or []:
        qn = q.get("question_number")
        try:
            qn_int = int(qn)
        except Exception:
            continue
        subquestions = []
        for sq in q.get("sub_questions", []) or []:
            label = str(sq.get("sub_id") or "").strip()
            if not label:
                continue
            subquestions.append(
                {
                    "label": label,
                    "text": str(sq.get("rubric") or "").strip(),
                    "marks": _to_float(sq.get("max_marks"), 0.0),
                }
            )
        rows.append(
            {
                "number": qn_int,
                "section": None,
                "instruction": None,
                "question_text": str(q.get("question_text") or q.get("rubric") or "").strip(),
                "question_type": str(q.get("question_type") or "descriptive").strip().lower(),
                "marks": _to_float(q.get("max_marks"), 0.0),
                "options": None,
                "subquestions": subquestions,
                "or_group_id": q.get("or_group_id"),
                "image_evidence": [],
                "ai_confidence": 0.5,
            }
        )
    rows.sort(key=lambda item: int(item["number"]))
    return {
        "questions": rows,
        "total_questions": len(rows),
        "total_marks": round(sum(_to_float(row.get("marks"), 0.0) for row in rows), 4),
        "numbering_contiguous": True,
    }


def main() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise SystemExit("MONGO_URL and DB_NAME are required")

    client = MongoClient(mongo_url)
    db = client[db_name]

    exams = db.exams
    submissions = db.submissions
    versions = db.exam_blueprint_versions

    print("[migrate_ai_structured_v1] ensuring indexes...")
    versions.create_index([("exam_id", ASCENDING), ("blueprint_version", DESCENDING)], name="exam_id_blueprint_version_desc")
    submissions.create_index([("exam_id", ASCENDING), ("blueprint_version_used", ASCENDING)], name="exam_id_blueprint_version_used")
    exams.create_index([("exam_id", ASCENDING), ("processing_state", ASCENDING), ("blueprint_locked", ASCENDING)], name="exam_processing_blueprint")

    migrated = 0
    locked = 0
    failed = 0

    for exam in exams.find({}, {"_id": 0}):
        exam_id = exam.get("exam_id")
        if not exam_id:
            continue

        updates: Dict[str, Any] = {
            "processing_state": exam.get("processing_state", "idle"),
            "processing_lock_at": exam.get("processing_lock_at"),
            "processing_lock_owner": exam.get("processing_lock_owner"),
            "blueprint_locked": bool(exam.get("blueprint_locked", False)),
            "structure_confidence": _to_float(exam.get("structure_confidence"), 0.0),
            "question_structure_source": exam.get("question_structure_source") or "legacy_backfill",
            "question_structure_retry_count": int(exam.get("question_structure_retry_count") or 0),
            "model_name": exam.get("model_name") or "legacy",
            "prompt_version": exam.get("prompt_version") or "legacy",
            "pipeline_version": exam.get("pipeline_version") or "legacy",
            "extraction_hash": exam.get("extraction_hash"),
        }

        structure = exam.get("question_structure_v2")
        if not structure:
            structure = _legacy_questions_to_structure(exam.get("questions") or [])

        questions = structure.get("questions") or []
        question_count = len(questions)
        effective_total = _to_float(structure.get("total_marks"), _to_float(exam.get("total_marks"), 0.0))

        updates["question_structure_v2"] = structure
        updates["question_structure_validation"] = exam.get("question_structure_validation") or {
            "is_valid": bool(question_count > 0),
            "question_count": question_count,
            "effective_total_marks": effective_total,
        }
        updates["question_structure_confidence"] = _to_float(
            exam.get("question_structure_confidence"),
            0.5 if question_count > 0 else 0.0,
        )
        updates["effective_total_marks"] = effective_total
        updates["or_groups_map"] = exam.get("or_groups_map") or {}
        updates["attempt_rules"] = exam.get("attempt_rules") or {}
        updates["active_structure_hash"] = exam.get("active_structure_hash") or f"legacy:{exam_id}"

        if question_count > 0:
            updates["blueprint_version"] = int(exam.get("blueprint_version") or 1)
            updates["blueprint_locked"] = True
            updates["blueprint_status"] = "ready_locked"
            updates["locked_at"] = exam.get("locked_at") or exam.get("blueprint_locked_at") or datetime.now(timezone.utc).isoformat()
            updates["blueprint_locked_at"] = updates["locked_at"]
            locked += 1

            existing_snapshot = versions.find_one({"exam_id": exam_id, "blueprint_version": updates["blueprint_version"]})
            if not existing_snapshot:
                versions.insert_one(
                    {
                        "exam_id": exam_id,
                        "blueprint_version": updates["blueprint_version"],
                        "structure_hash": updates["active_structure_hash"],
                        "question_count": question_count,
                        "effective_total_marks": effective_total,
                        "or_groups_map": updates["or_groups_map"],
                        "attempt_rules": updates["attempt_rules"],
                        "locked_at": updates["locked_at"],
                        "question_structure_v2": structure,
                        "validation_report": updates["question_structure_validation"],
                        "structure_confidence": updates["question_structure_confidence"],
                        "model_name": updates["model_name"],
                        "prompt_version": updates["prompt_version"],
                        "pipeline_version": updates["pipeline_version"],
                        "extraction_hash": updates["extraction_hash"],
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
        else:
            updates["blueprint_locked"] = False
            updates["blueprint_status"] = "failed"
            failed += 1

        exams.update_one({"exam_id": exam_id}, {"$set": updates})
        migrated += 1

    print(
        "[migrate_ai_structured_v1] done",
        {
            "migrated_exams": migrated,
            "locked_blueprints": locked,
            "failed_blueprints": failed,
        },
    )


if __name__ == "__main__":
    main()

