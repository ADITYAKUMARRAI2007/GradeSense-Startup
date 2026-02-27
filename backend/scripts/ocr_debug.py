import os
import sys
import json
from typing import List, Dict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services.file_processing import pdf_to_images
from app.services.segmentation import build_page_segments
from app.services.question_mapper import map_segments_to_questions
from app.utils.ocr_provider import get_ocr_provider


def detect_page_labels(images: List[str], expected_questions: List[int], min_confidence: float = 0.55) -> Dict[int, Dict]:
    ocr = get_ocr_provider()
    stats = {}
    segments_by_page = []
    words_by_page = []
    widths = []
    for idx, img in enumerate(images):
        page_num = idx + 1
        try:
            result = ocr.detect(img, min_conf=min_confidence)
            words = result.get("words", [])
            provider = result.get("provider", "unknown")
            fallback_used = bool(result.get("fallback_used", False))
            lines = result.get("lines", [])
            tables = result.get("tables", [])
        except Exception as e:
            stats[page_num] = {"error": str(e), "labels": [], "provider": "error"}
            continue

        width = float(result.get("width", 1000))
        page_segments = build_page_segments(words=words, tables=tables, page=page_num)
        segments_by_page.append(page_segments)
        words_by_page.append(words)
        widths.append(width)

        stats[page_num] = {
            "provider": provider,
            "fallback_used": fallback_used,
            "words": len(words),
            "lines": len(lines),
            "segments": len(page_segments),
            "tables": len(tables),
            "metrics": result.get("metrics", {}),
        }

    mapped = map_segments_to_questions(
        segments_by_page=segments_by_page,
        words_by_page=words_by_page,
        expected_questions=expected_questions,
        page_widths=widths,
    )
    detected = sorted([int(k) for k in mapped.keys() if isinstance(k, int)])
    missing = sorted(set(expected_questions) - set(detected))
    stats["_coverage"] = {
        "expected": expected_questions,
        "detected": detected,
        "missing": missing,
        "coverage_pct": round((len(detected) / max(1, len(expected_questions))) * 100, 2),
    }
    return stats


def main(pdf_path: str, expected_count: int = 34):
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    images = pdf_to_images(pdf_bytes)
    expected_questions = list(range(1, expected_count + 1))
    stats = detect_page_labels(images, expected_questions=expected_questions)
    per_page = {k: v for k, v in stats.items() if isinstance(k, int)}
    print(json.dumps({
        "pages": len(images),
        "coverage": stats.get("_coverage", {}),
        "providers": {k: v.get("provider") for k, v in per_page.items()},
        "fallback_used": {k: v.get("fallback_used") for k, v in per_page.items()},
        "words": {k: v.get("words", 0) for k, v in per_page.items()},
        "lines": {k: v.get("lines", 0) for k, v in per_page.items()},
        "segments": {k: v.get("segments", 0) for k, v in per_page.items()},
        "tables": {k: v.get("tables", 0) for k, v in per_page.items()},
        "metrics": {k: v.get("metrics", {}) for k, v in per_page.items()},
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/ocr_debug.py <pdf_path> [expected_question_count]")
        sys.exit(1)
    expected = int(sys.argv[2]) if len(sys.argv) > 2 else 34
    main(sys.argv[1], expected_count=expected)
