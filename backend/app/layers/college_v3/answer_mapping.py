"""Answer mapping for college_v3 (anchor + hybrid continuity)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.config import logger
from app.layers.universal.embeddings import SemanticEmbeddingService, cosine_similarity
from .anchor_detection import detect_anchors


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_]+", text.lower() if text else "")


def _lexical_overlap(a: str, b: str) -> float:
    ta = set(_tokenize(a))
    tb = set(_tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def _bbox_center(bbox: List[float]) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0
    return float(bbox[1] + bbox[3]) * 0.5


def _layout_signature(blocks: List[Dict[str, Any]]) -> Tuple[float, float]:
    if not blocks:
        return 0.0, 0.0
    line_count = len(blocks)
    avg_width = 0.0
    for blk in blocks:
        bbox = blk.get("bbox") or [0, 0, 0, 0]
        avg_width += float(bbox[2]) - float(bbox[0])
    avg_width = avg_width / max(1, line_count)
    return float(line_count), avg_width


def _handwriting_proxy(word_boxes: List[Dict[str, Any]]) -> Tuple[float, float]:
    if not word_boxes:
        return 0.0, 0.0
    heights = []
    widths = []
    for w in word_boxes:
        bbox = w.get("bbox") or [0, 0, 0, 0]
        widths.append(float(bbox[2]) - float(bbox[0]))
        heights.append(float(bbox[3]) - float(bbox[1]))
    avg_h = sum(heights) / max(1, len(heights))
    avg_w = sum(widths) / max(1, len(widths))
    ratio = avg_h / max(1.0, avg_w)
    return avg_h, ratio


def _similarity(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    diff = abs(a - b) / max(a, b)
    return max(0.0, 1.0 - diff)


def _segment_page_by_anchors(
    blocks: List[Dict[str, Any]],
    anchors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not anchors:
        return []
    sorted_blocks = sorted(blocks, key=lambda b: _bbox_center(b.get("bbox") or [0, 0, 0, 0]))
    sorted_anchors = sorted(anchors, key=lambda a: float(a.get("y_position") or 0.0))
    segments: List[Dict[str, Any]] = []
    for idx, anchor in enumerate(sorted_anchors):
        start_y = float(anchor.get("y_position") or 0.0)
        next_anchor = sorted_anchors[idx + 1] if idx + 1 < len(sorted_anchors) else None
        end_y = float(next_anchor.get("y_position") or 1e9) if next_anchor else 1e9
        seg_blocks = [b for b in sorted_blocks if start_y <= _bbox_center(b.get("bbox") or [0, 0, 0, 0]) < end_y]
        seg_text = "\n".join((b.get("text") or "").strip() for b in seg_blocks if (b.get("text") or "").strip()).strip()
        segments.append(
            {
                "question_number": anchor.get("question_number"),
                "anchor": anchor,
                "blocks": seg_blocks,
                "text": seg_text,
            }
        )
    return segments


def _compute_continuity_scores(
    *,
    last_text: str,
    last_blocks: List[Dict[str, Any]],
    last_words: List[Dict[str, Any]],
    curr_text: str,
    curr_blocks: List[Dict[str, Any]],
    curr_words: List[Dict[str, Any]],
    embedding: SemanticEmbeddingService,
) -> Tuple[float, float, float, float, float]:
    semantic = 0.0
    try:
        vecs = embedding.embed([last_text, curr_text])
        semantic = cosine_similarity(vecs[0], vecs[1])
    except Exception as e:
        logger.warning("[COLLEGE-V3][MAP] embedding fallback: %s", e)
        semantic = 0.0

    layout_a = _layout_signature(last_blocks)
    layout_b = _layout_signature(curr_blocks)
    spatial = (_similarity(layout_a[0], layout_b[0]) + _similarity(layout_a[1], layout_b[1])) / 2.0

    hand_a = _handwriting_proxy(last_words)
    hand_b = _handwriting_proxy(curr_words)
    handwriting = (_similarity(hand_a[0], hand_b[0]) + _similarity(hand_a[1], hand_b[1])) / 2.0

    lexical = _lexical_overlap(last_text, curr_text)

    continuity_score = (
        0.35 * semantic
        + 0.25 * spatial
        + 0.20 * handwriting
        + 0.20 * lexical
    )
    return continuity_score, semantic, spatial, handwriting, lexical


def map_answers(
    answer_pages: List[Dict[str, Any]],
    expected_questions: List[int],
    continuity_threshold: float = 0.65,
    mapping_conf_threshold: float = 0.75,
    continuity_conf_threshold: float = 0.70,
) -> Dict[str, Any]:
    anchors = [a for a in detect_anchors(answer_pages) if a.get("anchor_level") == "question"]
    anchors_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for a in anchors:
        anchors_by_page.setdefault(int(a.get("page_index") or 1), []).append(a)
    for page in anchors_by_page.values():
        page.sort(key=lambda a: float(a.get("y_position") or 0.0))

    buckets: Dict[int, List[Dict[str, Any]]] = {}
    orphan_pages: List[int] = []
    continuation_merges: List[Dict[str, Any]] = []
    embedding = SemanticEmbeddingService()

    last_question: Optional[int] = None
    last_text: str = ""
    last_blocks: List[Dict[str, Any]] = []
    last_words: List[Dict[str, Any]] = []
    last_page_index: Optional[int] = None

    pages_with_anchor = 0

    for page in answer_pages:
        page_index = int(page.get("page_index") or 1)
        full_text = str(page.get("full_text") or "")
        blocks = page.get("blocks") or []
        words = page.get("word_boxes") or []

        page_anchors = anchors_by_page.get(page_index, [])
        if page_anchors:
            pages_with_anchor += 1
            # Attach pre-anchor blocks as continuation when applicable.
            first_anchor_y = float(page_anchors[0].get("y_position") or 0.0)
            pre_blocks = [b for b in blocks if _bbox_center(b.get("bbox") or [0, 0, 0, 0]) < first_anchor_y]
            if pre_blocks and last_question is not None:
                pre_text = "\n".join(
                    (b.get("text") or "").strip() for b in pre_blocks if (b.get("text") or "").strip()
                ).strip()
                if last_page_index is None or page_index - last_page_index <= 1:
                    cont_score, semantic, spatial, handwriting, lexical = _compute_continuity_scores(
                        last_text=last_text,
                        last_blocks=last_blocks,
                        last_words=last_words,
                        curr_text=pre_text or full_text,
                        curr_blocks=pre_blocks,
                        curr_words=words,
                        embedding=embedding,
                    )
                    if cont_score >= continuity_threshold:
                        buckets.setdefault(last_question, [])
                        buckets[last_question].append(
                            {
                                "page": page_index,
                                "text": pre_text or full_text,
                                "blocks": pre_blocks,
                                "continuation_flag": True,
                                "attached_by": "continuity",
                                "continuity_score": round(cont_score, 4),
                            }
                        )
                        continuation_merges.append(
                            {
                                "question_number": last_question,
                                "page": page_index,
                                "score": round(cont_score, 4),
                                "semantic": round(semantic, 4),
                                "spatial": round(spatial, 4),
                                "handwriting": round(handwriting, 4),
                                "lexical": round(lexical, 4),
                            }
                        )
                        last_text = pre_text or full_text
                        last_blocks = pre_blocks
                        last_words = words
                        last_page_index = page_index
            segments = _segment_page_by_anchors(blocks, page_anchors)
            for seg in segments:
                qn = seg.get("question_number")
                if qn is None:
                    continue
                qn = int(qn)
                buckets.setdefault(qn, [])
                buckets[qn].append(
                    {
                        "page": page_index,
                        "text": seg.get("text", ""),
                        "blocks": seg.get("blocks", []),
                        "continuation_flag": False,
                        "attached_by": "anchor",
                        "continuity_score": 1.0,
                    }
                )
                last_question = qn
                last_text = seg.get("text", "") or full_text
                last_blocks = seg.get("blocks", [])
                last_words = words
                last_page_index = page_index
        else:
            if last_question is None:
                orphan_pages.append(page_index)
                continue

            if last_page_index is not None and page_index - last_page_index > 1:
                orphan_pages.append(page_index)
                continue
            continuity_score, semantic, spatial, handwriting, lexical = _compute_continuity_scores(
                last_text=last_text,
                last_blocks=last_blocks,
                last_words=last_words,
                curr_text=full_text,
                curr_blocks=blocks,
                curr_words=words,
                embedding=embedding,
            )

            if continuity_score >= continuity_threshold:
                buckets.setdefault(last_question, [])
                buckets[last_question].append(
                    {
                        "page": page_index,
                        "text": full_text,
                        "blocks": blocks,
                        "continuation_flag": True,
                        "attached_by": "continuity",
                        "continuity_score": round(continuity_score, 4),
                    }
                )
                continuation_merges.append(
                    {
                        "question_number": last_question,
                        "page": page_index,
                        "score": round(continuity_score, 4),
                        "semantic": round(semantic, 4),
                        "spatial": round(spatial, 4),
                        "handwriting": round(handwriting, 4),
                        "lexical": round(lexical, 4),
                    }
                )
                last_text = full_text
                last_blocks = blocks
                last_words = words
                last_page_index = page_index
            else:
                orphan_pages.append(page_index)

    mapped_questions = sorted(k for k in buckets.keys() if isinstance(k, int))
    mapped_ratio = len(mapped_questions) / max(1, len(expected_questions))
    anchor_presence_weight = pages_with_anchor / max(1, len(answer_pages))
    spatial_alignment_weight = (
        sum(m.get("spatial", 0.0) for m in continuation_merges) / max(1, len(continuation_merges))
        if continuation_merges
        else 1.0
    )
    semantic_similarity_weight = (
        sum(m.get("semantic", 0.0) for m in continuation_merges) / max(1, len(continuation_merges))
        if continuation_merges
        else 1.0
    )
    continuity_consistency = 1.0 - (len(orphan_pages) / max(1, len(answer_pages)))

    mapping_confidence = (
        anchor_presence_weight
        + spatial_alignment_weight
        + semantic_similarity_weight
        + continuity_consistency
    ) / 4.0

    if continuation_merges:
        continuity_confidence = (
            sum(m.get("score", 0.0) for m in continuation_merges) / max(1, len(continuation_merges))
        )
    else:
        continuity_confidence = 1.0 if not orphan_pages else 0.0

    missing_questions = sorted(set(expected_questions) - set(mapped_questions))

    question_confidence: Dict[int, float] = {}
    low_confidence_questions: List[int] = []
    for qn, segments in buckets.items():
        if not segments:
            continue
        anchor_segments = [s for s in segments if not s.get("continuation_flag")]
        cont_segments = [s for s in segments if s.get("continuation_flag")]
        anchor_strength = 1.0 if anchor_segments else 0.0
        avg_cont = (
            sum(float(s.get("continuity_score", 0.0) or 0.0) for s in cont_segments)
            / max(1, len(cont_segments))
            if cont_segments
            else (1.0 if anchor_segments else 0.0)
        )
        q_conf = 0.6 * anchor_strength + 0.4 * avg_cont
        question_confidence[int(qn)] = round(q_conf, 4)
        if q_conf < 0.6:
            low_confidence_questions.append(int(qn))

    mapping_status = "pass"
    mapping_fail_reasons: List[str] = []
    if mapping_confidence < mapping_conf_threshold:
        mapping_status = "needs_review"
        mapping_fail_reasons.append(
            f"mapping_confidence_below_threshold:{mapping_confidence:.3f}<{mapping_conf_threshold:.3f}"
        )
    if continuity_confidence < continuity_conf_threshold:
        mapping_status = "needs_review"
        mapping_fail_reasons.append(
            f"continuity_confidence_below_threshold:{continuity_confidence:.3f}<{continuity_conf_threshold:.3f}"
        )
    if missing_questions:
        mapping_fail_reasons.append(f"missing_questions:{','.join(str(m) for m in missing_questions)}")

    return {
        "question_page_buckets": buckets,
        "mapping_confidence": round(mapping_confidence, 4),
        "continuity_confidence": round(continuity_confidence, 4),
        "mapping_status": mapping_status,
        "mapping_fail_reasons": mapping_fail_reasons,
        "missing_questions": missing_questions,
        "low_confidence_questions": low_confidence_questions,
        "orphan_pages": orphan_pages,
        "continuation_merges": continuation_merges,
        "question_confidence": question_confidence,
        "anchor_presence_weight": round(anchor_presence_weight, 4),
        "spatial_alignment_weight": round(spatial_alignment_weight, 4),
        "semantic_similarity_weight": round(semantic_similarity_weight, 4),
        "continuity_consistency": round(continuity_consistency, 4),
        "mapped_question_ratio": round(mapped_ratio, 4),
    }
