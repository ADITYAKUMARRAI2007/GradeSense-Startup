"""Global span assembly across pages for college_v3."""

from __future__ import annotations

from typing import Any, Dict, List

from app.config import logger


def _flatten_blocks(pages_ocr: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    for page in pages_ocr or []:
        page_index = int(page.get("page_index") or 1)
        for block in page.get("blocks") or []:
            bbox = block.get("bbox") or [0, 0, 0, 0]
            lines.append(
                {
                    "page_index": page_index,
                    "text": block.get("text", ""),
                    "bbox": bbox,
                    "y_position": float(bbox[1]) if bbox else 0.0,
                }
            )
    lines.sort(key=lambda b: (int(b.get("page_index") or 1), float(b.get("y_position") or 0.0)))
    for idx, line in enumerate(lines):
        line["global_index"] = idx
    return lines


def build_global_spans(
    pages_ocr: List[Dict[str, Any]],
    anchors: List[Dict[str, Any]],
    level_filter: str = "question",
) -> List[Dict[str, Any]]:
    """Build spans from anchors across all pages (span_i = anchor_i -> anchor_(i+1))."""
    if not anchors:
        return []

    lines = _flatten_blocks(pages_ocr)
    # Map anchor to nearest line index by page + y.
    for anchor in anchors:
        page_index = int(anchor.get("page_index") or 1)
        y = float(anchor.get("y_position") or 0.0)
        candidates = [ln for ln in lines if int(ln.get("page_index") or 1) == page_index]
        if not candidates:
            anchor["line_index"] = None
            continue
        nearest = min(candidates, key=lambda ln: abs(float(ln.get("y_position") or 0.0) - y))
        anchor["line_index"] = int(nearest.get("global_index") or 0)

    anchors_filtered = [
        a
        for a in anchors
        if a.get("line_index") is not None and (not level_filter or a.get("anchor_level") == level_filter)
    ]
    anchors_sorted = sorted(
        anchors_filtered,
        key=lambda a: (int(a.get("page_index") or 1), float(a.get("y_position") or 0.0)),
    )

    spans: List[Dict[str, Any]] = []
    for idx, anchor in enumerate(anchors_sorted):
        start_idx = int(anchor.get("line_index") or 0)
        next_anchor = anchors_sorted[idx + 1] if idx + 1 < len(anchors_sorted) else None
        end_idx = (
            int(next_anchor.get("line_index") or len(lines) - 1) - 1
            if next_anchor is not None
            else len(lines) - 1
        )
        if end_idx < start_idx:
            end_idx = start_idx
        span_blocks = lines[start_idx:end_idx + 1]
        page_numbers = sorted({int(b.get("page_index") or 1) for b in span_blocks}) if span_blocks else []
        raw_text_by_page: List[Dict[str, Any]] = []
        for page_num in page_numbers:
            page_lines = [b.get("text", "") for b in span_blocks if int(b.get("page_index") or 1) == page_num]
            raw_text_by_page.append(
                {
                    "page_index": int(page_num),
                    "text": "\n".join(t for t in page_lines if t).strip(),
                }
            )
        combined_text = "\n".join(item.get("text", "") for item in raw_text_by_page).strip()
        preview_text = combined_text[:300]
        spans.append(
            {
                "question_number": int(anchor.get("question_number") or 0),
                "anchor_level": anchor.get("anchor_level"),
                "parent_question_number": anchor.get("parent_question_number"),
                "page_numbers": page_numbers,
                "raw_text_by_page": raw_text_by_page,
                "span_blocks": span_blocks,
                "preview_text": preview_text,
                "anchor_confidence": float(anchor.get("confidence", 0.0) or 0.0),
                "span_length": len(combined_text),
            }
        )

    logger.info("[COLLEGE-V3][SPAN] spans=%s", len(spans))
    return spans
