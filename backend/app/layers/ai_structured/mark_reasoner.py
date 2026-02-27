"""Layer-3 deterministic mark reasoning + Layer-4 audit tree."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger

from .safe_numeric import parse_section_math_expression, safe_float, safe_int
from .validation import normalize_structure_payload


_EXPLICIT_SOURCES = {"margin", "section_math", "instruction"}


def _norm_source(value: Any) -> str:
    return str(value or "inferred").strip().lower()


def _norm_label(value: Any) -> Optional[str]:
    s = str(value or "").strip().lower()
    return s or None


def _parse_margin_split_text(value: Any) -> Optional[List[float]]:
    import re

    txt = str(value or "").strip()
    if not txt:
        return None
    m = re.match(
        r"^\s*[\(\[\{]?\s*(\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)+)\s*[\)\]\}]?\s*$",
        txt,
    )
    if not m:
        return None
    parts = [safe_float(p, 0.0) for p in re.split(r"\s*\+\s*", m.group(1))]
    if len(parts) < 2 or any(p <= 0 for p in parts):
        return None
    return [round(p, 4) for p in parts]


def _extract_instruction_mark(*texts: Optional[str]) -> Optional[float]:
    import re

    for raw in texts:
        txt = str(raw or "").strip().lower()
        if not txt:
            continue
        m = re.search(r"\b(?:in|for|of)?\s*(\d+(?:\.\d+)?)\s*(?:marks?|mks?)\b", txt, flags=re.IGNORECASE)
        if not m:
            continue
        mark = safe_float(m.group(1), 0.0)
        if mark > 0:
            return round(mark, 4)
    return None


def _compute_effective_total(questions: List[Dict[str, Any]]) -> float:
    grouped: Dict[str, List[float]] = defaultdict(list)
    total = 0.0
    for q in questions:
        marks = max(0.0, safe_float(q.get("marks"), 0.0))
        gid = str(q.get("or_group_id") or "").strip()
        if gid:
            grouped[gid].append(marks)
        else:
            total += marks
    for _, vals in grouped.items():
        total += max(vals) if vals else 0.0
    return round(total, 4)


def _source_confidence(source: str) -> float:
    s = _norm_source(source)
    if s == "margin":
        return 1.0
    if s == "section_math":
        return 0.92
    if s == "instruction":
        return 0.82
    return 0.62


def _redistribute_subparts_only(question: Dict[str, Any]) -> bool:
    subparts = list(question.get("subquestions") or [])
    if not subparts:
        return False
    total = max(0.0, safe_float(question.get("marks"), 0.0))
    if total <= 0:
        return False
    explicit_idxs: List[int] = []
    explicit_sum = 0.0
    for idx, sq in enumerate(subparts):
        src = _norm_source(sq.get("mark_source"))
        val = max(0.0, safe_float(sq.get("marks"), 0.0))
        if val > 0 and src in _EXPLICIT_SOURCES:
            explicit_idxs.append(idx)
            explicit_sum += val
    if explicit_sum > total:
        return False
    missing = [i for i in range(len(subparts)) if i not in explicit_idxs]
    if not missing:
        return False
    even = (total - explicit_sum) / float(len(missing)) if missing else 0.0
    for idx in missing:
        subparts[idx]["marks"] = round(even, 4)
        if _norm_source(subparts[idx].get("mark_source")) not in _EXPLICIT_SOURCES:
            subparts[idx]["mark_source"] = _norm_source(question.get("mark_source"))
    # Adjust last for rounding drift.
    if missing:
        current_sum = sum(max(0.0, safe_float(sq.get("marks"), 0.0)) for sq in subparts)
        diff = round(total - current_sum, 4)
        if abs(diff) > 1e-6:
            last = missing[-1]
            subparts[last]["marks"] = round(max(0.0, safe_float(subparts[last].get("marks"), 0.0) + diff), 4)
    question["subquestions"] = subparts
    return True


def _build_or_groups(questions: List[Dict[str, Any]], visual_entities: Optional[Dict[str, Any]]) -> Dict[str, List[int]]:
    # Merge existing OR ids with visual connectors.
    edges: List[Tuple[int, int]] = []
    ai_groups: Dict[str, List[int]] = defaultdict(list)
    for q in questions:
        qn = safe_int(q.get("number"), 0)
        gid = str(q.get("or_group_id") or "").strip()
        if qn > 0 and gid:
            ai_groups[gid].append(qn)
    for members in ai_groups.values():
        uniq = sorted(set(int(n) for n in members if int(n) > 0))
        for i in range(len(uniq) - 1):
            edges.append((uniq[i], uniq[i + 1]))

    for row in (visual_entities or {}).get("or_connectors") or []:
        if not isinstance(row, dict):
            continue
        q1 = safe_int(row.get("q1"), 0)
        q2 = safe_int(row.get("q2"), 0)
        if q1 > 0 and q2 > 0 and q1 != q2:
            edges.append((min(q1, q2), max(q1, q2)))

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
        union(int(a), int(b))

    comps: Dict[int, List[int]] = defaultdict(list)
    for node in list(parent.keys()):
        comps[find(node)].append(node)

    out: Dict[str, List[int]] = {}
    gid_seq = 1
    for _, members in sorted(comps.items(), key=lambda kv: min(kv[1])):
        uniq = sorted(set(int(n) for n in members if int(n) > 0))
        if len(uniq) < 2:
            continue
        gid = f"visual_or_{gid_seq}"
        gid_seq += 1
        out[gid] = uniq
    return out


def _resolve_section_math_blocks(structure: Dict[str, Any], visual_entities: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    # Prefer visual layer blocks.
    for row in (visual_entities or {}).get("section_math") or []:
        if not isinstance(row, dict):
            continue
        count = safe_int(row.get("count"), 0)
        per = safe_float(row.get("per"), 0.0)
        total = safe_float(row.get("total"), 0.0)
        if count <= 0 or per <= 0 or total <= 0:
            continue
        blocks.append(
            {
                "count": count,
                "per": round(per, 4),
                "total": round(total, 4),
                "page": safe_int(row.get("page"), 0),
                "range": row.get("range"),
                "expr": str(row.get("expr") or f"{count} x {per} = {total}"),
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "confidence": safe_float(row.get("confidence"), 0.0),
            }
        )

    # Fallback to structure section_math_blocks.
    if not blocks:
        for block in (structure.get("section_math_blocks") or []):
            if not isinstance(block, dict):
                continue
            parsed = parse_section_math_expression(block.get("expression"))
            if parsed:
                count, per, total = parsed
            else:
                count = safe_int(block.get("question_count"), 0)
                per = safe_float(block.get("per_question_marks"), 0.0)
                total = safe_float(block.get("total_marks"), 0.0)
            if count <= 0 or per <= 0 or total <= 0:
                continue
            range_raw = block.get("range")
            range_obj = None
            if isinstance(range_raw, dict):
                start = safe_int(range_raw.get("start"), 0)
                end = safe_int(range_raw.get("end"), 0)
                if start > 0 and end >= start:
                    range_obj = {"start": start, "end": end}
            blocks.append(
                {
                    "count": count,
                    "per": round(per, 4),
                    "total": round(total, 4),
                    "page": safe_int(block.get("page_index"), 0),
                    "range": range_obj,
                    "expr": str(block.get("expression") or f"{count} x {per} = {total}"),
                    "bbox": [0, 0, 0, 0],
                    "confidence": safe_float(block.get("confidence"), 0.0),
                }
            )
    blocks.sort(key=lambda b: (safe_int(b.get("page"), 0), str(b.get("expr") or "")))
    return blocks


def _infer_start_question_from_visual(row: Dict[str, Any], visual_entities: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(row, dict):
        return None
    page = safe_int(row.get("page"), 0)
    bbox = row.get("bbox") or [0, 0, 0, 0]
    y_after = safe_float(bbox[3] if len(bbox) >= 4 else 0.0, 0.0)
    anchors: List[Tuple[int, float, int]] = []
    for q in (visual_entities or {}).get("questions") or []:
        if not isinstance(q, dict):
            continue
        qn = safe_int(q.get("number"), 0)
        if qn <= 0:
            continue
        qpage = safe_int(q.get("page"), 0)
        qbbox = q.get("bbox") or [0, 0, 0, 0]
        qy = safe_float(qbbox[1] if len(qbbox) >= 2 else 0.0, 0.0)
        anchors.append((qpage, qy, qn))
    anchors.sort(key=lambda it: (it[0], it[1], it[2]))
    for qpage, qy, qn in anchors:
        if qpage == page and qy >= (y_after - 8.0):
            return qn
    for qpage, qy, qn in anchors:
        if qpage > page:
            return qn
    return None


def _build_section_math_rules(structure: Dict[str, Any], visual_entities: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    for row in (visual_entities or {}).get("section_math") or []:
        if not isinstance(row, dict):
            continue
        count = safe_int(row.get("count"), 0)
        per = safe_float(row.get("per"), 0.0)
        total = safe_float(row.get("total"), 0.0)
        if count <= 0 or per <= 0 or total <= 0:
            continue
        start_q = safe_int(((row.get("range") or {}).get("start")), 0)
        inferred = _infer_start_question_from_visual(row, visual_entities)
        inferred_q = safe_int(inferred, 0)
        if start_q <= 0:
            start_q = inferred_q
        elif inferred_q > 0 and inferred_q != start_q:
            logger.info("SECTION_RULE_START_MISMATCH start_explicit=%s inferred=%s keep=explicit", start_q, inferred_q)
        if start_q <= 0:
            continue
        rule = {
            "start_question": start_q,
            "count": count,
            "marks_per_question": round(per, 4),
            "total": round(total, 4),
            "expr": str(row.get("expr") or f"{count} x {round(per, 4)} = {round(total, 4)}"),
            "source_page": safe_int(row.get("page"), 0),
            "confidence": safe_float(row.get("confidence"), 0.0),
            "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
        }
        rules.append(rule)
        logger.info(
            "SECTION_RULE_CREATED start=%s count=%s marks=%s total=%s page=%s",
            start_q,
            count,
            round(per, 4),
            round(total, 4),
            safe_int(row.get("page"), 0),
        )

    if not rules:
        for block in (structure.get("section_math_blocks") or []):
            if not isinstance(block, dict):
                continue
            parsed = parse_section_math_expression(block.get("expression"))
            if parsed:
                count, per, total = parsed
            else:
                count = safe_int(block.get("question_count"), 0)
                per = safe_float(block.get("per_question_marks"), 0.0)
                total = safe_float(block.get("total_marks"), 0.0)
            if count <= 0 or per <= 0 or total <= 0:
                continue
            start_q = safe_int(((block.get("range") or {}).get("start")), 0)
            if start_q <= 0:
                continue
            rule = {
                "start_question": start_q,
                "count": count,
                "marks_per_question": round(per, 4),
                "total": round(total, 4),
                "expr": str(block.get("expression") or f"{count} x {round(per, 4)} = {round(total, 4)}"),
                "source_page": safe_int(block.get("page_index"), 0),
                "confidence": safe_float(block.get("confidence"), 0.0),
                "bbox": [0, 0, 0, 0],
            }
            rules.append(rule)
            logger.info(
                "SECTION_RULE_CREATED start=%s count=%s marks=%s total=%s page=%s",
                start_q,
                count,
                round(per, 4),
                round(total, 4),
                safe_int(block.get("page_index"), 0),
            )
    rules.sort(key=lambda r: (safe_int(r.get("source_page"), 0), safe_int(r.get("start_question"), 0)))
    return rules


def _ensure_section_rule_anchor_coverage(
    section_rules: List[Dict[str, Any]],
    visual_entities: Optional[Dict[str, Any]],
) -> int:
    if not section_rules or not isinstance(visual_entities, dict):
        return 0
    anchors = list(visual_entities.get("questions") or [])
    by_num: Dict[int, Dict[str, Any]] = {}
    for row in anchors:
        if not isinstance(row, dict):
            continue
        qn = safe_int(row.get("number"), 0)
        if qn <= 0 or qn in by_num:
            continue
        by_num[qn] = row

    synthetic_added = 0
    for rule in section_rules:
        start_q = safe_int(rule.get("start_question"), 0)
        count = safe_int(rule.get("count"), 0)
        if start_q <= 0 or count <= 0:
            continue
        expected = list(range(start_q, start_q + count))
        missing = [qn for qn in expected if qn not in by_num]
        if not missing:
            continue
        for qn in missing:
            anchor = {
                "number": qn,
                "bbox": list(rule.get("bbox") or [0, 0, 0, 0]),
                "page": safe_int(rule.get("source_page"), 0),
                "confidence": 0.2,
                "source": "synthetic",
            }
            anchors.append(anchor)
            by_num[qn] = anchor
            synthetic_added += 1

    if synthetic_added:
        anchors.sort(key=lambda r: safe_int(r.get("number"), 0))
        visual_entities["questions"] = anchors
    return synthetic_added


def _log_anchor_merge_result(visual_entities: Optional[Dict[str, Any]]) -> None:
    if not isinstance(visual_entities, dict):
        return
    anchors = list(visual_entities.get("questions") or [])
    total = len(anchors)
    visual = 0
    ocr = 0
    synthetic = 0
    for row in anchors:
        if not isinstance(row, dict):
            continue
        src = str(row.get("source") or "").lower()
        if src == "visual":
            visual += 1
        elif src == "ocr":
            ocr += 1
        elif src == "synthetic":
            synthetic += 1
    logger.info(
        "ANCHOR_MERGE_RESULT total=%s visual=%s ocr=%s synthetic=%s",
        total,
        visual,
        ocr,
        synthetic,
    )


def _section_rule_priority(rule: Dict[str, Any]) -> int:
    count = safe_int(rule.get("count"), 0)
    if count <= 0:
        return 0
    if count == 1:
        return 3
    if count <= 2:
        return 2
    if count <= 4:
        return 1
    return 0


def _reconcile_section_rule_starts(section_rules: List[Dict[str, Any]], qnums: List[int]) -> List[Dict[str, Any]]:
    if not section_rules or not qnums:
        return section_rules
    qnums_sorted = list(qnums)
    cursor_idx = 0
    reconciled: List[Dict[str, Any]] = []

    for rule in section_rules:
        count = safe_int(rule.get("count"), 0)
        if count <= 0:
            continue
        start = safe_int(rule.get("start_question"), 0)

        if cursor_idx >= len(qnums_sorted):
            reconciled.append(rule)
            continue

        cursor_q = qnums_sorted[cursor_idx]
        new_start = start
        if start <= 0:
            new_start = cursor_q
        elif start < cursor_q:
            # Overlapping/secondary rule (likely subparts). Keep as-is.
            reconciled.append(rule)
            continue
        elif start > cursor_q:
            new_start = cursor_q
            logger.info(
                "SECTION_RULE_REALIGN start_old=%s start_new=%s count=%s",
                start,
                new_start,
                count,
            )

        if new_start != start:
            rule = dict(rule)
            rule["start_question"] = new_start
            per = max(0.0, safe_float(rule.get("marks_per_question"), 0.0))
            if per > 0:
                rule["total"] = round(per * count, 4)
        reconciled.append(rule)

        # Advance cursor only for primary (non-overlapping) rules.
        if new_start == cursor_q:
            cursor_idx = min(len(qnums_sorted), cursor_idx + count)

    return reconciled


def _apply_section_rule_conflicts(
    section_rules: List[Dict[str, Any]],
    qnums: List[int],
    q_margin: Dict[int, Dict[str, Any]],
) -> Tuple[Dict[int, Dict[str, Any]], List[Dict[str, Any]]]:
    assignments: Dict[int, Dict[str, Any]] = {}
    rule_meta: Dict[str, Dict[str, Any]] = {}
    q_to_rule: Dict[int, str] = {}

    for idx, rule in enumerate(section_rules):
        count = safe_int(rule.get("count"), 0)
        per = max(0.0, safe_float(rule.get("marks_per_question"), 0.0))
        start_q = safe_int(rule.get("start_question"), 0)
        if count <= 0 or per <= 0 or start_q <= 0 or start_q not in qnums:
            continue
        start_idx = qnums.index(start_q)
        run = qnums[start_idx:start_idx + count]
        rule_id = f"sec_{idx + 1}"
        priority = _section_rule_priority(rule)
        rule_meta[rule_id] = {"rule": dict(rule), "applied": [], "priority": priority, "run": list(run)}

        for qn in run:
            if qn in q_margin:
                logger.info("SECTION_RULE_OVERRIDE q=%s keep=margin drop=%s", qn, str(rule.get("expr") or ""))
                continue
            existing = assignments.get(qn)
            if existing:
                if existing.get("priority", 0) >= priority:
                    continue
                prev_id = q_to_rule.get(qn)
                if prev_id and qn in rule_meta.get(prev_id, {}).get("applied", []):
                    rule_meta[prev_id]["applied"].remove(qn)
                logger.info(
                    "SECTION_RULE_OVERRIDE q=%s keep=%s drop=%s",
                    qn,
                    str(rule.get("expr") or ""),
                    str(existing.get("expr") or ""),
                )

            assignments[qn] = {
                "marks": round(per, 4),
                "expr": str(rule.get("expr") or f"{count} x {round(per, 4)} = {round(safe_float(rule.get('total'), 0.0), 4)}"),
                "evidence": {
                    "bbox": list(rule.get("bbox") or [0, 0, 0, 0]),
                    "page": safe_int(rule.get("source_page"), 0),
                    "confidence": round(safe_float(rule.get("confidence"), 0.0), 4),
                    "source": "section_math",
                },
                "rule_id": rule_id,
                "priority": priority,
            }
            q_to_rule[qn] = rule_id
            rule_meta[rule_id]["applied"].append(qn)

    resolved_rules: List[Dict[str, Any]] = []
    for rule_id, meta in rule_meta.items():
        applied = list(meta.get("applied") or [])
        if not applied:
            continue
        rule = dict(meta.get("rule") or {})
        per = max(0.0, safe_float(rule.get("marks_per_question"), 0.0))
        original_count = safe_int(rule.get("count"), 0)
        if len(applied) < original_count:
            logger.warning(
                "SECTION_RULE_PARTIAL_APPLY start=%s count=%s applied=%s questions=%s",
                safe_int(rule.get("start_question"), 0),
                original_count,
                len(applied),
                applied,
            )
        applied_sorted = sorted(applied)
        segments: List[List[int]] = []
        current: List[int] = []
        for qn in applied_sorted:
            if not current or qn == current[-1] + 1:
                current.append(qn)
            else:
                segments.append(current)
                current = [qn]
        if current:
            segments.append(current)

        for seg_idx, segment in enumerate(segments):
            seg_rule = dict(rule)
            seg_rule_id = rule_id if seg_idx == 0 else f"{rule_id}_{seg_idx + 1}"
            seg_rule["start_question"] = segment[0]
            seg_rule["count"] = len(segment)
            seg_rule["total"] = round(len(segment) * per, 4)
            seg_rule["questions"] = list(segment)
            seg_rule["rule_id"] = seg_rule_id
            resolved_rules.append(seg_rule)
            logger.info(
                "SECTION_RULE_APPLIED start=%s count=%s marks=%s total=%s questions=%s",
                safe_int(seg_rule.get("start_question"), 0),
                safe_int(seg_rule.get("count"), 0),
                round(per, 4),
                round(safe_float(seg_rule.get("total"), 0.0), 4),
                segment,
            )
            for qn in segment:
                logger.info(
                    "SECTION_RULE_APPLIED_Q q=%s start=%s count=%s marks=%s expr=%s",
                    qn,
                    safe_int(seg_rule.get("start_question"), 0),
                    safe_int(seg_rule.get("count"), 0),
                    round(per, 4),
                    str(seg_rule.get("expr") or ""),
                )

    return assignments, resolved_rules


def _margin_mark_maps(visual_entities: Optional[Dict[str, Any]]) -> Tuple[Dict[int, Dict[str, Any]], Dict[Tuple[int, str], Dict[str, Any]]]:
    q_marks: Dict[int, Dict[str, Any]] = {}
    sq_marks: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for row in (visual_entities or {}).get("margin_marks") or []:
        if not isinstance(row, dict):
            continue
        qn = safe_int(row.get("q"), 0)
        if qn <= 0:
            continue
        mark = max(0.0, safe_float(row.get("marks"), 0.0))
        if mark <= 0:
            continue
        sub = _norm_label(row.get("sub"))
        raw_text = row.get("text") or row.get("raw") or row.get("expression")
        split_values: Optional[List[float]] = None
        if isinstance(row.get("split"), list):
            split_values = [safe_float(v, 0.0) for v in row.get("split") if safe_float(v, 0.0) > 0]
        if not split_values:
            split_values = _parse_margin_split_text(raw_text)
        payload = {
            "marks": round(mark, 4),
            "text": str(raw_text or "").strip() or None,
            "split": split_values or None,
            "evidence": {
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "page": safe_int(row.get("page"), 0),
                "confidence": round(safe_float(row.get("confidence"), 0.0), 4),
                "source": "margin",
            },
        }
        if sub:
            sq_marks[(qn, sub)] = payload
        else:
            q_marks[qn] = payload
    return q_marks, sq_marks


def _mode_positive(values: List[float]) -> Optional[float]:
    vals = [round(v, 4) for v in values if safe_float(v, 0.0) > 0]
    if not vals:
        return None
    cnt = Counter(vals)
    return float(sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0])


def resolve_marks(
    question_structure: Dict[str, Any],
    *,
    visual_entities: Optional[Dict[str, Any]] = None,
    header_total_marks: Optional[float] = None,
    header_total_reliable: bool = False,
) -> Dict[str, Any]:
    """
    Deterministic mark computation priority:
    1) margin marks
    2) section math
    3) header totals (if reliable)
    4) pattern inference
    """

    normalized = normalize_structure_payload(question_structure or {})
    questions = [dict(q) for q in (normalized.get("questions") or [])]
    questions.sort(key=lambda q: safe_int(q.get("number"), 0))
    if not questions:
        return {
            "resolved_structure": normalized,
            "effective_total_marks": 0.0,
            "effective_marks_map": [],
            "mark_override_coverage": 0.0,
            "or_groups_map": {},
            "ai_visual_mismatches": [],
            "question_audit_tree": [],
        }

    by_num: Dict[int, Dict[str, Any]] = {safe_int(q.get("number"), 0): q for q in questions if safe_int(q.get("number"), 0) > 0}
    qnums = sorted(by_num.keys())
    base_marks: Dict[int, float] = {qn: max(0.0, safe_float(by_num[qn].get("marks"), 0.0)) for qn in qnums}
    question_marks: Dict[int, float] = dict(base_marks)
    question_source: Dict[int, str] = {qn: "inferred" for qn in qnums}
    question_mode: Dict[int, str] = {qn: "direct" for qn in qnums}
    evidence_refs: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    q_margin, sq_margin = _margin_mark_maps(visual_entities)
    section_blocks = _resolve_section_math_blocks(normalized, visual_entities)
    section_rules = _build_section_math_rules(normalized, visual_entities)
    section_rules = _reconcile_section_rule_starts(section_rules, qnums)
    _ensure_section_rule_anchor_coverage(section_rules, visual_entities)
    _log_anchor_merge_result(visual_entities)
    effective_marks_map: List[Dict[str, Any]] = []
    changed_questions: set[int] = set()

    # Build OR groups first so they are preserved in output.
    or_groups_map = _build_or_groups(questions, visual_entities)
    q_to_gid: Dict[int, str] = {}
    for gid, members in or_groups_map.items():
        for qn in members:
            q_to_gid[qn] = gid

    # Apply section math rule assignments with conflict resolution.
    section_assignments, section_rules = _apply_section_rule_conflicts(section_rules, qnums, q_margin)

    # Fallback to section math blocks when no rule exists.
    # Be strict: only apply when an explicit range/start is available to avoid misassignment.
    if not section_assignments:
        for block in section_blocks:
            count = safe_int(block.get("count"), 0)
            per = max(0.0, safe_float(block.get("per"), 0.0))
            if count <= 0 or per <= 0:
                continue
            rng = block.get("range") or {}
            start_q = safe_int(rng.get("start"), 0)
            end_q = safe_int(rng.get("end"), 0)
            run: List[int] = []
            if start_q > 0:
                if end_q >= start_q:
                    run = [qn for qn in qnums if start_q <= qn <= end_q]
                elif start_q in qnums:
                    start_idx = qnums.index(start_q)
                    run = qnums[start_idx:start_idx + count]
            if not run:
                logger.info(
                    "SECTION_BLOCK_SKIPPED start=%s end=%s count=%s reason=no_explicit_range",
                    start_q,
                    end_q,
                    count,
                )
                continue
            if count > 0:
                run = run[:count]

            for qn in run:
                if qn in q_margin:
                    continue
                section_assignments[qn] = {
                    "marks": round(per, 4),
                    "expr": str(block.get("expr") or ""),
                    "evidence": {
                        "bbox": list(block.get("bbox") or [0, 0, 0, 0]),
                        "page": safe_int(block.get("page"), 0),
                        "confidence": round(safe_float(block.get("confidence"), 0.0), 4),
                        "source": "section_math",
                    },
                }

    # Resolve parent marks + subpart marks.
    question_audit_tree: List[Dict[str, Any]] = []
    for qn in qnums:
        q = by_num[qn]
        base = max(0.0, safe_float(base_marks.get(qn), 0.0))
        total = base
        source = "inferred"
        mode = "direct"

        if qn in q_margin:
            total = max(0.0, safe_float(q_margin[qn]["marks"], 0.0))
            source = "margin"
            evidence_refs[qn].append(dict(q_margin[qn]["evidence"]))
            logger.info("MARK_REASON_APPLIED q=%s reason=margin marks=%s", qn, round(total, 4))
        elif qn in section_assignments:
            total = max(0.0, safe_float(section_assignments[qn]["marks"], 0.0))
            source = "section_math"
            evidence_refs[qn].append(dict(section_assignments[qn]["evidence"]))
            logger.info(
                "MARK_REASON_APPLIED q=%s reason=section_math marks=%s expression=%s",
                qn,
                round(total, 4),
                section_assignments[qn].get("expr"),
            )
        else:
            instr = _extract_instruction_mark(q.get("instruction"), q.get("question_text"))
            if instr is not None:
                total = instr
                source = "instruction"
                logger.info("MARK_REASON_APPLIED q=%s reason=instruction marks=%s", qn, round(total, 4))

        subparts = [dict(sq) for sq in (q.get("subquestions") or [])]
        sub_audit: List[Dict[str, Any]] = []
        if subparts:
            explicit_sum = 0.0
            explicit_idxs: List[int] = []
            sub_values: List[float] = [0.0] * len(subparts)
            sub_sources: List[str] = ["inferred"] * len(subparts)

            for idx, sq in enumerate(subparts):
                lbl = _norm_label(sq.get("label")) or str(sq.get("label") or "").strip().lower()
                if not lbl:
                    lbl = f"s{idx+1}"
                    sq["label"] = lbl
                skey = (qn, lbl)
                if skey in sq_margin:
                    val = max(0.0, safe_float(sq_margin[skey]["marks"], 0.0))
                    sub_values[idx] = val
                    sub_sources[idx] = "margin"
                    explicit_sum += val
                    explicit_idxs.append(idx)
                    evidence_refs[qn].append(dict(sq_margin[skey]["evidence"]))
                elif safe_float(sq.get("marks"), 0.0) > 0 and _norm_source(sq.get("mark_source")) in _EXPLICIT_SOURCES:
                    val = max(0.0, safe_float(sq.get("marks"), 0.0))
                    sub_values[idx] = val
                    sub_sources[idx] = _norm_source(sq.get("mark_source"))
                    explicit_sum += val
                    explicit_idxs.append(idx)

            split_values: Optional[List[float]] = None
            if not explicit_idxs and qn in q_margin:
                split_values = q_margin[qn].get("split")
                if not split_values:
                    split_values = _parse_margin_split_text(q_margin[qn].get("text"))
                if split_values and len(split_values) == len(subparts):
                    sub_values = [round(max(0.0, safe_float(v, 0.0)), 4) for v in split_values]
                    sub_sources = ["margin" for _ in subparts]
                    explicit_sum = round(sum(sub_values), 4)
                    explicit_idxs = list(range(len(subparts)))
                    if total <= 0 or abs(total - explicit_sum) > 1e-6:
                        total = explicit_sum
                        source = "margin"
                    logger.info(
                        "MARK_REASON_APPLIED q=%s reason=margin_split marks=%s",
                        qn,
                        round(total, 4),
                    )

            if total <= 0 and explicit_sum > 0:
                total = round(explicit_sum, 4)
                source = "margin" if any(s == "margin" for s in sub_sources) else "inferred"

            if len(explicit_idxs) == 0 and total > 0:
                even = total / float(len(subparts))
                sub_values = [even for _ in subparts]
                sub_sources = [source for _ in subparts]
                mode = "shared"
                logger.info("MARK_REASON_APPLIED q=%s reason=subpart_shared marks=%s", qn, round(total, 4))
                if source == "section_math":
                    logger.info(
                        "SUBPART_AUTO_SPLIT q=%s total=%s per_subpart=%s",
                        qn,
                        round(total, 4),
                        round(even, 4),
                    )
            else:
                missing = [i for i in range(len(subparts)) if i not in explicit_idxs]
                if missing and total > explicit_sum:
                    even = (total - explicit_sum) / float(len(missing))
                    for idx in missing:
                        sub_values[idx] = even
                        sub_sources[idx] = source
                    mode = "shared"
                    logger.info(
                        "MARK_REASON_APPLIED q=%s reason=subpart_fill marks=%s remaining=%s",
                        qn,
                        round(total, 4),
                        round(total - explicit_sum, 4),
                    )
                    if source == "section_math":
                        logger.info(
                            "SUBPART_AUTO_SPLIT q=%s total=%s per_subpart=%s",
                            qn,
                            round(total, 4),
                            round(even, 4),
                        )
                elif missing and total <= explicit_sum:
                    for idx in missing:
                        sub_values[idx] = 0.0
                        sub_sources[idx] = "inferred"

            sub_sum = sum(max(0.0, v) for v in sub_values)
            if total > 0 and abs(sub_sum - total) > 1e-6:
                # Deterministic adjustment on last non-margin slot.
                adjustables = [i for i in range(len(subparts)) if sub_sources[i] != "margin"]
                pick = adjustables[-1] if adjustables else len(subparts) - 1
                sub_values[pick] = max(0.0, sub_values[pick] + (total - sub_sum))
                sub_sum = sum(max(0.0, v) for v in sub_values)

            if total <= 0 and sub_sum > 0:
                total = round(sub_sum, 4)
                source = "inferred"

            rounded_vals = [round(max(0.0, v), 4) for v in sub_values]
            if total > 0:
                rounded_sum = round(sum(rounded_vals), 4)
                diff = round(total - rounded_sum, 4)
                if abs(diff) > 1e-6:
                    adjustables = [i for i in range(len(subparts)) if sub_sources[i] != "margin"]
                    pick = adjustables[-1] if adjustables else len(subparts) - 1
                    rounded_vals[pick] = round(max(0.0, rounded_vals[pick] + diff), 4)

            for idx, sq in enumerate(subparts):
                lbl = _norm_label(sq.get("label")) or str(sq.get("label") or "").strip().lower()
                val = round(max(0.0, rounded_vals[idx]), 4)
                ssrc = _norm_source(sub_sources[idx] or "inferred")
                sq["marks"] = val
                sq["mark_source"] = ssrc
                sq["mark_confidence"] = _source_confidence(ssrc)
                sq["confidence"] = max(safe_float(sq.get("confidence"), 0.0), _source_confidence(ssrc))
                subparts[idx] = sq
                sub_audit.append({"label": lbl or f"s{idx+1}", "marks": val, "source": ssrc})
                if val > 0:
                    effective_marks_map.append(
                        {
                            "question_number": qn,
                            "sub_label": lbl,
                            "marks": val,
                            "evidence": [0, [0, 0, 0, 0], _source_confidence(ssrc)],
                            "source": ssrc,
                        }
                    )

        q["subquestions"] = subparts
        q["marks"] = round(max(0.0, total), 4)
        q["mark_source"] = _norm_source(source)
        q["mark_confidence"] = _source_confidence(source)
        q["distribution_mode"] = mode
        q["or_group_id"] = q_to_gid.get(qn) or q.get("or_group_id")
        q["evidence_refs"] = evidence_refs.get(qn, [])
        by_num[qn] = q

        if abs(base - q["marks"]) > 1e-6:
            changed_questions.add(qn)
            logger.info("MARK_OVERRIDE_APPLIED q=%s sub=- ai=%s visual=%s", qn, round(base, 4), round(q["marks"], 4))

        effective_marks_map.append(
            {
                "question_number": qn,
                "sub_label": None,
                "marks": round(q["marks"], 4),
                "evidence": [0, [0, 0, 0, 0], _source_confidence(source)],
                "source": _norm_source(source),
            }
        )

        question_audit_tree.append(
            {
                "number": qn,
                "total_marks": round(max(0.0, q["marks"]), 4),
                "subparts": sub_audit,
                "mark_source": _norm_source(source),
                "distribution_mode": mode,
                "evidence_refs": list(evidence_refs.get(qn, [])),
                "confidence": round(_source_confidence(source), 4),
            }
        )

    # Header-total alignment (priority 3) then pattern inference (priority 4).
    def _sync_audit_for_q(qn: int) -> None:
        for row in question_audit_tree:
            if safe_int(row.get("number"), 0) == qn:
                q = by_num.get(qn) or {}
                row["total_marks"] = round(max(0.0, safe_float(q.get("marks"), 0.0)), 4)
                row["mark_source"] = _norm_source(q.get("mark_source"))
                row["distribution_mode"] = str(q.get("distribution_mode") or row.get("distribution_mode") or "direct")
                row["confidence"] = round(_source_confidence(q.get("mark_source")), 4)
                row["subparts"] = [
                    {
                        "label": _norm_label(sq.get("label")) or str(sq.get("label") or ""),
                        "marks": round(max(0.0, safe_float(sq.get("marks"), 0.0)), 4),
                        "source": _norm_source(sq.get("mark_source")),
                    }
                    for sq in (q.get("subquestions") or [])
                ]
                break

    if header_total_reliable and header_total_marks and header_total_marks > 0:
        current_total = _compute_effective_total([by_num[n] for n in qnums])
        target_total = round(float(header_total_marks), 4)
        delta = round(target_total - current_total, 4)
        if abs(delta) > 1e-6:
            # Fill/reduce inferred marks only.
            inferred_candidates = [
                qn
                for qn in qnums
                if _norm_source((by_num.get(qn) or {}).get("mark_source")) not in {"margin", "section_math"}
            ]
            pattern = _mode_positive([safe_float((by_num.get(qn) or {}).get("marks"), 0.0) for qn in qnums]) or 1.0
            if delta > 0:
                for qn in inferred_candidates:
                    if delta <= 1e-6:
                        break
                    q = by_num[qn]
                    cur = max(0.0, safe_float(q.get("marks"), 0.0))
                    if cur > 0:
                        continue
                    add = min(pattern, delta)
                    q["marks"] = round(cur + add, 4)
                    q["mark_source"] = "inferred"
                    q["distribution_mode"] = "section_pattern"
                    by_num[qn] = q
                    delta = round(delta - add, 4)
                    changed_questions.add(qn)
                    logger.info("MARK_REASON_APPLIED q=%s reason=header_total_fill marks=%s", qn, round(q["marks"], 4))
                    _sync_audit_for_q(qn)
            else:
                need = abs(delta)
                for qn in reversed(inferred_candidates):
                    if need <= 1e-6:
                        break
                    q = by_num[qn]
                    cur = max(0.0, safe_float(q.get("marks"), 0.0))
                    if cur <= 0:
                        continue
                    cut = min(cur, need)
                    q["marks"] = round(cur - cut, 4)
                    q["mark_source"] = "inferred"
                    q["distribution_mode"] = "section_pattern"
                    by_num[qn] = q
                    need = round(need - cut, 4)
                    changed_questions.add(qn)
                    logger.info("MARK_REASON_APPLIED q=%s reason=header_total_trim marks=%s", qn, round(q["marks"], 4))
                    _sync_audit_for_q(qn)

    # Pattern inference for still-missing marks.
    covered_by_rules: set[int] = set()
    for rule in section_rules:
        covered_by_rules.update(int(qn) for qn in (rule.get("questions") or []) if safe_int(qn, 0) > 0)
    covered_by_rules.update(section_assignments.keys())

    pattern_mark = _mode_positive([safe_float((by_num.get(qn) or {}).get("marks"), 0.0) for qn in qnums]) or 1.0
    for qn in qnums:
        if qn in covered_by_rules:
            continue
        q = by_num[qn]
        if safe_float(q.get("marks"), 0.0) > 0:
            continue
        qtype = str(q.get("question_type") or "").strip().lower()
        inferred_default = 1.0 if qtype in {"mcq", "fill_blank", "very_short"} else pattern_mark
        q["marks"] = round(inferred_default, 4)
        q["mark_source"] = "inferred"
        q["distribution_mode"] = "section_pattern"
        by_num[qn] = q
        changed_questions.add(qn)
        logger.info(
            "MARK_REASON_APPLIED q=%s reason=pattern_inference marks=%s qtype=%s",
            qn,
            round(q["marks"], 4),
            qtype or "unknown",
        )
        _sync_audit_for_q(qn)

    # OR integrity: all branches share same marks (max) and must not be double counted.
    for gid, members in sorted(or_groups_map.items(), key=lambda kv: kv[0]):
        if len(members) < 2:
            continue
        shared = max(max(0.0, safe_float((by_num.get(qn) or {}).get("marks"), 0.0)) for qn in members)
        for qn in members:
            q = by_num.get(qn)
            if not q:
                continue
            old = max(0.0, safe_float(q.get("marks"), 0.0))
            q["or_group_id"] = gid
            if abs(old - shared) > 1e-6:
                q["marks"] = round(shared, 4)
                q["mark_source"] = _norm_source(q.get("mark_source") or "inferred")
                q["distribution_mode"] = str(q.get("distribution_mode") or "direct")
                by_num[qn] = q
                changed_questions.add(qn)
                logger.info("MARK_OVERRIDE_APPLIED q=%s sub=- ai=%s visual=%s reason=or_group", qn, round(old, 4), round(shared, 4))
            _sync_audit_for_q(qn)
        logger.info("OR_GROUP_RESOLVED group=%s members=%s effective_marks=%s", gid, members, round(shared, 4))

    # Validate section rules: sum of next n question marks must equal rule total.
    for rule in section_rules:
        run = list(rule.get("questions") or [])
        if not run:
            continue
        run_sum = round(sum(max(0.0, safe_float((by_num.get(qn) or {}).get("marks"), 0.0)) for qn in run), 4)
        expected_total = round(max(0.0, safe_float(rule.get("total"), 0.0)), 4)
        if abs(run_sum - expected_total) > 1e-6:
            logger.warning(
                "SECTION_RULE_MISMATCH start=%s count=%s expected=%s actual=%s",
                safe_int(rule.get("start_question"), 0),
                safe_int(rule.get("count"), 0),
                expected_total,
                run_sum,
            )
            if run_sum > 0:
                logger.info(
                    "SECTION_RULE_OVERRIDE start=%s reason=validation_failed new_total=%s",
                    safe_int(rule.get("start_question"), 0),
                    run_sum,
                )
                rule["total"] = run_sum
                rule["count"] = len(run)
            # Repair by redistributing subparts only.
            for qn in run:
                q = by_num.get(qn)
                if not q:
                    continue
                if _redistribute_subparts_only(q):
                    by_num[qn] = q
                    logger.info("SUBPART_AUTO_SPLIT q=%s total=%s", qn, round(safe_float(q.get("marks"), 0.0), 4))
                    _sync_audit_for_q(qn)

    resolved_questions = [by_num[qn] for qn in qnums]
    resolved_structure = {
        "questions": resolved_questions,
        "section_math_blocks": [
            {
                "section": None,
                "expression": str(b.get("expr") or ""),
                "question_count": safe_int(b.get("count"), 0),
                "per_question_marks": round(safe_float(b.get("per"), 0.0), 4),
                "total_marks": round(safe_float(b.get("total"), 0.0), 4),
                "page_index": safe_int(b.get("page"), 0),
                "confidence": round(safe_float(b.get("confidence"), 0.0), 4),
                "range": (
                    {
                        "start": safe_int(((b.get("range") or {}).get("start")), 0),
                        "end": safe_int(((b.get("range") or {}).get("end")), 0),
                    }
                    if isinstance(b.get("range"), dict)
                    and safe_int(((b.get("range") or {}).get("start")), 0) > 0
                    else None
                ),
            }
            for b in section_blocks
        ],
        "section_math_rules": [
            {
                "start_question": safe_int(rule.get("start_question"), 0),
                "count": safe_int(rule.get("count"), 0),
                "marks_per_question": round(safe_float(rule.get("marks_per_question"), 0.0), 4),
                "total": round(safe_float(rule.get("total"), 0.0), 4),
                "source_page": safe_int(rule.get("source_page"), 0),
            }
            for rule in section_rules
        ],
        "total_questions": len(resolved_questions),
        "total_marks": _compute_effective_total(resolved_questions),
        "effective_total_marks": _compute_effective_total(resolved_questions),
        "numbering_contiguous": bool(normalized.get("numbering_contiguous", False)),
    }

    ai_visual_mismatches: List[Dict[str, Any]] = []
    for qn in qnums:
        ai_mark = round(max(0.0, safe_float(base_marks.get(qn), 0.0)), 4)
        resolved_mark = round(max(0.0, safe_float((by_num.get(qn) or {}).get("marks"), 0.0)), 4)
        if abs(ai_mark - resolved_mark) > 1e-6:
            ai_visual_mismatches.append({"question_number": qn, "ai_marks": ai_mark, "visual_marks": resolved_mark})

    for audit in sorted(question_audit_tree, key=lambda x: safe_int(x.get("number"), 0)):
        logger.info(
            "QUESTION_AUDIT q=%s total=%s source=%s mode=%s subparts=%s confidence=%.3f",
            safe_int(audit.get("number"), 0),
            round(safe_float(audit.get("total_marks"), 0.0), 4),
            str(audit.get("mark_source") or "inferred"),
            str(audit.get("distribution_mode") or "direct"),
            len(audit.get("subparts") or []),
            safe_float(audit.get("confidence"), 0.0),
        )

    coverage = round((len(changed_questions) / float(len(qnums))) if qnums else 0.0, 4)
    logger.info("MARK_REASON_APPLIED questions=%s changed=%s coverage=%.4f", len(qnums), len(changed_questions), coverage)

    return {
        "resolved_structure": normalize_structure_payload(resolved_structure),
        "effective_total_marks": _compute_effective_total(resolved_questions),
        "effective_marks_map": effective_marks_map,
        "mark_override_coverage": coverage,
        "or_groups_map": {gid: sorted(set(members)) for gid, members in or_groups_map.items() if len(set(members)) >= 2},
        "ai_visual_mismatches": ai_visual_mismatches,
        "question_audit_tree": sorted(question_audit_tree, key=lambda x: safe_int(x.get("number"), 0)),
    }


__all__ = ["resolve_marks"]
