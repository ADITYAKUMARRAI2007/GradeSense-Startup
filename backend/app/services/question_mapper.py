"""Question/subquestion detection and deterministic segment-first mapping."""

import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


ANCHOR_LEFT_RATIO = float(os.getenv("ANCHOR_LEFT_RATIO", "0.38"))
MAPPING_COVERAGE_MIN = float(os.getenv("MAPPING_COVERAGE_MIN", "0.85"))
SPARSE_WORD_THRESHOLD = int(os.getenv("SPARSE_WORD_THRESHOLD", os.getenv("OCR_MIN_WORDS", "20")))
SUBLABEL_DETECT_ENABLED = _env_bool("SUBLABEL_DETECT_ENABLED", True)
TABLE_STICKY_ENABLED = _env_bool("TABLE_STICKY_ENABLED", True)
WORKING_NOTE_STICKY_ENABLED = _env_bool("WORKING_NOTE_STICKY_ENABLED", True)
SEMANTIC_REPAIR_SIM_MIN = float(os.getenv("SEMANTIC_REPAIR_SIM_MIN", "0.78"))
SEMANTIC_OVERRIDE_ANCHOR = _env_bool("SEMANTIC_OVERRIDE_ANCHOR", False)
SPARSE_ALLOW_ANCHOR = _env_bool("SPARSE_ALLOW_ANCHOR", True)

LABEL_PATTERNS = [
    re.compile(r"^\s*Q\.?\s*0*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"^\s*0*(\d{1,3})\s*[\).:]\s*"),
    re.compile(r"^\s*0*(\d{1,3})\b"),
]
SUB_PATTERNS = [
    re.compile(r"^\s*[\(\[]\s*([a-z])\s*[\)\]]", re.IGNORECASE),
    re.compile(r"^\s*([a-z])[\).]\s*", re.IGNORECASE),
    re.compile(r"^\s*[\(\[]\s*(i{1,4}|v|vi{0,3}|ix|x)\s*[\)\]]", re.IGNORECASE),
    re.compile(r"^\s*(i{1,4}|v|vi{0,3}|ix|x)[\).]\s*", re.IGNORECASE),
]

