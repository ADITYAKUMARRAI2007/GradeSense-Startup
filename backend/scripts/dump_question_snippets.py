import asyncio
import json
import os
import pickle
import sys
from typing import Dict, Any, List

from bson import ObjectId

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.database import db, fs  # noqa: E402
from app.services.segmentation import build_page_segments  # noqa: E402
from app.services.question_mapper import map_segments_to_questions  # noqa: E402
from app.utils.ocr_provider import get_ocr_provider  # noqa: E402


async def build_question_snippets(submission_id: str) -> Dict[str, Any]:
    submission = await db.submissions.find_one(
        {"submission_id": submission_id},
        {"_id": 0, "submission_id": 1, "exam_id": 1, "file_images": 1, "images_gridfs_id": 1},
    )
    if not submission:
        raise RuntimeError(f"Submission not found: {submission_id}")

    images: List[str] = submission.get("file_images") or []
    if not images and submission.get("images_gridfs_id"):
        oid = ObjectId(submission["images_gridfs_id"])
        if fs.exists(oid):
            images = pickle.loads(fs.get(oid).read())
    if not images:
        raise RuntimeError("No images found for submission")

    exam = await db.exams.find_one({"exam_id": submission.get("exam_id")}, {"_id": 0, "questions": 1})
    expected_questions = []
    for q in (exam or {}).get("questions", []):
        try:
            expected_questions.append(int(q.get("question_number")))
        except Exception:
            continue
    expected_questions = sorted(set(expected_questions))

    ocr = get_ocr_provider()
    force_fallback_on_sparse = os.getenv("OCR_FORCE_FALLBACK_ON_SPARSE", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    segments_by_page = []
    words_by_page = []
    widths = []

    for page_idx, img in enumerate(images):
        res = ocr.detect(img)
        words = res.get("words", []) or []
        lines = res.get("lines", []) or []
        if not words or (len(words) < 8 and len(lines) < 3):
            retry = ocr.detect(
                img,
                min_conf=0.35,
                min_words=8,
                min_lines=2,
                force_fallback=force_fallback_on_sparse,
            )
            if len(retry.get("words", []) or []) > len(words):
                res = retry
                words = res.get("words", []) or []
        tables = res.get("tables", []) or []
        segments = build_page_segments(words=words, tables=tables, page=page_idx + 1)
        segments_by_page.append(segments)
        words_by_page.append(words)
        widths.append(float(res.get("width", 1000)))

    mapped = map_segments_to_questions(
        segments_by_page=segments_by_page,
        words_by_page=words_by_page,
        expected_questions=expected_questions,
        page_widths=widths,
    )

    out = {
        "submission_id": submission_id,
        "exam_id": submission.get("exam_id"),
        "expected_questions": expected_questions,
        "detected_questions": sorted([k for k in mapped.keys() if isinstance(k, int)]),
        "per_page_metrics": (mapped.get("_meta", {}) or {}).get("per_page", []),
        "mapping_coverage": float((mapped.get("_meta", {}) or {}).get("mapping_coverage", 0.0) or 0.0),
        "packets_generated": int((mapped.get("_meta", {}) or {}).get("packets_generated", 0) or 0),
        "subpacket_count": int((mapped.get("_meta", {}) or {}).get("subpacket_count", 0) or 0),
        "low_confidence_questions": (mapped.get("_meta", {}) or {}).get("low_confidence_questions", []),
        "consistency_flags": (mapped.get("_meta", {}) or {}).get("consistency_flags", []),
        "snippets": {},
    }
    for qn in out["detected_questions"]:
        qd = mapped.get(qn, {})
        out["snippets"][str(qn)] = {
            "question_number": int(qn),
            "segment_ids": qd.get("segment_ids", []),
            "combined_text": (qd.get("combined_text", "") or "")[:2400],
            "page_refs": qd.get("page_refs", []),
            "subquestion_count": int(qd.get("subquestion_count", 0) or 0),
            "subanswers": qd.get("subanswers", []),
            "table_segments": qd.get("table_segments", []),
            "working_note_segments": qd.get("working_note_segments", []),
            "mapping_confidence": float(qd.get("mapping_confidence", 0.0) or 0.0),
            "mapping_trace": qd.get("mapping_trace", []),
            "start_anchor": qd.get("start_anchor"),
            "end_anchor": qd.get("end_anchor"),
        }
    return out


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/dump_question_snippets.py <submission_id>")
        sys.exit(1)
    submission_id = sys.argv[1]
    result = await build_question_snippets(submission_id)
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
