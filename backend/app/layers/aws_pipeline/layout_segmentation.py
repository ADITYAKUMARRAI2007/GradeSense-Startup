"""Deterministic layout segmentation for question spans and subparts.

This module builds a span graph BEFORE any AI so span boundaries are stable,
auditable, and re-runnable from raw Textract lines.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger

SECTION_PATTERNS = [
    re.compile(r"^\s*section\s*[-–]?\s*[a-z]\b", re.IGNORECASE),
    re.compile(r"^\s*part\s*[-–]?\s*[a-z]\b", re.IGNORECASE),
    re.compile(r"\breading skills\b", re.IGNORECASE),
    re.compile(r"\bgrammar\b", re.IGNORECASE),
    re.compile(r"\bliterature\b", re.IGNORECASE),
]

INSTRUCTION_PATTERNS = [
    re.compile(r"\bread the\b", re.IGNORECASE),
    re.compile(r"\banswer the following\b", re.IGNORECASE),
    re.compile(r"\banswer the questions\b", re.IGNORECASE),
    re.compile(r"\battempt any\b", re.IGNORECASE),
    re.compile(r"\bwrite an?\b", re.IGNORECASE),
    re.compile(r"\bfill in the blank\b", re.IGNORECASE),
    re.compile(r"\bcomplete the following\b", re.IGNORECASE),
    re.compile(r"\bchoose the correct\b", re.IGNORECASE),
    re.compile(r"\bselect the option\b", re.IGNORECASE),
    re.compile(r"\bgiven below\b", re.IGNORECASE),
    re.compile(r"\binstructions?\b", re.IGNORECASE),
]

GLOBAL_PREFACE_PATTERNS = [
    re.compile(r"^\s*general instructions", re.IGNORECASE),
    re.compile(r"^\s*time allowed", re.IGNORECASE),
    re.compile(r"^\s*maximum marks", re.IGNORECASE),
    re.compile(r"^\s*note\b", re.IGNORECASE),
    re.compile(r"^\s*please check", re.IGNORECASE),
    re.compile(r"^\s*english\b", re.IGNORECASE),
    re.compile(r"^\s*series\b", re.IGNORECASE),
    re.compile(r"^\s*q\.?p\.?\s*code", re.IGNORECASE),
]

QUESTION_VERB_PATTERNS = [
    re.compile(r"^\s*(write|explain|describe|state|answer|discuss|give|list|how|why|what|when|where|who)\b", re.IGNORECASE),
]

EXPLICIT_Q_PATTERNS = [
    re.compile(r"^\s*Q\.?\s*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"^\s*Question\s*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"^\s*(\d{1,3})\s*[\).]\s*(.*)$"),
    re.compile(r"^\s*(\d{1,3})\s*$"),
]

SUBPART_PATTERNS = [
    re.compile(r"^\s*\(?([a-h])\)"),
    re.compile(r"^\s*([a-h])\)"),
]

SUBSUB_PATTERNS = [
    re.compile(r"^\s*\(?([ivx]+)\)"),
    re.compile(r"^\s*([ivx]+)\)"),
]

BULLET_PATTERNS = [
    re.compile(r"^\s*[\u2022\-*]\s+"),
]

OR_PATTERN = re.compile(r"^\s*or\s*$", re.IGNORECASE)
MARKS_PATTERN = re.compile(r"\bmarks?\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    return (text or "").strip()


def _line_is_section(text: str) -> bool:
    if not text:
        return False
    lowered = text.strip().lower()
    if lowered.startswith("set-"):
        return True
    return any(pat.search(lowered) for pat in SECTION_PATTERNS)


def _line_is_instruction(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in INSTRUCTION_PATTERNS)


def _line_is_global_preface(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in GLOBAL_PREFACE_PATTERNS)


def _line_is_question_like(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in QUESTION_VERB_PATTERNS)


def _line_is_subpart(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in SUBPART_PATTERNS + SUBSUB_PATTERNS + BULLET_PATTERNS)


def _line_is_or(text: str) -> bool:
    return bool(text) and bool(OR_PATTERN.match(text.strip()))


def _extract_explicit_qnum(text: str) -> Optional[str]:
    if not text:
        return None
    if "/" in text:
        return None
    lowered = text.lower()
    if MARKS_PATTERN.search(lowered) and not lowered.startswith("question") and not lowered.startswith("q"):
        return None
    for pat in EXPLICIT_Q_PATTERNS:
        m = pat.match(text)
        if m:
            return m.group(1)
    return None


def _is_valid_numeric_anchor_text(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False
    # reject decimal/time-like starts (e.g. 10.30 a.m.)
    if re.match(r"^\s*\d+\.\d", t):
        return False
    if re.search(r"\b(a\.m|p\.m)\b", t, re.IGNORECASE):
        return False
    if MARKS_PATTERN.search(t) and not re.match(r"^\s*(Q\.?\s*\d+|Question\s*\d+|\d+\s*[\).])", t, re.IGNORECASE):
        return False
    return True


def _is_probable_header_footer(line: Dict[str, Any]) -> bool:
    text = _normalize(line.get("text", ""))
    if not text:
        return True
    bbox = line.get("bbox") or {}
    top = float(bbox.get("top", 0.0))
    left = float(bbox.get("left", 0.0))
    if text.isdigit() and (top < 0.05 or top > 0.9 or left > 0.6):
        return True
    return False


def _bbox_union(lines: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not lines:
        return None
    lefts = []
    tops = []
    rights = []
    bottoms = []
    for line in lines:
        bbox = line.get("bbox") or {}
        left = float(bbox.get("left", 0.0))
        top = float(bbox.get("top", 0.0))
        width = float(bbox.get("width", 0.0))
        height = float(bbox.get("height", 0.0))
        lefts.append(left)
        tops.append(top)
        rights.append(left + width)
        bottoms.append(top + height)
    if not lefts:
        return None
    return {
        "left": min(lefts),
        "top": min(tops),
        "width": max(rights) - min(lefts),
        "height": max(bottoms) - min(tops),
    }


def _median_height(lines: List[Dict[str, Any]]) -> float:
    heights = [float((l.get("bbox") or {}).get("height", 0.0)) for l in lines]
    heights = [h for h in heights if h > 0]
    if not heights:
        return 0.02
    return float(median(heights))


def _group_lines_by_page(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for line in lines:
        page = int(line.get("page") or 1)
        grouped.setdefault(page, []).append(line)
    out: List[Dict[str, Any]] = []
    for page in sorted(grouped.keys()):
        text = "\n".join([l.get("text", "") for l in grouped[page]]).strip()
        out.append({"page": page, "text": text})
    return out


def _build_paragraphs(lines_sorted: List[Dict[str, Any]], gap_threshold: float) -> List[Dict[str, Any]]:
    paragraphs: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    prev_line: Optional[Dict[str, Any]] = None
    for line in lines_sorted:
        if prev_line is None:
            current = [line]
            prev_line = line
            continue
        new_paragraph = False
        if line.get("page") != prev_line.get("page"):
            new_paragraph = True
        else:
            prev_bbox = prev_line.get("bbox") or {}
            curr_bbox = line.get("bbox") or {}
            prev_bottom = float(prev_bbox.get("top", 0.0)) + float(prev_bbox.get("height", 0.0))
            gap = float(curr_bbox.get("top", 0.0)) - prev_bottom
            if gap > gap_threshold:
                new_paragraph = True
        if new_paragraph:
            paragraphs.append({"lines": current})
            current = [line]
        else:
            current.append(line)
        prev_line = line
    if current:
        paragraphs.append({"lines": current})
    return paragraphs


def _find_next_explicit(paragraphs: List[Dict[str, Any]], start_idx: int, lookahead: int) -> Optional[int]:
    end = min(len(paragraphs), start_idx + lookahead + 1)
    for idx in range(start_idx, end):
        para = paragraphs[idx]
        if para.get("explicit_anchor_lines"):
            return idx
    return None


def _span_evidence(span: Dict[str, Any]) -> Dict[str, Any]:
    lines = span.get("lines") or []
    line_count = max(1, len(lines))
    avg_height = None
    if lines:
        avg_height = sum(float((l.get("bbox") or {}).get("height", 0.0)) for l in lines) / float(line_count)
    return {
        "anchor_bbox": span.get("anchor_bbox"),
        "anchor_text": span.get("anchor_text"),
        "next_anchor_text": span.get("next_anchor_text"),
        "page_range": span.get("page_numbers"),
        "layout_features": {
            "avg_line_height": avg_height,
            "density": float(line_count),
            "table_presence": False,
        },
        "span_confidence": span.get("anchor_confidence", 0.5),
    }


def _detect_subparts(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    subparts: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in lines:
        text = _normalize(line.get("text", ""))
        marker = None
        kind = None
        for pat in SUBPART_PATTERNS:
            m = pat.search(text)
            if m:
                marker = m.group(1)
                kind = "alpha"
                break
        if marker is None:
            for pat in SUBSUB_PATTERNS:
                m = pat.search(text)
                if m:
                    marker = m.group(1)
                    kind = "roman"
                    break
        if marker is None:
            for pat in BULLET_PATTERNS:
                if pat.search(text):
                    marker = f"bullet_{len(subparts)+1}"
                    kind = "bullet"
                    break

        if marker:
            if current:
                current["bbox"] = _bbox_union(current["lines"])
                current["page_numbers"] = sorted({l.get("page") for l in current["lines"] if l.get("page")})
                current["text"] = " ".join([_normalize(l.get("text", "")) for l in current["lines"]]).strip()
                subparts.append(current)
            current = {
                "sub_id": marker,
                "kind": kind or "alpha",
                "lines": [line],
            }
        elif current:
            current["lines"].append(line)

    if current:
        current["bbox"] = _bbox_union(current["lines"])
        current["page_numbers"] = sorted({l.get("page") for l in current["lines"] if l.get("page")})
        current["text"] = " ".join([_normalize(l.get("text", "")) for l in current["lines"]]).strip()
        subparts.append(current)
    return subparts


def _split_choices(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    choices: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    for line in lines:
        text = _normalize(line.get("text", ""))
        if _line_is_or(text):
            if current:
                choices.append({"lines": current})
                current = []
            continue
        current.append(line)
    if current:
        choices.append({"lines": current})

    if len(choices) <= 1:
        return []

    out: List[Dict[str, Any]] = []
    for idx, choice in enumerate(choices, 1):
        lines_chunk = choice.get("lines") or []
        out.append(
            {
                "choice_id": f"choice_{idx}",
                "lines": lines_chunk,
                "bbox": _bbox_union(lines_chunk),
                "page_numbers": sorted({l.get("page") for l in lines_chunk if l.get("page")}),
                "text": " ".join([_normalize(l.get("text", "")) for l in lines_chunk]).strip(),
                "subparts": _detect_subparts(lines_chunk),
            }
        )
    return out


def build_span_graph(
    *,
    line_positions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build span graph using layout markers, instructions, and explicit anchors."""
    cleaned_lines: List[Dict[str, Any]] = []
    for line in line_positions or []:
        text = _normalize(line.get("text", ""))
        if not text:
            continue
        bbox = line.get("bbox") or {}
        cleaned_lines.append(
            {
                "page": int(line.get("page") or 1),
                "text": text,
                "bbox": {
                    "left": float(bbox.get("left", 0.0)),
                    "top": float(bbox.get("top", 0.0)),
                    "width": float(bbox.get("width", 0.0)),
                    "height": float(bbox.get("height", 0.0)),
                },
            }
        )

    lines_sorted = sorted(
        cleaned_lines,
        key=lambda l: (l.get("page", 0), (l.get("bbox") or {}).get("top", 0.0), (l.get("bbox") or {}).get("left", 0.0)),
    )

    for idx, line in enumerate(lines_sorted):
        line["global_idx"] = idx

    gap_threshold = max(_median_height(lines_sorted) * 1.6, 0.015)
    paragraphs = _build_paragraphs(lines_sorted, gap_threshold)

    anchors: List[Dict[str, Any]] = []
    # First pass: classify paragraphs and detect explicit anchors line-wise.
    for para in paragraphs:
        lines = para.get("lines") or []
        if not lines:
            continue
        first_line = lines[0]
        first_text = first_line.get("text", "")
        para["kind"] = "section" if _line_is_section(first_text) else ("instruction" if _line_is_instruction(first_text) else "normal")
        para["explicit_anchor_lines"] = []

        for candidate in lines:
            text = candidate.get("text", "")
            qnum = _extract_explicit_qnum(text)
            if not qnum:
                continue
            if not _is_valid_numeric_anchor_text(text):
                continue
            if _is_probable_header_footer(candidate):
                continue
            if float((candidate.get("bbox") or {}).get("left", 1.0)) > 0.4:
                continue
            if _line_is_subpart(text):
                continue
            para["explicit_anchor_lines"].append((candidate, qnum))

    # Second pass: create explicit anchors first, then synthetic/instruction for no-explicit paragraphs.
    last_anchor_idx: Optional[int] = None
    last_section_idx: Optional[int] = None
    for idx, para in enumerate(paragraphs):
        lines = para.get("lines") or []
        if not lines:
            continue
        if para.get("kind") == "section" and not (para.get("explicit_anchor_lines") or []):
            last_section_idx = idx
            continue

        explicit_anchor_lines = para.get("explicit_anchor_lines") or []
        if explicit_anchor_lines:
            for explicit_line, qnum in explicit_anchor_lines:
                anchors.append(
                    {
                        "type": "explicit",
                        "question_number": qnum,
                        "page_index": explicit_line.get("page"),
                        "bbox": explicit_line.get("bbox"),
                        "text": explicit_line.get("text"),
                        "confidence": 0.7,
                        "line_idx": explicit_line.get("global_idx"),
                        "para_idx": idx,
                    }
                )
            last_anchor_idx = idx
            continue

        first_line = lines[0]
        first_text = first_line.get("text", "")
        if para.get("kind") == "instruction":
            if _line_is_global_preface(first_text):
                continue
            if _line_is_subpart(first_text):
                continue
            if last_anchor_idx is not None and (idx - last_anchor_idx) <= 2 and (last_section_idx is None or last_section_idx < last_anchor_idx):
                continue
            next_explicit = _find_next_explicit(paragraphs, idx + 1, lookahead=3)
            next_page = None
            if next_explicit is not None:
                next_lines = paragraphs[next_explicit].get("lines") or []
                if next_lines:
                    next_page = next_lines[0].get("page")
            if next_explicit is not None and next_page == first_line.get("page"):
                paragraphs[next_explicit].setdefault("preface_lines", []).extend(lines)
                continue
            if _is_probable_header_footer(first_line):
                continue
            anchors.append(
                {
                    "type": "instruction",
                    "question_number": _extract_explicit_qnum(first_text),
                    "page_index": first_line.get("page"),
                    "bbox": first_line.get("bbox"),
                    "text": first_text,
                    "confidence": 0.35,
                    "line_idx": first_line.get("global_idx"),
                    "para_idx": idx,
                }
            )
            last_anchor_idx = idx
            continue

        if _line_is_question_like(first_text) and not _line_is_subpart(first_text):
            if float((first_line.get("bbox") or {}).get("left", 1.0)) <= 0.38:
                if _is_probable_header_footer(first_line):
                    continue
                if last_anchor_idx is not None and (idx - last_anchor_idx) <= 2 and (last_section_idx is None or last_section_idx < last_anchor_idx):
                    continue
                anchors.append(
                    {
                        "type": "synthetic",
                        "question_number": _extract_explicit_qnum(first_text),
                        "page_index": first_line.get("page"),
                        "bbox": first_line.get("bbox"),
                        "text": first_text,
                        "confidence": 0.35,
                        "line_idx": first_line.get("global_idx"),
                        "para_idx": idx,
                    }
                )
                last_anchor_idx = idx

    anchors_sorted = sorted(anchors, key=lambda a: (a.get("page_index", 0), (a.get("bbox") or {}).get("top", 0.0)))
    deduped: List[Dict[str, Any]] = []
    for anchor in anchors_sorted:
        if not deduped:
            deduped.append(anchor)
            continue
        prev = deduped[-1]
        prev_q = str(prev.get("question_number") or "")
        curr_q = str(anchor.get("question_number") or "")
        if prev_q and curr_q and prev_q == curr_q:
            continue
        same_page = prev.get("page_index") == anchor.get("page_index")
        prev_top = float((prev.get("bbox") or {}).get("top", 0.0))
        curr_top = float((anchor.get("bbox") or {}).get("top", 0.0))
        close = abs(prev_top - curr_top) < 0.01
        same_q = prev_q == curr_q
        same_text = _normalize(prev.get("text", "")) == _normalize(anchor.get("text", ""))
        if same_page and close and (same_q or same_text):
            continue
        deduped.append(anchor)
    anchors_sorted = deduped

    spans: List[Dict[str, Any]] = []
    if not anchors_sorted and lines_sorted:
        raw_text = "\n".join([l.get("text", "") for l in lines_sorted]).strip()
        spans.append(
            {
                "span_id": "span_fallback",
                "span_type": "question",
                "question_number": None,
                "anchor_type": "fallback",
                "anchor_text": "fallback",
                "anchor_bbox": None,
                "anchor_confidence": 0.2,
                "page_numbers": sorted({l.get("page") for l in lines_sorted if l.get("page")}),
                "lines": lines_sorted,
                "raw_text_by_page": _group_lines_by_page(lines_sorted),
                "preview_text": raw_text[:300],
                "next_anchor_text": None,
            }
        )

    if anchors_sorted:
        # Preface before first anchor (non-question)
        first_anchor = anchors_sorted[0]
        first_idx = first_anchor.get("line_idx", 0)
        pre_lines = [l for l in lines_sorted if l.get("global_idx", 0) < first_idx]
        if pre_lines:
            pre_text = "\n".join([l.get("text", "") for l in pre_lines]).strip()
            spans.append(
                {
                    "span_id": "span_preface",
                    "span_type": "non_question",
                    "question_number": None,
                    "anchor_type": "preface",
                    "anchor_text": "preface",
                    "anchor_bbox": None,
                    "anchor_confidence": 0.2,
                    "page_numbers": sorted({l.get("page") for l in pre_lines if l.get("page")}),
                    "lines": pre_lines,
                    "raw_text_by_page": _group_lines_by_page(pre_lines),
                    "preview_text": pre_text[:300],
                    "next_anchor_text": first_anchor.get("text"),
                }
            )

        for idx, anchor in enumerate(anchors_sorted):
            next_anchor = anchors_sorted[idx + 1] if idx + 1 < len(anchors_sorted) else None
            start_idx = anchor.get("line_idx", 0)
            # Attach preface lines if marked for this anchor
            para_idx = anchor.get("para_idx")
            preface_lines = []
            if para_idx is not None:
                preface_lines = paragraphs[para_idx].get("preface_lines", []) or []
            if preface_lines:
                start_idx = min(start_idx, min(l.get("global_idx", start_idx) for l in preface_lines))

            end_idx = next_anchor.get("line_idx") if next_anchor else len(lines_sorted)
            span_lines = [l for l in lines_sorted if start_idx <= l.get("global_idx", 0) < end_idx]

            span_text = "\n".join([l.get("text", "") for l in span_lines]).strip()
            page_numbers = sorted({l.get("page") for l in span_lines if l.get("page")})

            span = {
                "span_id": f"span_{idx + 1}",
                "span_type": "question",
                "question_number": anchor.get("question_number") or _extract_explicit_qnum(anchor.get("text") or span_text),
                "anchor_type": anchor.get("type"),
                "anchor_text": anchor.get("text"),
                "anchor_bbox": anchor.get("bbox"),
                "anchor_confidence": anchor.get("confidence", 0.4),
                "page_numbers": page_numbers,
                "lines": span_lines,
                "raw_text_by_page": _group_lines_by_page(span_lines),
                "preview_text": span_text[:300],
                "next_anchor_text": (next_anchor.get("text") if next_anchor else None),
            }

            choices = _split_choices(span_lines)
            if choices:
                span["choices"] = choices
                span["subparts"] = []
            else:
                span["choices"] = []
                span["subparts"] = _detect_subparts(span_lines)

            span["span_graph"] = {
                "question": {
                    "question_number": span.get("question_number"),
                    "anchor_text": span.get("anchor_text"),
                    "page_numbers": span.get("page_numbers"),
                    "bbox": span.get("anchor_bbox"),
                },
                "subparts": span.get("subparts", []),
                "choices": span.get("choices", []),
            }
            span["span_evidence"] = _span_evidence(span)
            spans.append(span)

    logger.info("[AWS][Layout] spans=%s anchors=%s", len(spans), len(anchors_sorted))
    return {
        "spans": spans,
        "anchors": anchors_sorted,
    }