SEGMENT_LABEL_PATTERN = re.compile(
    r"^\s*(?:q\.?\s*\d{1,3}\b|\d{1,3}(?:[\).:]|\b)|[a-z](?:[\).:]|\b)|i{1,5}(?:[\).:]|\b))",
    re.IGNORECASE,
)
WORKING_NOTE_PATTERN = re.compile(r"\b(?:working\s*note|wn|note|calculation)\b", re.IGNORECASE)
ALNUM_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
TABLE_HINTS = (
    "journal",
    "ledger",
    "particulars",
    "debit",
    "credit",
    "dr",
    "cr",
    "balance",
    "account",
    "amount",
)


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for v in values:
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _normalize_sub_id(raw: str) -> str:
    s = _normalize_spaces(raw).lower()
    s = re.sub(r"^[\(\)\[\]\s\.\-]+|[\(\)\[\]\s\.\-]+$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def detect_subquestion_id(text: str) -> Optional[str]:
    t = _normalize_spaces(text).lower()
    for pat in SUB_PATTERNS:
        m = pat.match(t)
        if m:
            normalized = _normalize_sub_id(m.group(1))
            if normalized:
                return normalized
    return None


def _token_count(text: str) -> int:
    return len(ALNUM_TOKEN_PATTERN.findall(text or ""))


def _segment_has_label(text: str) -> bool:
    return bool(SEGMENT_LABEL_PATTERN.match(_normalize_spaces(text)))


def _bbox(seg: Dict[str, Any]) -> Tuple[float, float, float, float]:
    return (
        float(seg.get("x1", 0.0)),
        float(seg.get("y1", 0.0)),
        float(seg.get("x2", 0.0)),
        float(seg.get("y2", 0.0)),
    )


def _merge_bbox(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    return (
        min(a[0], b[0]),
        min(a[1], b[1]),
        max(a[2], b[2]),
        max(a[3], b[3]),
    )


def _bbox_center(box: Tuple[float, float, float, float]) -> Tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _vertical_overlaps(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    return not (a[3] < b[1] or a[1] > b[3])


def _nearest_previous_question(
    seg: Dict[str, Any],
    page_num: int,
    question_history: List[Dict[str, Any]],
) -> Optional[int]:
    if not question_history:
        return None
    sbox = _bbox(seg)
    scx, scy = _bbox_center(sbox)
    best_q = None
    best_score = None
    for item in question_history:
        if int(item.get("page", 0)) > page_num:
            continue
        qbox = item.get("bbox")
        if not qbox:
            continue
        qcx, qcy = _bbox_center(qbox)
        page_gap = max(0, page_num - int(item.get("page", 0)))
        score = (page_gap * 2400.0) + abs(scx - qcx) + abs(scy - qcy)
        if best_score is None or score < best_score:
            best_score = score
            best_q = int(item["question_number"])
    return best_q


def _is_table_segment(seg: Dict[str, Any], seg_text: str) -> bool:
    if not TABLE_STICKY_ENABLED:
        return False
    if seg.get("tables"):
        return True
    text = (seg_text or "").lower()
    if not text:
        return False
    hint_hits = sum(1 for hint in TABLE_HINTS if hint in text)
    num_count = len(re.findall(r"\b\d+(?:[\.,]\d+)?\b", text))
    dr_cr_like = bool(re.search(r"\bdr\b|\bcr\b", text))
    return hint_hits >= 2 or (hint_hits >= 1 and num_count >= 4 and dr_cr_like)


def _is_working_note_segment(seg_text: str) -> bool:
    if not WORKING_NOTE_STICKY_ENABLED:
        return False
    return bool(WORKING_NOTE_PATTERN.search(seg_text or ""))


def _token_set(text: str) -> Set[str]:
    return {t.lower() for t in ALNUM_TOKEN_PATTERN.findall(text or "") if len(t) > 1}


def _jaccard_similarity(a: str, b: str) -> float:
    sa = _token_set(a)
    sb = _token_set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return inter / union


def normalize_question_number(raw: str, expected_qs: Set[int], page_num: int = 0) -> Optional[int]:
    t = _normalize_spaces(raw)
    if not t:
        return None
    low = t.lower()
    if "space for writing" in low or "question number" in low:
        return None
    if t.isdigit() and int(t) == page_num and len(t) <= 2:
        return None
    # Range labels like Q1-7 / 1-7 are section headers, not a single question anchor.
    if re.match(r"^\s*q\.?\s*\d{1,3}\s*[-–]\s*\d{1,3}\b", t, re.IGNORECASE):
        return None
    if re.match(r"^\s*\d{1,3}\s*[-–]\s*\d{1,3}\b", t, re.IGNORECASE):
        return None

    for pat in LABEL_PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        token = m.group(1)
        try:
            n = int(token)
        except Exception:
            continue
        if n in expected_qs:
            return n
        if len(token) == 3 and token.startswith("0"):
            n2 = int(token[-2:])
            if n2 in expected_qs:
                return n2
        if len(token) == 3 and token.startswith("9"):
            n3 = int(token[-2:])
            if n3 in expected_qs:
                return n3
    return None


def detect_margin_labels(
    words: List[Dict[str, Any]],
    expected_qs: Set[int],
    width: float,
    page_num: int,
    left_ratio: float = ANCHOR_LEFT_RATIO,
    right_ratio: float = 0.75,
) -> List[Dict[str, Any]]:
    labels: List[Dict[str, Any]] = []
    for w in words or []:
        text = str(w.get("text", "")).strip()
        if not text:
            continue
        x1 = float(w.get("x1", 0.0))
        x2 = float(w.get("x2", 0.0))
        in_left = x1 <= width * left_ratio
        in_right = x2 >= width * right_ratio
        if not (in_left or in_right):
            continue
        q_num = normalize_question_number(text, expected_qs=expected_qs, page_num=page_num)
        if q_num is None:
            continue
        labels.append(
            {
                "question_number": q_num,
                "y": float(w.get("y1", 0.0)),
                "x1": x1,
                "x2": x2,
                "text": text,
                "page": page_num,
            }
        )
    labels.sort(key=lambda l: (l["y"], l["x1"]))

    deduped: List[Dict[str, Any]] = []
    for lb in labels:
        if deduped:
            prev = deduped[-1]
            if (
                int(prev["question_number"]) == int(lb["question_number"])
                and int(prev["page"]) == int(lb["page"])
                and abs(float(prev["y"]) - float(lb["y"])) <= 10.0
            ):
                continue
        deduped.append(lb)
    return deduped


def _new_packet(question_number: int) -> Dict[str, Any]:
    return {
        "question_number": int(question_number),
        "segments": [],
        "subquestions": {},
        "subanswers": [],
        "page_refs": set(),
        "tables": [],
        "table_segments": [],
        "working_note_segments": [],
        "segment_ids": [],
        "mapping_trace": [],
        "mapping_confidence": 0.0,
        "start_anchor": None,
        "end_anchor": None,
        "_stats": {
            "anchors": 0,
            "sparse_assignments": 0,
            "semantic_repairs": 0,
            "sticky_table_assignments": 0,
            "working_note_assignments": 0,
        },
    }


def _append_trace(entry: Dict[str, Any], trace: str) -> None:
    traces = entry.setdefault("mapping_trace", [])
    if trace not in traces:
        traces.append(trace)


def _compute_mapping_confidence(entry: Dict[str, Any]) -> float:
    stats = entry.get("_stats", {})
    score = 0.45
    if stats.get("anchors", 0) > 0:
        score += 0.24
    if len(entry.get("page_refs") or []) > 1:
        score += 0.08
    if entry.get("table_segments"):
        score += 0.05
    if entry.get("working_note_segments"):
        score += 0.04
    score -= min(0.18, 0.04 * int(stats.get("sparse_assignments", 0)))
    score -= min(0.22, 0.06 * int(stats.get("semantic_repairs", 0)))
    return max(0.0, min(0.99, score))


def _build_subanswer_packets(entry: Dict[str, Any]) -> None:
    segments = entry.get("segments") or []
    if not segments:
        entry["subanswers"] = []
        entry["subquestions"] = {}
        entry["subquestion_count"] = 0
        return

    sub_map: Dict[str, List[Dict[str, Any]]] = {}
    sub_order: List[str] = []
    preamble: List[Dict[str, Any]] = []
    current_sub: Optional[str] = None

    for seg in segments:
        seg_text = str(seg.get("text", "")).strip()
        is_table = bool(seg.get("_is_table_segment"))
        is_working_note = bool(seg.get("_is_working_note"))
        detected_sub = None
        if SUBLABEL_DETECT_ENABLED and not is_table and not is_working_note:
            detected_sub = detect_subquestion_id(seg_text)
        if detected_sub:
            if detected_sub not in sub_map:
                sub_map[detected_sub] = []
                sub_order.append(detected_sub)
            if preamble and len(sub_map[detected_sub]) == 0:
                sub_map[detected_sub].extend(preamble)
                preamble = []
            current_sub = detected_sub
        if current_sub:
            sub_map.setdefault(current_sub, []).append(seg)
        else:
            preamble.append(seg)

    if preamble and sub_order:
        first_sub = sub_order[0]
        sub_map[first_sub] = preamble + sub_map.get(first_sub, [])

    subanswers: List[Dict[str, Any]] = []
    if not sub_order:
        subanswers.append(
            {
                "sub_id": "__full__",
                "segment_ids": [str(s.get("segment_id")) for s in segments if s.get("segment_id")],
                "combined_text": " ".join(str(s.get("text", "")).strip() for s in segments).strip()[:8000],
                "page_refs": sorted({int(s.get("page", 1) or 1) for s in segments}),
                "mapping_confidence": entry.get("mapping_confidence", 0.0),
            }
        )
        entry["subquestions"] = {}
        entry["subanswers"] = subanswers
        entry["subquestion_count"] = 0
        return

    for sub_id in sub_order:
        segs = sub_map.get(sub_id) or []
        seg_ids = [str(s.get("segment_id")) for s in segs if s.get("segment_id")]
        combined = " ".join(str(s.get("text", "")).strip() for s in segs).strip()
        pages = sorted({int(s.get("page", 1) or 1) for s in segs})
        conf = min(0.99, max(0.35, entry.get("mapping_confidence", 0.0) + (0.03 if segs else -0.08)))
        subanswers.append(
            {
                "sub_id": sub_id,
                "segment_ids": seg_ids,
                "combined_text": combined[:8000],
                "page_refs": pages,
                "mapping_confidence": conf,
            }
        )

    entry["subquestions"] = {s["sub_id"]: sub_map.get(s["sub_id"], []) for s in subanswers}
    entry["subanswers"] = subanswers
    entry["subquestion_count"] = len(subanswers)


def map_segments_to_questions(
    segments_by_page: List[List[Dict[str, Any]]],
    words_by_page: List[List[Dict[str, Any]]],
    expected_questions: List[int],
    page_widths: List[float],
) -> Dict[int, Dict[str, Any]]:
    sparse_word_threshold = int(os.getenv("SPARSE_WORD_THRESHOLD", str(SPARSE_WORD_THRESHOLD)))
    mapping_coverage_min = float(os.getenv("MAPPING_COVERAGE_MIN", str(MAPPING_COVERAGE_MIN)))
    semantic_repair_sim_min = float(os.getenv("SEMANTIC_REPAIR_SIM_MIN", str(SEMANTIC_REPAIR_SIM_MIN)))
    semantic_override_anchor = _env_bool("SEMANTIC_OVERRIDE_ANCHOR", SEMANTIC_OVERRIDE_ANCHOR)
    sparse_allow_anchor = _env_bool("SPARSE_ALLOW_ANCHOR", SPARSE_ALLOW_ANCHOR)
    expected_qs = set(expected_questions)
    mapped: Dict[int, Dict[str, Any]] = {}
    per_page_metrics: List[Dict[str, Any]] = []
    question_history: List[Dict[str, Any]] = []
    segment_meta: Dict[str, Dict[str, Any]] = {}
    anchor_by_segment_id: Dict[str, Dict[str, Any]] = {}
    anchors_by_page: Dict[int, List[Dict[str, Any]]] = {}
    total_segments = 0
    assigned_segment_ids: Set[str] = set()
    unassigned_segments: List[Dict[str, Any]] = []

    for page_idx, segments in enumerate(segments_by_page):
        page_num = page_idx + 1
        width = page_widths[page_idx] if page_idx < len(page_widths) else 1000.0
        page_words_raw = words_by_page[page_idx] if page_idx < len(words_by_page) else []
        page_words = len(page_words_raw)
        sparse_page = page_words < sparse_word_threshold

        page_margin_labels = detect_margin_labels(
            words=page_words_raw,
            expected_qs=expected_qs,
            width=width,
            page_num=page_num,
            left_ratio=ANCHOR_LEFT_RATIO,
            right_ratio=1.0,
        )
        sorted_segments = sorted(segments, key=lambda s: (float(s.get("y1", 0.0)), float(s.get("x1", 0.0))))

        labels_detected = 0
        for seg in sorted_segments:
            seg_id = str(seg.get("segment_id") or f"P{page_num}-S{len(segment_meta) + 1}")
            seg_text = str(seg.get("text", "")).strip()
            if not seg_text:
                continue
            total_segments += 1

            seg_box = _bbox(seg)
            seg_h = max(1.0, seg_box[3] - seg_box[1])
            token_count = _token_count(seg_text)
            in_left_margin = float(seg.get("x1", 0.0)) <= width * ANCHOR_LEFT_RATIO
            has_label = _segment_has_label(seg_text)
            if in_left_margin and has_label:
                labels_detected += 1
            overlapping_page_labels = [
                lb
                for lb in page_margin_labels
                if (seg_box[1] - max(10.0, seg_h * 0.8)) <= float(lb.get("y", 0.0)) <= (seg_box[3] + max(10.0, seg_h * 0.8))
            ]
            margin_q = int(overlapping_page_labels[0]["question_number"]) if overlapping_page_labels else None
            detected_q = margin_q
            if detected_q is None:
                detected_q = normalize_question_number(seg_text, expected_qs=expected_qs, page_num=page_num)
            is_table = _is_table_segment(seg, seg_text)
            is_working_note = _is_working_note_segment(seg_text)
            # Anchoring must prioritize explicit margin-number evidence.
            # In practice, OCR often yields short labels ("1.", "Q2") or table-like lines
            # near the margin; treating those as non-anchors causes severe under-mapping.
            has_margin_anchor = margin_q is not None
            has_segment_anchor = in_left_margin and has_label and token_count >= 1
            strong_anchor = (
                (not sparse_page or sparse_allow_anchor)
                and (has_margin_anchor or has_segment_anchor)
                and detected_q in expected_qs
                and not is_working_note
            )

            seg["_is_table_segment"] = is_table
            seg["_is_working_note"] = is_working_note

            segment_meta[seg_id] = {
                "segment_id": seg_id,
                "page": page_num,
                "bbox": seg_box,
                "token_count": token_count,
                "in_left_margin": in_left_margin,
                "has_label": has_label,
                "sparse_page": sparse_page,
                "is_table": is_table,
                "is_working_note": is_working_note,
                "strong_anchor": strong_anchor,
                "detected_q": detected_q if detected_q in expected_qs else None,
                "text": seg_text,
                "seg": seg,
            }
            if strong_anchor and detected_q is not None:
                anchors_by_page.setdefault(page_num, []).append(
                    {
                        "question_number": int(detected_q),
                        "segment_id": seg_id,
                        "page": page_num,
                        "y": float(seg.get("y1", 0.0)),
                        "bbox": seg_box,
                        "raw": seg_text[:80],
                    }
                )

        anchors = sorted(anchors_by_page.get(page_num, []), key=lambda a: (float(a["y"]), str(a["segment_id"])))
        deduped_anchors: List[Dict[str, Any]] = []
        for anchor in anchors:
            if deduped_anchors:
                prev = deduped_anchors[-1]
                if (
                    int(prev["question_number"]) == int(anchor["question_number"])
                    and abs(float(prev["y"]) - float(anchor["y"])) <= 10.0
                ):
                    continue
            deduped_anchors.append(anchor)
        anchors_by_page[page_num] = deduped_anchors
        for anchor in deduped_anchors:
            anchor_by_segment_id[anchor["segment_id"]] = anchor

        per_page_metrics.append(
            {
                "page": page_num,
                "segments": len(sorted_segments),
                "labels_detected": labels_detected,
                "anchors_detected": len(deduped_anchors),
                "questions_assigned": [],
                "questions_assigned_count": 0,
                "sparse": sparse_page,
                "word_count": page_words,
            }
        )

    active_q: Optional[int] = None
    question_bbox: Dict[int, Tuple[float, float, float, float]] = {}
    per_page_assigned: Dict[int, Set[int]] = {}
    first_page_for_q: Dict[int, int] = {}

    for page_idx, segments in enumerate(segments_by_page):
        page_num = page_idx + 1
        sorted_segments = sorted(segments, key=lambda s: (float(s.get("y1", 0.0)), float(s.get("x1", 0.0))))
        page_has_anchor = bool(anchors_by_page.get(page_num))
        page_sparse = False
        if sorted_segments:
            first_seg_id = str(sorted_segments[0].get("segment_id") or "")
            if first_seg_id in segment_meta:
                page_sparse = bool(segment_meta[first_seg_id].get("sparse_page", False))
        page_active_q: Optional[int] = active_q if (not page_has_anchor and not page_sparse) else None

        for seg in sorted_segments:
            seg_id = str(seg.get("segment_id") or "")
            if not seg_id or seg_id not in segment_meta:
                continue
            meta = segment_meta[seg_id]
            if not str(seg.get("text", "")).strip():
                continue

            anchor = anchor_by_segment_id.get(seg_id)
            chosen_q: Optional[int] = None

            if anchor:
                chosen_q = int(anchor["question_number"])
                page_active_q = chosen_q
                active_q = chosen_q
            else:
                if page_active_q is not None and page_active_q in expected_qs:
                    chosen_q = page_active_q
                elif meta["sparse_page"]:
                    chosen_q = _nearest_previous_question(seg, page_num, question_history)
                    if chosen_q in expected_qs:
                        page_active_q = chosen_q
                        _append_trace(mapped.setdefault(chosen_q, _new_packet(chosen_q)), "sparse_attach")
                        mapped[chosen_q]["_stats"]["sparse_assignments"] += 1
                elif meta["is_working_note"]:
                    chosen_q = active_q or _nearest_previous_question(seg, page_num, question_history)
                    if chosen_q in expected_qs:
                        page_active_q = chosen_q
                        _append_trace(mapped.setdefault(chosen_q, _new_packet(chosen_q)), "working_note_attach")
                        mapped[chosen_q]["_stats"]["working_note_assignments"] += 1
                elif meta["is_table"]:
                    chosen_q = active_q or _nearest_previous_question(seg, page_num, question_history)
                    if chosen_q in expected_qs:
                        page_active_q = chosen_q
                        _append_trace(mapped.setdefault(chosen_q, _new_packet(chosen_q)), "table_sticky")
                        mapped[chosen_q]["_stats"]["sticky_table_assignments"] += 1
                elif not page_has_anchor and active_q in expected_qs:
                    chosen_q = active_q
                    page_active_q = chosen_q
                    _append_trace(mapped.setdefault(chosen_q, _new_packet(chosen_q)), "cross_page_merge")
                else:
                    # Conservative continuation only when vertically overlapping last active question bbox.
                    if active_q in question_bbox:
                        candidate_box = question_bbox[active_q]
                        if _vertical_overlaps(meta["bbox"], candidate_box):
                            chosen_q = active_q
                            page_active_q = chosen_q

            if chosen_q is None or chosen_q not in expected_qs:
                unassigned_segments.append(meta)
                continue

            entry = mapped.setdefault(chosen_q, _new_packet(chosen_q))
            entry["segments"].append(seg)
            entry["page_refs"].add(int(seg.get("page", page_num) or page_num))
            if meta["is_table"]:
                entry["table_segments"].append(seg_id)
            if meta["is_working_note"]:
                entry["working_note_segments"].append(seg_id)
            for t in seg.get("tables", []) or []:
                entry["tables"].append(t)

            if anchor:
                entry["_stats"]["anchors"] += 1
                _append_trace(entry, "anchor_match")
                anchor_payload = {
                    "page": page_num,
                    "y": float(seg.get("y1", 0.0)),
                    "raw": str(seg.get("text", "")).strip()[:80],
                    "segment_id": seg_id,
                }
                if not entry.get("start_anchor"):
                    entry["start_anchor"] = anchor_payload
                entry["end_anchor"] = anchor_payload
            if chosen_q not in first_page_for_q:
                first_page_for_q[chosen_q] = page_num
            elif first_page_for_q.get(chosen_q) != page_num:
                _append_trace(entry, "cross_page_merge")

            box = meta["bbox"]
            if chosen_q in question_bbox:
                question_bbox[chosen_q] = _merge_bbox(question_bbox[chosen_q], box)
            else:
                question_bbox[chosen_q] = box
            question_history.append({"question_number": chosen_q, "bbox": box, "page": page_num})

            assigned_segment_ids.add(seg_id)
            per_page_assigned.setdefault(page_num, set()).add(chosen_q)
            active_q = chosen_q

    if unassigned_segments:
        for meta in unassigned_segments:
            seg = meta["seg"]
            seg_text = meta["text"]
            if (
                not semantic_override_anchor
                and meta["in_left_margin"]
                and meta["has_label"]
                and meta["token_count"] >= 3
            ):
                continue
            best_q = None
            best_score = 0.0
            for qn, entry in mapped.items():
                if not isinstance(qn, int):
                    continue
                candidate_text = entry.get("combined_text", "") or " ".join(
                    str(s.get("text", "")).strip() for s in (entry.get("segments") or [])
                )
                sim = _jaccard_similarity(seg_text, candidate_text)
                if sim < semantic_repair_sim_min:
                    continue
                q_pages = entry.get("page_refs") or []
                page_gap = 0 if meta["page"] in q_pages else min(abs(meta["page"] - p) for p in q_pages) if q_pages else 4
                proximity = max(0.0, 1.0 - (page_gap / 4.0))
                score = (sim * 0.8) + (proximity * 0.2)
                if score > best_score:
                    best_score = score
                    best_q = qn
            if best_q is None:
                continue
            entry = mapped.setdefault(best_q, _new_packet(best_q))
            entry["segments"].append(seg)
            entry["page_refs"].add(int(seg.get("page", meta["page"]) or meta["page"]))
            if meta["is_table"]:
                entry["table_segments"].append(meta["segment_id"])
            if meta["is_working_note"]:
                entry["working_note_segments"].append(meta["segment_id"])
            _append_trace(entry, "semantic_repair")
            entry["_stats"]["semantic_repairs"] += 1
            assigned_segment_ids.add(meta["segment_id"])
            per_page_assigned.setdefault(meta["page"], set()).add(best_q)

    low_confidence_questions: List[int] = []
    subpacket_count = 0
    for q_num, item in mapped.items():
        if not isinstance(q_num, int):
            continue
        item["page_refs"] = sorted({int(p) for p in (item.get("page_refs") or [])})
        item["segments"].sort(key=lambda s: (int(s.get("page", 1) or 1), float(s.get("y1", 0.0))))
        item["segment_ids"] = _dedupe_preserve_order([str(s.get("segment_id")) for s in item["segments"] if s.get("segment_id")])
        item["table_segments"] = _dedupe_preserve_order(item.get("table_segments") or [])
        item["working_note_segments"] = _dedupe_preserve_order(item.get("working_note_segments") or [])
        combined_text = " ".join(str(s.get("text", "")).strip() for s in item["segments"]).strip()
        item["combined_text"] = combined_text[:12000]
        item["extracted_text"] = item["combined_text"]
        item["mapping_trace"] = _dedupe_preserve_order(item.get("mapping_trace") or [])
        item["mapping_confidence"] = _compute_mapping_confidence(item)
        _build_subanswer_packets(item)
        subpacket_count += len(item.get("subanswers") or [])
        if item["mapping_confidence"] < 0.65:
            low_confidence_questions.append(int(q_num))
        item.pop("_stats", None)

    page_metric_index = {int(m["page"]): m for m in per_page_metrics}
    for page_num, assigned in per_page_assigned.items():
        pm = page_metric_index.get(int(page_num))
        if not pm:
            continue
        pm["questions_assigned"] = sorted(int(q) for q in assigned)
        pm["questions_assigned_count"] = len(assigned)

    mapped_count = len(assigned_segment_ids)
    mapping_coverage = (mapped_count / total_segments) if total_segments > 0 else 0.0
    consistency_flags: List[str] = []
    if mapping_coverage < mapping_coverage_min:
        consistency_flags.append("low_mapping_coverage")
    if low_confidence_questions:
        consistency_flags.append("low_confidence_packets")

    mapped["_meta"] = {
        "per_page": per_page_metrics,
        "mapping_coverage": round(mapping_coverage, 4),
        "packets_generated": len([k for k in mapped.keys() if isinstance(k, int)]),
        "subpacket_count": subpacket_count,
        "low_confidence_questions": sorted(set(low_confidence_questions)),
        "consistency_flags": consistency_flags,
    }
    return mapped
