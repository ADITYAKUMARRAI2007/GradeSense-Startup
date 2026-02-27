"""Visual mark resolver for deterministic question/subpart marks."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger
from app.utils.ocr_provider import get_ocr_provider


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _norm_sub_label(label: Optional[str]) -> Optional[str]:
    if label is None:
        return None
    s = str(label).strip().lower()
    return s or None


def _key(qn: int, sub_label: Optional[str]) -> Tuple[int, Optional[str]]:
    return int(qn), _norm_sub_label(sub_label)


def _evidence(page_index: int, bbox: List[float], confidence: float) -> List[Any]:
    return [int(page_index), list(bbox), round(float(confidence), 4)]


def _extract_mark_value(text: str) -> Optional[float]:
    t = (text or "").strip()
    if not t:
        return None

    # Explicit "... marks" is strongest.
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:marks?|mks?)\b", t, flags=re.IGNORECASE)
    if m:
        return _to_float(m.group(1), 0.0)

    # Bracketed/standalone margin formats: "(5)", "[2]", "3".
    m = re.match(r"^\s*[\(\[\{]?\s*(\d+(?:\.\d+)?)\s*[\)\]\}]?\s*$", t)
    if m:
        return _to_float(m.group(1), 0.0)

    # Common style: "Q1 (5)".
    m = re.search(r"[\(\[\{]\s*(\d+(?:\.\d+)?)\s*[\)\]\}]", t)
    if m:
        return _to_float(m.group(1), 0.0)

    return None


def _parse_sub_label(prefix: str) -> Optional[str]:
    txt = (prefix or "").strip().lower()
    if not txt:
        return None

    # "(a)", "a.", "(ii)", "ii)"
    m = re.match(r"^\(?\s*([a-z]|[ivxlcdm]{1,5})\s*\)?\s*[\).:-]?\s*$", txt, flags=re.IGNORECASE)
    if m:
        return _norm_sub_label(m.group(1))
    return None


def _question_number_from_line(text: str) -> Optional[int]:
    txt = (text or "").strip()
    if not txt:
        return None
    # Avoid section math like "7 x 2 = 14" being treated as question anchors.
    if re.match(r"^\s*\d{1,3}\s*[x×*]\s*\d", txt, flags=re.IGNORECASE):
        return None
    m = re.match(r"^(?:q(?:uestion)?\s*)?(\d{1,3})(?!\d)\s*[\).:-]?\s*", txt, flags=re.IGNORECASE)
    if not m:
        return None
    return _to_int(m.group(1), 0)


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


def _collect_ocr_lines(images: List[str]) -> List[OCRLine]:
    provider = get_ocr_provider()
    out: List[OCRLine] = []
    for page_index, image in enumerate(images):
        res = provider.detect(image)
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
                    confidence=_to_float(row.get("confidence", row.get("conf")), 0.0),
                    page_index=page_index,
                    width=width,
                    height=height,
                )
            )
    out.sort(key=lambda ln: (ln.page_index, ln.y1, ln.x1))
    return out


def _detect_header_total(lines: List[OCRLine]) -> Tuple[Optional[float], Optional[List[Any]], float, Optional[str]]:
    best: Optional[Tuple[float, float, List[Any], str]] = None  # (score, marks, evidence, source)
    for ln in lines:
        # Header must be near top of first page.
        if ln.page_index != 0:
            continue
        if ln.y1 > (ln.height * 0.24):
            continue

        txt = ln.text.lower()
        mark = None
        score = max(0.0, ln.confidence)
        source: Optional[str] = None

        m = re.search(r"(?:maximum|max(?:imum)?\.?)\s*marks?\s*[:\-]?\s*(\d+(?:\.\d+)?)", txt, flags=re.IGNORECASE)
        if m:
            mark = _to_float(m.group(1), 0.0)
            score += 2.5
            source = "header_maximum"
        else:
            m = re.search(r"\bm\.?\s*m\.?\s*[:\-]?\s*(\d+(?:\.\d+)?)\b", txt, flags=re.IGNORECASE)
            if m:
                mark = _to_float(m.group(1), 0.0)
                score += 2.0
                source = "header_mm"
            else:
                m = re.search(r"\btotal\s*marks?\s*[:\-]?\s*(\d+(?:\.\d+)?)\b", txt, flags=re.IGNORECASE)
                if m:
                    mark = _to_float(m.group(1), 0.0)
                    score += 0.8
                    source = "header_total"

        if mark is None:
            continue
        if mark <= 0:
            continue

        ev = _evidence(ln.page_index, ln.bbox, ln.confidence)
        if best is None or score > best[0]:
            best = (score, mark, ev, str(source or "header_unknown"))

    if best:
        return best[1], best[2], round(best[0], 4), best[3]
    return None, None, 0.0, None


def _parse_section_math(lines: List[OCRLine]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)", flags=re.IGNORECASE)
    for ln in lines:
        m = pattern.search(ln.text)
        if not m:
            continue
        count = _to_int(m.group(1), 0)
        each = _to_float(m.group(2), 0.0)
        total = _to_float(m.group(3), 0.0)
        if count <= 0 or each <= 0 or total <= 0:
            continue
        # Keep only coherent equations.
        if abs((count * each) - total) > max(1.0, 0.15 * max(total, 1.0)):
            continue

        expr_str = f"{count}x{round(each, 4)}={round(total, 4)}"
        expr = {
            "section": None,
            "expression": expr_str,
            "question_count": count,
            "per_question_marks": round(each, 4),
            "total_marks": round(total, 4),
            "page_index": ln.page_index,
            "bbox": ln.bbox,
            "confidence": ln.confidence,
            # Backward-compat aliases for internal consumers.
            "count": count,
            "each": round(each, 4),
            "total": round(total, 4),
        }
        out.append(expr)
        logger.info(
            "SECTION_MATH_PARSED page=%s expr=%s×%s=%s",
            ln.page_index + 1,
            count,
            each,
            total,
        )
    return out


def _extract_instruction_mark(*texts: Optional[str]) -> Optional[float]:
    for raw in texts:
        txt = str(raw or "").strip().lower()
        if not txt:
            continue
        m = re.search(r"\b(?:in|for|of)?\s*(\d+(?:\.\d+)?)\s*(?:marks?|mks?)\b", txt, flags=re.IGNORECASE)
        if not m:
            continue
        mark = _to_float(m.group(1), 0.0)
        if mark > 0:
            return round(mark, 4)
    return None


def _find_question_anchors(lines: List[OCRLine], valid_questions: set[int]) -> List[Dict[str, Any]]:
    anchors: List[Dict[str, Any]] = []
    by_page: Dict[int, List[OCRLine]] = defaultdict(list)
    for ln in lines:
        by_page[ln.page_index].append(ln)

    for page_index in sorted(by_page.keys()):
        page_lines = sorted(by_page[page_index], key=lambda x: (x.y1, x.x1))
        current_q: Optional[int] = None
        for ln in page_lines:
            qn = _question_number_from_line(ln.text)
            if qn is not None and qn in valid_questions:
                current_q = qn
                rest = re.sub(
                    r"^(?:q(?:uestion)?\s*)?\d{1,3}\s*[\).:-]?\s*",
                    "",
                    ln.text,
                    flags=re.IGNORECASE,
                )
                sub = None
                m_sub = re.match(r"^\(?\s*([a-z]|[ivxlcdm]{1,5})\s*\)?\s*[\).:-]", rest, flags=re.IGNORECASE)
                if m_sub:
                    sub = _norm_sub_label(m_sub.group(1))
                anchors.append(
                    {
                        "question_number": qn,
                        "sub_label": sub,
                        "page_index": page_index,
                        "y_mid": ln.y_mid,
                        "bbox": ln.bbox,
                        "confidence": ln.confidence,
                    }
                )
                continue

            if current_q is None:
                continue
            # Subpart-only line (a), (ii), etc.
            m_lead = re.match(r"^\s*(\(?\s*(?:[a-z]|[ivxlcdm]{1,5})\s*\)?\s*[\).:-])", ln.text, flags=re.IGNORECASE)
            if not m_lead:
                continue
            sub = _parse_sub_label(m_lead.group(1))
            if not sub:
                continue
            anchors.append(
                {
                    "question_number": current_q,
                    "sub_label": sub,
                    "page_index": page_index,
                    "y_mid": ln.y_mid,
                    "bbox": ln.bbox,
                    "confidence": ln.confidence,
                }
            )
    return anchors


def _find_right_margin_mark_candidates(lines: List[OCRLine]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    min_conf = 0.78
    for ln in lines:
        if _to_float(ln.confidence, 0.0) < min_conf:
            continue
        right_ratio = ln.x1 / max(ln.width, 1.0)
        if right_ratio < 0.62 and (ln.x2 / max(ln.width, 1.0)) < 0.78:
            continue
        mark = _extract_mark_value(ln.text)
        if mark is None:
            continue
        if len((ln.text or "").strip()) > 16:
            continue
        if mark <= 0 or mark > 200:
            continue
        out.append(
            {
                "mark": round(mark, 4),
                "page_index": ln.page_index,
                "y_mid": ln.y_mid,
                "bbox": ln.bbox,
                "confidence": ln.confidence,
                "used": False,
            }
        )
    out.sort(key=lambda c: (c["page_index"], c["y_mid"]))
    return out


def _detect_visual_or_groups(lines: List[OCRLine], question_anchors: List[Dict[str, Any]]) -> Dict[int, str]:
    question_level = [a for a in question_anchors if a.get("sub_label") is None]
    by_page = defaultdict(list)
    for a in question_level:
        by_page[int(a["page_index"])].append(a)
    for page in by_page:
        by_page[page].sort(key=lambda a: float(a["y_mid"]))

    edges: List[Tuple[int, int]] = []
    for ln in lines:
        txt = re.sub(r"[^A-Z]", "", ln.text.upper())
        if txt != "OR":
            continue
        anchors = by_page.get(ln.page_index) or []
        prev_q = None
        next_q = None
        for a in anchors:
            if float(a["y_mid"]) < ln.y_mid:
                prev_q = int(a["question_number"])
            elif next_q is None and float(a["y_mid"]) > ln.y_mid:
                next_q = int(a["question_number"])
                break
        if prev_q and next_q and prev_q != next_q:
            edges.append((min(prev_q, next_q), max(prev_q, next_q)))

    if not edges:
        return {}

    # Union-find for OR components.
    parent: Dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        pa = find(a)
        pb = find(b)
        if pa != pb:
            parent[pb] = pa

    for a, b in edges:
        union(a, b)

    groups: Dict[int, List[int]] = defaultdict(list)
    for node in list(parent.keys()):
        groups[find(node)].append(node)

    mapping: Dict[int, str] = {}
    gid_seq = 1
    for _, members in sorted(groups.items(), key=lambda kv: min(kv[1])):
        gid = f"visual_or_{gid_seq}"
        gid_seq += 1
        for qn in sorted(set(members)):
            mapping[int(qn)] = gid
    return mapping


def _has_or_signal(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return bool(
        re.search(
            r"^\s*or(?:\s|$|[:\-])|\banswer\s+any\s+one\b|\bany\s+one\b|\beither\b|\bchoose\s+(?:any\s+)?one\b|\battempt\s+any\b",
            t,
            flags=re.IGNORECASE,
        )
    )


def _split_contiguous_runs(nums: List[int]) -> List[List[int]]:
    if not nums:
        return []
    seq = sorted(set(int(n) for n in nums))
    runs: List[List[int]] = [[seq[0]]]
    for n in seq[1:]:
        if n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


def _canonicalize_or_group_ids(
    questions: List[Dict[str, Any]],
    visual_or_map: Dict[int, str],
) -> Dict[int, str]:
    q_by_num: Dict[int, Dict[str, Any]] = {}
    for q in questions:
        qn = _to_int(q.get("number"), 0)
        if qn > 0:
            q_by_num[qn] = q

    edges: List[Tuple[int, int]] = []

    # Visual OR detections are strong evidence.
    visual_groups: Dict[str, List[int]] = defaultdict(list)
    for qn, gid in (visual_or_map or {}).items():
        if qn > 0 and gid:
            visual_groups[str(gid)].append(int(qn))
    for members in visual_groups.values():
        for run in _split_contiguous_runs(members):
            if len(run) < 2:
                continue
            for i in range(len(run) - 1):
                edges.append((run[i], run[i + 1]))

    # AI-provided OR groups are accepted only when contiguous and text has OR signals.
    ai_groups: Dict[str, List[int]] = defaultdict(list)
    for q in questions:
        qn = _to_int(q.get("number"), 0)
        gid = str(q.get("or_group_id") or "").strip()
        if qn > 0 and gid:
            ai_groups[gid].append(qn)
    for members in ai_groups.values():
        for run in _split_contiguous_runs(members):
            if len(run) < 2:
                continue
            has_signal = any(
                _has_or_signal(
                    " ".join(
                        [
                            str((q_by_num.get(qn) or {}).get("instruction") or ""),
                            str((q_by_num.get(qn) or {}).get("question_text") or ""),
                        ]
                    )
                )
                for qn in run
            )
            if not has_signal:
                continue
            for i in range(len(run) - 1):
                edges.append((run[i], run[i + 1]))

    if not edges:
        return {}

    parent: Dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        pa = find(a)
        pb = find(b)
        if pa != pb:
            parent[pb] = pa

    for a, b in edges:
        if a <= 0 or b <= 0:
            continue
        union(int(a), int(b))

    comps: Dict[int, List[int]] = defaultdict(list)
    for node in list(parent.keys()):
        comps[find(node)].append(node)

    out: Dict[int, str] = {}
    gid_seq = 1
    for _, members in sorted(comps.items(), key=lambda kv: min(kv[1])):
        uniq = sorted(set(int(m) for m in members))
        if len(uniq) < 2:
            continue
        gid = f"visual_or_{gid_seq}"
        gid_seq += 1
        for qn in uniq:
            out[qn] = gid
    return out


def _compute_effective_total(question_marks: Dict[int, float], questions: List[Dict[str, Any]]) -> float:
    group_map: Dict[str, List[int]] = defaultdict(list)
    for q in questions:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        gid = str(q.get("or_group_id") or "").strip()
        if gid:
            group_map[gid].append(qn)

    in_group = {qn for qs in group_map.values() for qn in qs}
    total = 0.0
    for qn, mark in question_marks.items():
        if qn not in in_group:
            total += max(0.0, mark)

    for _, qns in group_map.items():
        if not qns:
            continue
        total += max(max(0.0, question_marks.get(qn, 0.0)) for qn in qns)
    return round(total, 4)


async def resolve_visual_marks(
    *,
    question_structure: Dict[str, Any],
    question_paper_images: List[str],
) -> Dict[str, Any]:
    """Resolve visual marks and override AI marks only where evidence exists."""

    questions = [dict(q) for q in (question_structure.get("questions") or [])]
    question_numbers = sorted({_to_int(q.get("number"), 0) for q in questions if _to_int(q.get("number"), 0) > 0})
    valid_q_set = set(question_numbers)

    ai_question_marks: Dict[int, float] = {}
    ai_sub_marks: Dict[Tuple[int, Optional[str]], float] = {}
    for q in questions:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        ai_question_marks[qn] = _to_float(q.get("marks"), 0.0)
        for sq in (q.get("subquestions") or []):
            lbl = _norm_sub_label(sq.get("label"))
            if not lbl:
                continue
            ai_sub_marks[_key(qn, lbl)] = _to_float(sq.get("marks"), 0.0)

    # Collect OCR line geometry once for all detectors.
    lines = _collect_ocr_lines(question_paper_images)
    header_total, header_evidence, header_score, header_source = _detect_header_total(lines)
    section_exprs = _parse_section_math(lines)

    anchors = _find_question_anchors(lines, valid_q_set)
    margin_candidates = _find_right_margin_mark_candidates(lines)

    # Visual evidence maps (authoritative only where present).
    visual_question_marks: Dict[int, float] = {}
    visual_sub_marks: Dict[Tuple[int, Optional[str]], float] = {}
    question_mark_source: Dict[int, str] = {}
    question_mark_confidence: Dict[int, float] = {}
    sub_mark_source: Dict[Tuple[int, Optional[str]], str] = {}
    sub_mark_confidence: Dict[Tuple[int, Optional[str]], float] = {}
    effective_marks_map: List[Dict[str, Any]] = []

    # Detect OR groups visually and canonicalize with strict locality rules.
    visual_or_map = _detect_visual_or_groups(lines, anchors)
    canonical_or_map = _canonicalize_or_group_ids(questions, visual_or_map)
    for q in questions:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        q["or_group_id"] = canonical_or_map.get(qn)

    # 1) Right-margin assignment (question and subpart anchors).
    for anchor in sorted(anchors, key=lambda a: (a["page_index"], a["y_mid"])):
        page = int(anchor["page_index"])
        y = float(anchor["y_mid"])
        nearby = [
            c
            for c in margin_candidates
            if (not c["used"]) and int(c["page_index"]) == page
        ]
        if not nearby:
            continue
        nearest = min(nearby, key=lambda c: abs(float(c["y_mid"]) - y))
        y_threshold = 45.0
        if abs(float(nearest["y_mid"]) - y) > y_threshold:
            continue

        nearest["used"] = True
        qn = int(anchor["question_number"])
        sub = _norm_sub_label(anchor.get("sub_label"))
        mark_val = max(0.0, _to_float(nearest["mark"], 0.0))
        if sub:
            visual_sub_marks[_key(qn, sub)] = mark_val
            sub_mark_source[_key(qn, sub)] = "margin"
            sub_mark_confidence[_key(qn, sub)] = round(_to_float(nearest["confidence"], 0.0), 4)
        else:
            visual_question_marks[qn] = max(visual_question_marks.get(qn, 0.0), mark_val)
            question_mark_source[qn] = "margin"
            question_mark_confidence[qn] = round(_to_float(nearest["confidence"], 0.0), 4)

        evidence = _evidence(page, nearest["bbox"], nearest["confidence"])
        effective_marks_map.append(
            {
                "question_number": qn,
                "sub_label": sub,
                "marks": round(mark_val, 4),
                "evidence": evidence,
                "source": "margin",
            }
        )
        logger.info(
            "MARK_EVIDENCE_DETECTED q=%s sub=%s marks=%s source=margin page=%s",
            qn,
            sub or "-",
            round(mark_val, 4),
            page + 1,
        )

    # 2) Section math fallback.
    # CASE A: N x M means N parent questions each get M marks (no synthetic subparts).
    # CASE B: 1 x 12 means one parent question gets 12 marks.
    q_meta: List[Dict[str, Any]] = []
    for q in questions:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        section = str(q.get("section") or "").strip().lower()
        ev_rows = [ev for ev in (q.get("image_evidence") or []) if isinstance(ev, dict)]
        page_idx = min((_to_int(ev.get("page_index"), 10**9) for ev in ev_rows), default=10**9)
        q_meta.append({"qn": qn, "section": section, "page": page_idx})
    q_meta.sort(key=lambda row: (row["page"], row["qn"]))

    section_order: Dict[str, List[int]] = defaultdict(list)
    for row in q_meta:
        section_order[str(row["section"])].append(int(row["qn"]))
    section_cursor: Dict[str, int] = defaultdict(int)

    def _infer_section_for_expr(page: int) -> str:
        for row in q_meta:
            if int(row["page"]) >= page and str(row["section"]):
                return str(row["section"])
        for row in reversed(q_meta):
            if str(row["section"]):
                return str(row["section"])
        return ""

    for expr in section_exprs:
        count = max(0, _to_int(expr.get("question_count", expr.get("count")), 0))
        each = max(0.0, _to_float(expr.get("per_question_marks", expr.get("each")), 0.0))
        if count <= 0 or each <= 0:
            continue
        page = int(expr.get("page_index") or 0)
        section_key = _infer_section_for_expr(page)
        targets = list(section_order.get(section_key) or [])
        if not targets:
            continue

        assigned = 0
        cursor = int(section_cursor.get(section_key, 0))
        idx = cursor
        while idx < len(targets) and assigned < count:
            qn = int(targets[idx])
            idx += 1
            if qn in visual_question_marks:
                continue
            visual_question_marks[qn] = each
            question_mark_source[qn] = "section_math"
            question_mark_confidence[qn] = round(min(1.0, _to_float(expr.get("confidence"), 0.0)), 4)
            effective_marks_map.append(
                {
                    "question_number": qn,
                    "sub_label": None,
                    "marks": round(each, 4),
                    "evidence": _evidence(
                        int(expr.get("page_index", 0)),
                        list(expr.get("bbox") or [0, 0, 0, 0]),
                        _to_float(expr.get("confidence"), 0.0),
                    ),
                    "source": "section_math",
                }
            )
            assigned += 1

        section_cursor[section_key] = idx

    # 2b) Instruction-mark fallback (explicit "X marks").
    for q in questions:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0 or qn in visual_question_marks:
            continue
        instr_mark = _extract_instruction_mark(q.get("instruction"), q.get("question_text"))
        if instr_mark is None:
            continue
        visual_question_marks[qn] = instr_mark
        question_mark_source[qn] = "instruction"
        question_mark_confidence[qn] = 0.7
        ev_rows = [ev for ev in (q.get("image_evidence") or []) if isinstance(ev, dict)]
        primary_ev = ev_rows[0] if ev_rows else {"page_index": 0, "bbox": [0, 0, 0, 0], "visual_confidence": 0.0}
        effective_marks_map.append(
            {
                "question_number": qn,
                "sub_label": None,
                "marks": round(instr_mark, 4),
                "evidence": _evidence(
                    _to_int(primary_ev.get("page_index"), 0),
                    list(primary_ev.get("bbox") or [0, 0, 0, 0]),
                    _to_float(primary_ev.get("visual_confidence"), 0.0),
                ),
                "source": "instruction",
            }
        )

    # 3) OR propagation from visual marks only (share detected branch marks).
    groups: Dict[str, List[int]] = defaultdict(list)
    for q in questions:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        gid = str(q.get("or_group_id") or "").strip()
        if gid:
            groups[gid].append(qn)
    for gid, members in groups.items():
        marked = [qn for qn in members if qn in visual_question_marks]
        if len(members) <= 1 or not marked:
            continue
        representative = max(
            marked,
            key=lambda qn: (
                _to_float(visual_question_marks.get(qn), 0.0),
                _to_float(question_mark_confidence.get(qn), 0.0),
            ),
        )
        shared = _to_float(visual_question_marks.get(representative), 0.0)
        shared_conf = _to_float(question_mark_confidence.get(representative), 0.0)
        shared_source = str(question_mark_source.get(representative) or "inferred")
        for qn in members:
            if qn in visual_question_marks:
                continue
            visual_question_marks[qn] = shared
            question_mark_source[qn] = shared_source if shared_source in {"margin", "section_math", "instruction"} else "inferred"
            question_mark_confidence[qn] = round(shared_conf, 4)
            effective_marks_map.append(
                {
                    "question_number": qn,
                    "sub_label": None,
                    "marks": round(shared, 4),
                    "evidence": [0, [0, 0, 0, 0], 0.0],
                    "source": "inferred",
                }
            )
        logger.info("OR_MARK_SHARED group=%s members=%s marks=%s", gid, sorted(members), round(shared, 4))

    # Build resolved structure: AI base + visual overrides.
    resolved_questions: List[Dict[str, Any]] = []
    resolved_q_marks: Dict[int, float] = {}
    override_questions: set[int] = set()
    override_subparts: set[Tuple[int, Optional[str]]] = set()

    for q in questions:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        q_out = dict(q)
        base_q_mark = _to_float(ai_question_marks.get(qn), _to_float(q.get("marks"), 0.0))
        final_q_mark = base_q_mark
        if qn in visual_question_marks:
            final_q_mark = _to_float(visual_question_marks.get(qn), base_q_mark)
            override_questions.add(qn)
            logger.info(
                "MARK_OVERRIDE_APPLIED q=%s sub=- ai=%s visual=%s",
                qn,
                round(base_q_mark, 4),
                round(final_q_mark, 4),
            )
        q_out["marks"] = round(max(0.0, final_q_mark), 4)
        if qn in visual_question_marks:
            q_out["mark_source"] = question_mark_source.get(qn, "inferred")
            q_out["mark_confidence"] = round(question_mark_confidence.get(qn, 0.0), 4)
        else:
            q_out["mark_source"] = "inferred"
            q_out["mark_confidence"] = round(_to_float(q.get("ai_confidence"), 0.0), 4)
        q_out["confidence"] = round(_to_float(q.get("ai_confidence"), _to_float(q.get("confidence"), 0.0)), 4)

        sub_rows = []
        for sq in (q_out.get("subquestions") or []):
            sq_out = dict(sq)
            sub_label = _norm_sub_label(sq.get("label"))
            sq_source_hint = str(sq.get("mark_source") or "inferred").strip().lower()
            base_sq_mark = _to_float(ai_sub_marks.get(_key(qn, sub_label)), _to_float(sq.get("marks"), 0.0))
            final_sq_mark = base_sq_mark
            sq_key = _key(qn, sub_label)
            if sq_key in visual_sub_marks:
                final_sq_mark = _to_float(visual_sub_marks.get(sq_key), base_sq_mark)
                override_subparts.add(sq_key)
                logger.info(
                    "MARK_OVERRIDE_APPLIED q=%s sub=%s ai=%s visual=%s",
                    qn,
                    sub_label or "-",
                    round(base_sq_mark, 4),
                    round(final_sq_mark, 4),
                )
            elif sq_source_hint not in {"margin", "section_math", "instruction"}:
                # Guardrail: inferred subpart marks must not auto-split parent marks.
                final_sq_mark = 0.0
            sq_out["marks"] = round(max(0.0, final_sq_mark), 4)
            if sq_key in visual_sub_marks:
                sq_out["mark_source"] = sub_mark_source.get(sq_key, "inferred")
                sq_out["mark_confidence"] = round(sub_mark_confidence.get(sq_key, 0.0), 4)
            else:
                sq_out["mark_source"] = sq_source_hint if sq_source_hint in {"margin", "section_math", "instruction"} else "inferred"
                sq_out["mark_confidence"] = round(_to_float(sq.get("mark_confidence"), 0.0), 4)
            sq_out["confidence"] = round(_to_float(sq.get("confidence"), 0.0), 4)
            sub_rows.append(sq_out)

        sub_sum = sum(_to_float(sq.get("marks"), 0.0) for sq in sub_rows)
        authoritative_sub_sum = sum(
            _to_float(sq.get("marks"), 0.0)
            for sq in sub_rows
            if str(sq.get("mark_source") or "inferred").strip().lower() in {"margin", "section_math", "instruction"}
        )
        q_mark = _to_float(q_out.get("marks"), 0.0)

        # Parent mark may be raised only by explicit subpart mark evidence.
        if authoritative_sub_sum > q_mark + 1e-6:
            q_out["marks"] = round(authoritative_sub_sum, 4)
            visual_question_marks[qn] = round(authoritative_sub_sum, 4)
            question_mark_source[qn] = question_mark_source.get(qn, "inferred")
            question_mark_confidence[qn] = max(
                question_mark_confidence.get(qn, 0.0),
                max(
                    (
                        sub_mark_confidence.get(_key(qn, _norm_sub_label(sq.get("label"))), 0.0)
                        for sq in sub_rows
                    ),
                    default=0.0,
                ),
            )
            if qn not in override_questions:
                override_questions.add(qn)
            logger.info(
                "MARK_OVERRIDE_APPLIED q=%s sub=- ai=%s visual=%s reason=subpart_sum",
                qn,
                round(base_q_mark, 4),
                round(authoritative_sub_sum, 4),
            )
            q_mark = _to_float(q_out.get("marks"), 0.0)

        q_out["subquestions"] = sub_rows
        resolved_questions.append(q_out)
        resolved_q_marks[qn] = _to_float(q_out.get("marks"), 0.0)

    resolved_structure = {
        "questions": sorted(resolved_questions, key=lambda r: _to_int(r.get("number"), 0)),
        "section_math_blocks": section_exprs,
        "total_questions": len(resolved_questions),
        "total_marks": round(_compute_effective_total(resolved_q_marks, resolved_questions), 4),
        "effective_total_marks": round(_compute_effective_total(resolved_q_marks, resolved_questions), 4),
        "numbering_contiguous": bool(question_structure.get("numbering_contiguous", False)),
    }

    # Compare only overridden question marks against AI hints.
    ai_visual_mismatches: List[Dict[str, Any]] = []
    for qn in sorted(override_questions):
        ai_mark = round(_to_float(ai_question_marks.get(qn), 0.0), 4)
        visual_mark = round(_to_float(visual_question_marks.get(qn), 0.0), 4)
        if abs(ai_mark - visual_mark) > 1e-6:
            ai_visual_mismatches.append(
                {
                    "question_number": qn,
                    "ai_marks": ai_mark,
                    "visual_marks": visual_mark,
                }
            )

    header_total_confidence = round(min(1.0, max(0.0, header_score) / 3.5), 4)
    header_total_reliable = bool(
        header_total is not None
        and (
            header_source in {"header_maximum", "header_mm"}
            or (header_source == "header_total" and header_total_confidence >= 0.9)
        )
    )

    visual_mark_map: Dict[str, float] = {}
    for qn in sorted(override_questions):
        visual_mark_map[f"{qn}:"] = round(_to_float(visual_question_marks.get(qn), 0.0), 4)
    for qn, sub in sorted(override_subparts, key=lambda item: (item[0], item[1] or "")):
        visual_mark_map[f"{qn}:{sub or ''}"] = round(_to_float(visual_sub_marks.get(_key(qn, sub), 0.0), 0.0), 4)

    override_q_ratio = round(
        (len(override_questions) / float(len(question_numbers))) if question_numbers else 0.0,
        4,
    )

    return {
        "resolved_structure": resolved_structure,
        "header_total_marks": round(_to_float(header_total, 0.0), 4) if header_total is not None else None,
        "header_evidence": header_evidence,
        "header_total_confidence": header_total_confidence,
        "header_total_source": header_source,
        "header_total_reliable": header_total_reliable,
        "section_math_expressions": section_exprs,
        "effective_marks_map": effective_marks_map,
        "ai_visual_mismatches": ai_visual_mismatches,
        "visual_mark_map": visual_mark_map,
        "mark_override_coverage": override_q_ratio,
    }


__all__ = ["resolve_visual_marks"]
