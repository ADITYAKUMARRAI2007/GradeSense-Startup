#!/usr/bin/env python3
import os
import sys
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.services.file_processing import pdf_to_images
from app.layers.visual_entities.extractor import (  # type: ignore
    _collect_lines,
    _extract_section_math,
)


def main(pdf_path: str) -> None:
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    images = pdf_to_images(pdf_bytes)
    lines = _collect_lines(images, force_fallback=True)
    section_math = _extract_section_math(lines)
    print(json.dumps({
        "pages": len(images),
        "section_math_detected": section_math,
        "count": len(section_math),
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 backend/scripts/scan_section_math.py <pdf_path>")
        sys.exit(1)
    main(sys.argv[1])
