"""Layer-1 visual entity extraction (OCR-only, no AI reasoning)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger
from app.utils.ocr_provider import get_ocr_provider

from app.layers.ai_structured.safe_numeric import parse_section_math_expression, safe_float, safe_int


def _norm_label(value: Any) -> Optional[str]:
    s = str(value or "").strip().lower()
    return s or None


def _parse_sub_label(token: str) -> Optional[str]:
    txt = str(token or "").strip().lower()
    if not txt:
        return None
    # Keep subpart labels conservative to avoid capturing section headers
    # like VII/VIII/IX/XI as subparts.
    m = re.match(r"^\(?\s*([a-z]|i|ii|iii|iv|v)\s*\)?\s*[\).:-]?\s*$", txt, flags=re.IGNORECASE)
    if not m:
        return None
    return _norm_label(m.group(1))


def _parse_mark_split(text: str) -> Optional[List[float]]:
    t = str(text or "").strip()
    if not t:
        return None
    m = re.match(
        r"^\s*[\(\[\{]?\s*(\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)+)\s*[\)\]\}]?\s*$",
        t,
    )
    if not m:
        return None
    parts = [safe_float(p, 0.0) for p in re.split(r"\s*\+\s*", m.group(1))]
    if len(parts) < 2 or any(p <= 0 for p in parts):
        return None
    return [round(p, 4) for p in parts]


def _parse_mark_value(text: str) -> Optional[float]:
    t = str(text or "").strip()
    if not t:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:marks?|mks?)\b", t, flags=re.IGNORECASE)
    if m:
        mark = safe_float(m.group(1), 0.0)
        return mark if mark > 0 else None
    split = _parse_mark_split(t)
    if split:
        total = round(sum(split), 4)
        return total if total > 0 else None
    m = re.match(r"^\s*[\(\[\{]?\s*(\d+(?:\.\d+)?)\s*[\)\]\}]?\s*$", t)
    if m:
        mark = safe_float(m.group(1), 0.0)
        return mark if mark > 0 else None
    return None


def _question_number_from_line(text: str) -> Optional[int]:
    txt = str(text or "").strip()
    if not txt:
        return None
    if re.match(r"^\s*\d{1,3}\s*[x×*]\s*\d", txt, flags=re.IGNORECASE):
        return None
    # Require an explicit question delimiter after number to avoid
    # treating expression numbers as question anchors.
    m = re.match(r"^(?:q(?:uestion)?\s*)?(\d{1,3})(?!\d)\s*[\).:-]\s*", txt, flags=re.IGNORECASE)
    if not m:
        return None
    qn = safe_int(m.group(1), 0)
    if qn <= 0 or qn > 300:
        return None
    return qn if qn > 0 else None


@dataclass
class OCRLine:
    text: str
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    page_index: int
    width: float
    height: float

    @property
    def y_mid(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def bbox(self) -> List[float]:
        return [self.x1, self.y1, self.x2, self.y2]


def _collect_lines(images: List[str], *, force_fallback: bool = False) -> List[OCRLine]:
    provider = get_ocr_provider()
    out: List[OCRLine] = []
    for page_index, image in enumerate(images):
        res = provider.detect(image, force_fallback=force_fallback)
        width = float(res.get("width") or 1.0)
        height = float(res.get("height") or 1.0)
        for row in (res.get("lines") or []):
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            out.append(
                OCRLine(
                    text=text,
                    x1=float(row.get("x1") or 0.0),
                    y1=float(row.get("y1") or 0.0),
                    x2=float(row.get("x2") or 0.0),
                    y2=float(row.get("y2") or 0.0),
                    confidence=safe_float(row.get("confidence", row.get("conf")), 0.0),
                    page_index=page_index,
                    width=width,
                    height=height,
                )
            )
    out.sort(key=lambda ln: (ln.page_index, ln.y1, ln.x1))
    return out


def _extract_question_and_subpart_entities(lines: List[OCRLine]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    questions: Dict[int, Dict[str, Any]] = {}
    subparts: List[Dict[str, Any]] = []
    by_page: Dict[int, List[OCRLine]] = defaultdict(list)
    for ln in lines:
        by_page[int(ln.page_index)].append(ln)

    for page in sorted(by_page.keys()):
        page_lines = sorted(by_page[page], key=lambda ln: (ln.y1, ln.x1))
        current_q: Optional[int] = None
        for ln in page_lines:
            qn = _question_number_from_line(ln.text)
            if qn is not None:
                current_q = qn
                if qn not in questions:
                    questions[qn] = {
                        "number": qn,
                        "bbox": ln.bbox,
                        "page": page,
                        "confidence": round(float(ln.confidence), 4),
                    }
                else:
                    ex = questions[qn]
                    ex_page = int(ex.get("page", 10**9))
                    ex_conf = safe_float(ex.get("confidence"), 0.0)
                    # Prefer more confident anchor; break ties with later page to
                    # avoid early OCR-number noise overriding true anchors.
                    if float(ln.confidence) > ex_conf + 1e-6 or (
                        abs(float(ln.confidence) - ex_conf) <= 1e-6 and page > ex_page
                    ):
                        questions[qn] = {
                            "number": qn,
                            "bbox": ln.bbox,
                            "page": page,
                            "confidence": round(float(ln.confidence), 4),
                        }

                rest = re.sub(
                    r"^(?:q(?:uestion)?\s*)?\d{1,3}\s*[\).:-]?\s*",
                    "",
                    ln.text,
                    flags=re.IGNORECASE,
                )
                m_sub = re.match(r"^\s*(\(?\s*(?:[a-z]|[ivxlcdm]{1,5})\s*\)?\s*[\).:-])", rest, flags=re.IGNORECASE)
                if m_sub:
                    label = _parse_sub_label(m_sub.group(1))
                    if label:
                        subparts.append(
                            {
                                "q": qn,
                                "label": label,
                                "bbox": ln.bbox,
                                "page": page,
                                "confidence": round(float(ln.confidence), 4),
                            }
                        )
                continue

            if current_q is None:
                continue
            m_sub = re.match(r"^\s*(\(?\s*(?:[a-z]|[ivxlcdm]{1,5})\s*\)?\s*[\).:-])", ln.text, flags=re.IGNORECASE)
            if not m_sub:
                continue
            label = _parse_sub_label(m_sub.group(1))
            if not label:
                continue
            subparts.append(
                {
                    "q": current_q,
                    "label": label,
                    "bbox": ln.bbox,
                    "page": page,
                    "confidence": round(float(ln.confidence), 4),
                }
            )

    question_rows = [questions[k] for k in sorted(questions.keys())]
    return question_rows, subparts


def _extract_margin_marks(lines: List[OCRLine], questions: List[Dict[str, Any]], subparts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    anchors: List[Tuple[int, Optional[str], int, float]] = []
    for q in questions:
        bbox = q.get("bbox") or [0, 0, 0, 0]
        anchors.append((safe_int(q.get("number"), 0), None, safe_int(q.get("page"), 0), safe_float(bbox[1], 0.0)))
    for sp in subparts:
        bbox = sp.get("bbox") or [0, 0, 0, 0]
        anchors.append((safe_int(sp.get("q"), 0), _norm_label(sp.get("label")), safe_int(sp.get("page"), 0), safe_float(bbox[1], 0.0)))

    margin_candidates: List[Dict[str, Any]] = []
    for ln in lines:
        if safe_float(ln.confidence, 0.0) < 0.75:
            continue
        right_ratio = ln.x1 / max(1.0, ln.width)
        if right_ratio < 0.62 and (ln.x2 / max(1.0, ln.width)) < 0.78:
            continue
        mark = _parse_mark_value(ln.text)
        if mark is None:
            continue
        if len(ln.text.strip()) > 24:
            continue
        split = _parse_mark_split(ln.text)
        margin_candidates.append(
            {
                "marks": round(mark, 4),
                "text": str(ln.text or "").strip(),
                "split": split or None,
                "page": int(ln.page_index),
                "y_mid": float(ln.y_mid),
                "bbox": ln.bbox,
                "confidence": float(ln.confidence),
                "used": False,
            }
        )

    out: List[Dict[str, Any]] = []
    anchors.sort(key=lambda a: (a[2], a[3]))
    for qn, sub, page, y in anchors:
        if qn <= 0:
            continue
        same_page = [m for m in margin_candidates if not m["used"] and int(m["page"]) == int(page)]
        if not same_page:
            continue
        nearest = min(same_page, key=lambda m: abs(float(m["y_mid"]) - y))
        if abs(float(nearest["y_mid"]) - y) > 48.0:
            continue
        nearest["used"] = True
        out.append(
            {
                "q": int(qn),
                "sub": _norm_label(sub),
                "marks": round(safe_float(nearest.get("marks"), 0.0), 4),
                "text": str(nearest.get("text") or "").strip(),
                "split": list(nearest.get("split") or []) or None,
                "bbox": list(nearest.get("bbox") or [0, 0, 0, 0]),
                "page": int(nearest.get("page") or 0),
                "confidence": round(safe_float(nearest.get("confidence"), 0.0), 4),
            }
        )
    return out


def _question_anchors_from_lines(lines: List[OCRLine]) -> List[Tuple[int, float, int, List[float]]]:
    anchors: Dict[Tuple[int, int], Tuple[float, List[float]]] = {}
    by_page: Dict[int, List[OCRLine]] = defaultdict(list)
    for ln in lines:
        by_page[int(ln.page_index)].append(ln)

    for page in sorted(by_page.keys()):
        page_lines = sorted(by_page[page], key=lambda ln: (ln.y1, ln.x1))
        for ln in page_lines:
            qn = _question_number_from_line(ln.text)
            if qn is None:
                continue
            key = (page, qn)
            y = float(ln.y1)
            bbox = ln.bbox
            if key not in anchors or y < anchors[key][0]:
                anchors[key] = (y, bbox)

    out: List[Tuple[int, float, int, List[float]]] = []
    for (page, qn), (y, bbox) in anchors.items():
        out.append((page, y, qn, bbox))
    out.sort(key=lambda row: (row[0], row[1], row[2]))
    return out


def _extract_section_math(lines: List[OCRLine]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    token_re = re.compile(r"\d+(?:\.\d+)?|[xX×*]|=")

    def _clean_text(text: str) -> str:
        s = str(text or "")
        s = s.replace("×", "x").replace("*", "x").replace("X", "x")
        s = re.sub(r"[()\[\]{}.,;:]", " ", s)
        return " ".join(s.split())

    def _norm_math_token(token: str) -> Optional[str]:
        if not token:
            return None
        if token in {"×", "*", "X", "x"}:
            return "x"
        if token == "=":
            return "="
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            return token
        return None

    def _join_raw_tokens(window: List[Dict[str, Any]]) -> str:
        raw = " ".join(str(w.get("raw") or "").strip() for w in window)
        return " ".join(raw.split())

    def _merge_across_line_breaks(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Flattened math tokens already ignore line breaks; keep a pass for clarity
        # and future merge heuristics.
        if not tokens:
            return tokens
        merged: List[Dict[str, Any]] = []
        for tok in tokens:
            if not merged:
                merged.append(tok)
                continue
            prev = merged[-1]
            if prev.get("line_idx") != tok.get("line_idx"):
                # Explicitly allow math tokens to be adjacent across line breaks.
                tok["merged_line_break"] = True
            merged.append(tok)
        return merged

    q_anchors = _question_anchors_from_lines(lines)

    by_page: Dict[int, List[OCRLine]] = defaultdict(list)
    for ln in lines:
        by_page[int(ln.page_index)].append(ln)
    for page in by_page:
        by_page[page].sort(key=lambda ln: (ln.y1, ln.x1))

    seen: set[Tuple[int, int, int, int, float, float]] = set()

    for page, page_lines in sorted(by_page.items(), key=lambda it: it[0]):
        tokens: List[Dict[str, Any]] = []
        for line_idx, ln in enumerate(page_lines):
            raw_line = str(ln.text or "")
            clean_line = _clean_text(raw_line)
            if not clean_line:
                continue
            for tok in token_re.findall(raw_line):
                norm = _norm_math_token(tok)
                if not norm:
                    continue
                tokens.append(
                    {
                        "text": norm,
                        "raw": tok,
                        "line": ln,
                        "line_idx": line_idx,
                        "bbox": [ln.x1, ln.y1, ln.x2, ln.y2],
                    }
                )

        tokens = _merge_across_line_breaks(tokens)

        for i in range(0, max(0, len(tokens) - 4)):
            window = tokens[i:i + 5]
            if len(window) < 5:
                continue
            if window[1]["text"] != "x" or window[3]["text"] != "=":
                continue
            n = safe_int(window[0]["text"], 0)
            m = safe_float(window[2]["text"], 0.0)
            x_val = safe_float(window[4]["text"], 0.0)
            if n <= 0 or m <= 0 or x_val <= 0:
                continue

            # Allow multi-line expressions; cap excessive vertical span.
            y_span = max(w["bbox"][3] for w in window) - min(w["bbox"][1] for w in window)
            if y_span > (window[0]["line"].height * 0.2):
                continue

            expr_text = _join_raw_tokens(window)
            if abs((n * m) - x_val) > 1e-6:
                logger.info("SECTION_RULE_REJECTED reason=validation_failed text=%s", expr_text)
                continue

            signature = (
                page,
                int(min(w["line_idx"] for w in window)),
                int(max(w["line_idx"] for w in window)),
                int(n),
                round(float(m), 4),
                round(float(x_val), 4),
            )
            if signature in seen:
                continue
            seen.add(signature)

            line_indices = [int(w["line_idx"]) for w in window]
            min_line = min(line_indices)
            max_line = max(line_indices)
            heading_lines = [ln for idx, ln in enumerate(page_lines) if min_line <= idx <= max_line]
            if heading_lines:
                bbox_x1 = min(ln.x1 for ln in heading_lines)
                bbox_y1 = min(ln.y1 for ln in heading_lines)
                bbox_x2 = max(ln.x2 for ln in heading_lines)
                bbox_y2 = max(ln.y2 for ln in heading_lines)
            else:
                bbox_x1 = min(w["bbox"][0] for w in window)
                bbox_y1 = min(w["bbox"][1] for w in window)
                bbox_x2 = max(w["bbox"][2] for w in window)
                bbox_y2 = max(w["bbox"][3] for w in window)
            conf = round(
                sum(float(w["line"].confidence) for w in window) / float(len(window)),
                4,
            )
            logger.info("SECTION_RULE_SOURCE text=%s", expr_text)

            start_q: Optional[int] = None
            best_dist = None
            for q_page, y, qn, qb in q_anchors:
                if q_page != page:
                    continue
                # Prefer nearest question anchor below heading; if none, allow above.
                dist = y - bbox_y2
                if dist < 0:
                    continue
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    start_q = qn
            if start_q is None:
                for q_page, y, qn, _bbox in q_anchors:
                    if q_page > page:
                        start_q = qn
                        break
            if start_q is None and q_anchors:
                prev: Optional[int] = None
                for q_page, y, qn, _bbox in q_anchors:
                    if (q_page < page) or (q_page == page and y <= bbox_y2):
                        prev = qn
                    else:
                        break
                start_q = prev if prev is not None else q_anchors[0][2]

            end_q = None
            if start_q is not None:
                end_q = start_q + n - 1
            logger.info(
                "SECTION_RULE_HEADING expr=%s start_question=%s",
                expr_text,
                start_q,
            )
            logger.info(
                "SECTION_RULE_DETECTED page=%s expr=%s start=%s end=%s",
                page,
                expr_text,
                start_q,
                end_q,
            )

            rows.append(
                {
                    "count": int(n),
                    "per": round(float(m), 4),
                    "total": round(float(x_val), 4),
                    "range": {"start": int(start_q), "end": int(end_q)} if start_q is not None and end_q is not None else None,
                    "expr": f"{int(n)} x {round(float(m), 4)} = {round(float(x_val), 4)}",
                    "bbox": [bbox_x1, bbox_y1, bbox_x2, bbox_y2],
                    "page": int(page),
                    "confidence": conf,
                }
            )

    return rows


def _extract_or_connectors(lines: List[OCRLine], questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_page: Dict[int, List[Tuple[int, float]]] = defaultdict(list)
    for q in questions:
        bbox = q.get("bbox") or [0, 0, 0, 0]
        by_page[safe_int(q.get("page"), 0)].append((safe_int(q.get("number"), 0), safe_float(bbox[1], 0.0)))
    for page in by_page:
        by_page[page].sort(key=lambda it: it[1])

    connectors: List[Dict[str, Any]] = []
    for ln in lines:
        if re.sub(r"[^A-Z]", "", str(ln.text or "").upper()) != "OR":
            continue
        anchors = by_page.get(int(ln.page_index)) or []
        prev_q = None
        next_q = None
        for qn, y in anchors:
            if y < ln.y_mid:
                prev_q = qn
            elif y > ln.y_mid:
                next_q = qn
                break
        if prev_q and next_q and prev_q != next_q:
            connectors.append(
                {
                    "q1": int(min(prev_q, next_q)),
                    "q2": int(max(prev_q, next_q)),
                    "bbox": ln.bbox,
                    "page": int(ln.page_index),
                    "confidence": round(float(ln.confidence), 4),
                }
            )
    return connectors


def _extract_headers(lines: List[OCRLine]) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    headers: List[Dict[str, Any]] = []
    best_header_total: Optional[Dict[str, Any]] = None
    best_score = -1.0

    for ln in lines:
        txt = str(ln.text or "").strip()
        if not txt:
            continue
        low = txt.lower()
        if ln.y1 <= ln.height * 0.22:
            if re.search(r"\b(section|part)\b", low):
                headers.append(
                    {
                        "kind": "section",
                        "text": txt,
                        "bbox": ln.bbox,
                        "page": int(ln.page_index),
                        "confidence": round(float(ln.confidence), 4),
                    }
                )

            m = re.search(r"(?:maximum|max(?:imum)?\.?)\s*marks?\s*[:\-]?\s*(\d+(?:\.\d+)?)", low, flags=re.IGNORECASE)
            if not m:
                m = re.search(r"\bm\.?\s*m\.?\s*[:\-]?\s*(\d+(?:\.\d+)?)\b", low, flags=re.IGNORECASE)
            if not m:
                m = re.search(r"\btotal\s*marks?\s*[:\-]?\s*(\d+(?:\.\d+)?)\b", low, flags=re.IGNORECASE)
            if m:
                mark = safe_float(m.group(1), 0.0)
                if mark > 0:
                    score = float(ln.confidence)
                    if "maximum" in low or "max" in low or "m.m" in low or "m m" in low:
                        score += 1.0
                    reliable = score >= 1.0
                    candidate = {
                        "marks": round(mark, 4),
                        "reliable": bool(reliable),
                        "confidence": round(min(1.0, score / 2.0), 4),
                        "source": "visual_header",
                        "evidence": {"bbox": ln.bbox, "page": int(ln.page_index), "text": txt},
                    }
                    if score > best_score:
                        best_score = score
                        best_header_total = candidate

    return headers, best_header_total


def extract_visual_entities(
    question_paper_images: List[str],
    *,
    force_ocr_fallback: bool = False,
) -> Dict[str, Any]:
    """
    Layer-1 visual ground-truth extraction.
    Returns OCR-derived entities only; no AI/semantic reasoning.
    """
    lines = _collect_lines(question_paper_images or [], force_fallback=force_ocr_fallback)
    section_math = _extract_section_math(lines)
    questions, subparts = _extract_question_and_subpart_entities(lines)
    margin_marks = _extract_margin_marks(lines, questions, subparts)
    or_connectors = _extract_or_connectors(lines, questions)
    headers, header_total = _extract_headers(lines)

    entities = {
        "questions": questions,
        "subparts": subparts,
        "margin_marks": margin_marks,
        "section_math": section_math,
        "or_connectors": or_connectors,
        "headers": headers,
        "header_total": header_total,
    }
    logger.info(
        "VISUAL_ENTITIES_EXTRACTED questions=%s subparts=%s margin_marks=%s section_math=%s or_connectors=%s",
        len(questions),
        len(subparts),
        len(margin_marks),
        len(section_math),
        len(or_connectors),
    )
    return entities


__all__ = ["extract_visual_entities"]
