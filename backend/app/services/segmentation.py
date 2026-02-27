"""Spatial OCR segmentation: words -> lines -> answer blocks."""

from typing import List, Dict, Any


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return float(values[mid])
    return float(values[mid - 1] + values[mid]) / 2.0


def cluster_words_to_lines(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = []
    for w in words or []:
        text = str(w.get("text", "")).strip()
        if not text:
            continue
        try:
            x1 = float(w.get("x1", 0))
            y1 = float(w.get("y1", 0))
            x2 = float(w.get("x2", 0))
            y2 = float(w.get("y2", 0))
        except Exception:
            continue
        items.append({
            "text": text,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "yc": (y1 + y2) / 2.0,
            "conf": float(w.get("conf", w.get("confidence", 0.0)) or 0.0),
            "page": int(w.get("page", 1) or 1),
        })

    if not items:
        return []
    items.sort(key=lambda i: (i["yc"], i["x1"]))
    heights = [max(1.0, i["y2"] - i["y1"]) for i in items]
    y_tolerance = max(8.0, _median(heights) * 0.6)

    line_groups: List[List[Dict[str, Any]]] = []
    for item in items:
        if not line_groups:
            line_groups.append([item])
            continue
        last = line_groups[-1]
        if abs(item["yc"] - last[-1]["yc"]) <= y_tolerance:
            last.append(item)
        else:
            line_groups.append([item])

    lines: List[Dict[str, Any]] = []
    for idx, group in enumerate(line_groups, start=1):
        group.sort(key=lambda i: i["x1"])
        xs = [g["x1"] for g in group] + [g["x2"] for g in group]
        ys = [g["y1"] for g in group] + [g["y2"] for g in group]
        lines.append({
            "line_id": f"L{idx}",
            "text": " ".join(g["text"] for g in group).strip(),
            "x1": min(xs),
            "y1": min(ys),
            "x2": max(xs),
            "y2": max(ys),
            "conf": sum(g["conf"] for g in group) / max(1, len(group)),
            "page": group[0]["page"],
            "words": group,
        })
    return lines


def cluster_lines_to_blocks(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not lines:
        return []
    sorted_lines = sorted(lines, key=lambda l: (float(l.get("y1", 0)), float(l.get("x1", 0))))
    heights = [max(1.0, float(l.get("y2", 0)) - float(l.get("y1", 0))) for l in sorted_lines]
    median_line_height = _median(heights) or 8.0
    # Deterministic split: new segment when vertical gap exceeds 1.8x median line height.
    y_gap_threshold = median_line_height * 1.8

    blocks: List[List[Dict[str, Any]]] = []
    for line in sorted_lines:
        if not blocks:
            blocks.append([line])
            continue
        prev_line = blocks[-1][-1]
        gap = float(line.get("y1", 0)) - float(prev_line.get("y2", 0))
        if gap <= y_gap_threshold:
            blocks[-1].append(line)
        else:
            blocks.append([line])

    out: List[Dict[str, Any]] = []
    for idx, group in enumerate(blocks, start=1):
        xs = [float(l["x1"]) for l in group] + [float(l["x2"]) for l in group]
        ys = [float(l["y1"]) for l in group] + [float(l["y2"]) for l in group]
        out.append({
            "segment_id": f"S{idx}",
            "text": " ".join((l.get("text") or "") for l in group).strip(),
            "x1": min(xs),
            "y1": min(ys),
            "x2": max(xs),
            "y2": max(ys),
            "line_refs": [l.get("line_id") for l in group if l.get("line_id")],
            "confidence": sum(float(l.get("conf", 0.0)) for l in group) / max(1, len(group)),
            "page": int(group[0].get("page", 1) or 1),
            "lines": group,
        })
    out.sort(key=lambda b: (float(b["y1"]), float(b["x1"])))
    return out


def _intersects(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return not (
        float(a.get("x2", 0)) < float(b.get("x1", 0))
        or float(a.get("x1", 0)) > float(b.get("x2", 0))
        or float(a.get("y2", 0)) < float(b.get("y1", 0))
        or float(a.get("y1", 0)) > float(b.get("y2", 0))
    )


def attach_tables_to_segments(segments: List[Dict[str, Any]], tables: List[Dict[str, Any]]) -> None:
    for seg in segments:
        seg["tables"] = []
        for table in tables or []:
            bbox = table.get("bbox") or [0, 0, 0, 0]
            tb = {"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3]}
            if _intersects(seg, tb):
                seg["tables"].append(table)


def build_page_segments(
    words: List[Dict[str, Any]],
    tables: List[Dict[str, Any]] = None,
    page: int = 1,
) -> List[Dict[str, Any]]:
    lines = cluster_words_to_lines(words)
    for line in lines:
        line["page"] = page
    segments = cluster_lines_to_blocks(lines)
    for seg in segments:
        seg["page"] = page
        seg["segment_id"] = f"P{page}-{seg['segment_id']}"
    attach_tables_to_segments(segments, tables or [])
    return segments
