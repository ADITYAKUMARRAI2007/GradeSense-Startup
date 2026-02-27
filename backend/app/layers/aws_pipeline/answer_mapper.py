"""Answer mapping with anchors + continuity using question_uuid."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.config import logger


def _parse_qnum(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def map_answers(
    *,
    answer_pages: List[Dict[str, Any]],
    answer_anchors: List[Dict[str, Any]],
    question_blueprint: List[Dict[str, Any]],
    mapping_threshold: float = 0.75,
    continuity_threshold: float = 0.7,
) -> Dict[str, Any]:
    """Map answer pages to questions; key buckets by question_uuid."""
    number_to_uuid: Dict[int, str] = {}
    for q in question_blueprint or []:
        qn = _parse_qnum(q.get("question_number"))
        if qn is None:
            continue
        if q.get("question_uuid"):
            number_to_uuid[qn] = q.get("question_uuid")

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    orphan_pages: List[int] = []
    continuation_merges: List[Dict[str, Any]] = []

    anchors_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for anchor in answer_anchors or []:
        page = int(anchor.get("page_index") or 1)
        anchors_by_page.setdefault(page, []).append(anchor)

    last_uuid: str | None = None
    last_page: int | None = None

    for page in answer_pages or []:
        page_index = int(page.get("page_index") or 1)
        page_text = page.get("full_text") or ""
        anchors = anchors_by_page.get(page_index, [])
        assigned_uuid = None
        attached_by = "unresolved"

        if anchors:
            # pick first question-level anchor
            for anchor in anchors:
                qn = _parse_qnum(anchor.get("question_number"))
                if qn is None:
                    continue
                assigned_uuid = number_to_uuid.get(qn)
                if assigned_uuid:
                    attached_by = "anchor"
                    break

        # If no direct anchor mapping was possible on this page, allow
        # continuity fallback from adjacent mapped page. This is important for
        # pages that contain only subparts like "(i)/(ii)" or answer text.
        if not assigned_uuid and last_uuid and last_page is not None and abs(page_index - last_page) <= 1:
            assigned_uuid = last_uuid
            attached_by = "continuity"

        if assigned_uuid:
            buckets.setdefault(assigned_uuid, []).append(
                {
                    "page": page_index,
                    "text": page_text,
                    "blocks": page.get("lines") or [],
                    "attached_by": attached_by,
                    "continuity_score": 0.75 if attached_by == "continuity" else 1.0,
                }
            )
            if attached_by == "continuity":
                continuation_merges.append({"page": page_index, "question_uuid": assigned_uuid})
            last_uuid = assigned_uuid
            last_page = page_index
        else:
            orphan_pages.append(page_index)

    total_questions = max(1, len(number_to_uuid))
    mapped_questions = len(buckets)
    mapping_confidence = mapped_questions / float(total_questions)
    continuity_confidence = 1.0 if not continuation_merges else 0.75

    mapping_status = "pass" if (mapping_confidence >= mapping_threshold and continuity_confidence >= continuity_threshold) else "partial"
    mapping_fail_reasons: List[str] = []
    if mapping_status != "pass":
        mapping_fail_reasons.append(f"mapping_confidence_below_threshold:{mapping_confidence:.3f}")

    logger.info("MAPPING_USING_UUID mapped=%s/%s status=%s", mapped_questions, total_questions, mapping_status)
    if mapping_status != "pass":
        logger.info("MAPPING_PARTIAL exam_pages=%s orphan=%s", len(answer_pages), len(orphan_pages))

    return {
        "question_page_buckets": buckets,
        "orphan_pages": orphan_pages,
        "continuation_merges": continuation_merges,
        "mapping_confidence": round(mapping_confidence, 4),
        "continuity_confidence": round(continuity_confidence, 4),
        "mapping_status": mapping_status,
        "mapping_fail_reasons": mapping_fail_reasons,
    }
