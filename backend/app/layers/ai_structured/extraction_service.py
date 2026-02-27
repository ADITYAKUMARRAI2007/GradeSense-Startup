"""AI-first question structure extraction (image-first, OCR-supported)."""

from __future__ import annotations

import asyncio
import ast
import base64
import io
import json
import os
import re
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from app.config import get_llm_api_key, logger
from app.services.llm import ImageContent, LlmChat, UserMessage
from app.utils.ocr_provider import get_ocr_provider

from .mark_reasoner import resolve_marks
from .prompts import (
    build_extraction_prompt,
    build_reconstruction_prompt,
    get_extraction_system_prompt,
    build_visual_extraction_prompt,
    get_visual_extraction_system_prompt,
)
from .safe_numeric import safe_float, safe_int, parse_section_math_expression
from .retry import RetryExhaustedError, run_with_retry
from .structure_repair import apply_structure_repairs
from .structure_validator import validate_structure as validate_structure_stage3
from .validation import normalize_structure_payload
from app.layers.visual_entities import extract_visual_entities


_ALLOWED_TYPES = {
    "mcq",
    "fill_blank",
    "very_short",
    "short",
    "long",
    "passage",
    "writing",
    "letter",
    "essay",
    "short_answer",
    "descriptive",
    "descriptive_choice",
    "passage_subparts",
    "or_group",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    return safe_float(value, default)


def _to_int(value: Any, default: int = 0) -> int:
    return safe_int(value, default)


def _as_payload_dict(parsed: Any) -> Optional[Dict[str, Any]]:
    if isinstance(parsed, dict):
        if any(
            key in parsed
            for key in ("questions", "section_math_blocks", "total_questions", "total_marks", "effective_total_marks")
        ):
            return parsed
        return None
    if isinstance(parsed, list):
        rows = [row for row in parsed if isinstance(row, dict)]
        if rows and len(rows) == len(parsed):
            return {"questions": rows}
        return None
    return None


def _extract_balanced_json_candidates(text: str, *, max_candidates: int = 16) -> List[str]:
    candidates: List[str] = []
    if not text:
        return candidates

    stack: List[str] = []
    start_idx: Optional[int] = None
    in_string = False
    escape = False

    for idx, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch in "{[":
            if not stack:
                start_idx = idx
            stack.append(ch)
            continue

        if ch in "}]":
            if not stack:
                continue
            opener = stack[-1]
            if (opener == "{" and ch == "}") or (opener == "[" and ch == "]"):
                stack.pop()
                if not stack and start_idx is not None:
                    snippet = text[start_idx:idx + 1].strip()
                    if snippet:
                        candidates.append(snippet)
                        if len(candidates) >= max_candidates:
                            break
                    start_idx = None
            else:
                stack.clear()
                start_idx = None

    return candidates


def _sanitize_json_candidate(text: str) -> str:
    out = (text or "").strip().lstrip("\ufeff")
    out = re.sub(r"^\s*```(?:json)?\s*", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s*```\s*$", "", out)
    out = re.sub(r"^\s*json\s*[:\n]", "", out, flags=re.IGNORECASE)
    out = out.strip().rstrip(";")
    out = out.replace("“", '"').replace("”", '"')
    out = out.replace("’", "'").replace("‘", "'")
    out = re.sub(r",(\s*[}\]])", r"\1", out)
    return out.strip()


def _repair_json_string_content(text: str) -> str:
    """
    Repair common JSON string issues produced by LLMs:
    - literal newlines/tabs/carriage returns inside quoted strings
    - invalid backslash escapes inside quoted strings
    """
    if not text:
        return text

    out: List[str] = []
    in_string = False
    i = 0
    n = len(text)
    valid_escapes = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}

    while i < n:
        ch = text[i]

        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue

        # Inside quoted string.
        if ch == '"':
            out.append(ch)
            in_string = False
            i += 1
            continue

        if ch == "\\":
            if i + 1 >= n:
                out.append("\\\\")
                i += 1
                continue
            nxt = text[i + 1]
            if nxt in valid_escapes:
                out.append("\\")
                out.append(nxt)
                i += 2
                continue
            # Invalid escape: keep the next char, but escape the backslash.
            out.append("\\\\")
            i += 1
            continue

        if ch == "\n":
            out.append("\\n")
            i += 1
            continue
        if ch == "\r":
            out.append("\\r")
            i += 1
            continue
        if ch == "\t":
            out.append("\\t")
            i += 1
            continue
        if ord(ch) < 32:
            out.append(f"\\u{ord(ch):04x}")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _parse_any_json_value(candidate: str) -> Any:
    if not candidate:
        return None

    probes: List[str] = []
    base = candidate.strip()
    probes.append(base)
    sanitized = _sanitize_json_candidate(base)
    if sanitized and sanitized != base:
        probes.append(sanitized)
    repaired = _repair_json_string_content(sanitized or base)
    if repaired and repaired not in probes:
        probes.append(repaired)

    decoder = json.JSONDecoder()
    seen: set[str] = set()
    for probe in probes:
        if not probe or probe in seen:
            continue
        seen.add(probe)
        try:
            return json.loads(probe)
        except Exception:
            pass
        try:
            parsed, _end = decoder.raw_decode(probe.lstrip())
            return parsed
        except Exception:
            pass
        try:
            return ast.literal_eval(probe)
        except Exception:
            pass
    return None


def _looks_like_question_dict(obj: Dict[str, Any]) -> bool:
    if not isinstance(obj, dict):
        return False
    qn = _to_int(obj.get("number"), 0)
    if qn <= 0:
        return False
    return bool(
        str(obj.get("question_text") or "").strip()
        or str(obj.get("instruction") or "").strip()
        or str(obj.get("question_type") or "").strip()
    )


def _looks_like_section_math_block(obj: Dict[str, Any]) -> bool:
    if not isinstance(obj, dict):
        return False
    expr = str(obj.get("expression") or "").strip()
    if expr:
        parsed = parse_section_math_expression(expr)
        if parsed:
            return True
    count = _to_int(obj.get("question_count"), 0)
    if count <= 0:
        count = _to_int(obj.get("count"), 0)
    per = _to_float(obj.get("per_question_marks"), 0.0)
    if per <= 0:
        per = _to_float(obj.get("per"), 0.0)
    total = _to_float(obj.get("total_marks"), 0.0)
    if total <= 0:
        total = _to_float(obj.get("total"), 0.0)
    return count > 0 and per > 0 and total > 0


def _normalize_visual_payload(payload: Dict[str, Any], page_offset: int, page_count: int) -> Dict[str, Any]:
    def _norm_page(value: Any) -> int:
        raw = _to_int(value, -1)
        if raw < 0:
            return page_offset
        if page_offset > 0 and raw < page_offset and 0 <= raw < max(1, page_count):
            return raw + page_offset
        return raw

    out = {
        "questions": [],
        "subparts": [],
        "margin_marks": [],
        "section_math": [],
        "or_connectors": [],
        "headers": [],
        "header_total": None,
    }
    if not isinstance(payload, dict):
        return out

    for row in payload.get("questions") or []:
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("number"), 0)
        if qn <= 0:
            continue
        out["questions"].append(
            {
                "number": qn,
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "page": _norm_page(row.get("page_index")),
                "confidence": round(_to_float(row.get("confidence"), 0.0), 4),
            }
        )

    for row in payload.get("subparts") or []:
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("q"), 0)
        label = str(row.get("label") or "").strip()
        if qn <= 0 or not label:
            continue
        out["subparts"].append(
            {
                "q": qn,
                "label": label,
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "page": _norm_page(row.get("page_index")),
                "confidence": round(_to_float(row.get("confidence"), 0.0), 4),
            }
        )

    for row in payload.get("margin_marks") or []:
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("q"), 0)
        if qn <= 0:
            continue
        out["margin_marks"].append(
            {
                "q": qn,
                "sub": row.get("sub"),
                "marks": round(_to_float(row.get("marks"), 0.0), 4),
                "text": row.get("text") or row.get("raw"),
                "split": row.get("split"),
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "page": _norm_page(row.get("page_index")),
                "confidence": round(_to_float(row.get("confidence"), 0.0), 4),
            }
        )

    for row in payload.get("section_math_rules") or []:
        if not isinstance(row, dict):
            continue
        count = _to_int(row.get("count"), 0)
        per = _to_float(row.get("per"), 0.0)
        total = _to_float(row.get("total"), 0.0)
        if count <= 0 or per <= 0 or total <= 0:
            continue
        out["section_math"].append(
            {
                "count": count,
                "per": round(per, 4),
                "total": round(total, 4),
                "range": {
                    "start": _to_int(row.get("start_question"), 0),
                    "end": _to_int(row.get("start_question"), 0) + count - 1,
                },
                "expr": str(row.get("expression") or f"{count} x {round(per, 4)} = {round(total, 4)}"),
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "page": _norm_page(row.get("page_index")),
                "confidence": round(_to_float(row.get("confidence"), 0.0), 4),
            }
        )

    for row in payload.get("or_pairs") or []:
        if not isinstance(row, dict):
            continue
        q1 = _to_int(row.get("q1"), 0)
        q2 = _to_int(row.get("q2"), 0)
        if q1 <= 0 or q2 <= 0:
            continue
        out["or_connectors"].append(
            {
                "q1": q1,
                "q2": q2,
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "page": _norm_page(row.get("page_index")),
                "confidence": round(_to_float(row.get("confidence"), 0.0), 4),
            }
        )

    for row in payload.get("headers") or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        out["headers"].append(
            {
                "kind": str(row.get("kind") or "section"),
                "text": text,
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "page": _norm_page(row.get("page_index")),
                "confidence": round(_to_float(row.get("confidence"), 0.0), 4),
            }
        )

    if "header_total" in payload and isinstance(payload.get("header_total"), dict):
        out["header_total"] = payload.get("header_total")

    return out
    return bool(
        str(obj.get("expression") or "").strip()
        and (
            _to_int(obj.get("question_count"), 0) > 0
            or _to_float(obj.get("per_question_marks"), 0.0) > 0
            or _to_float(obj.get("total_marks"), 0.0) > 0
        )
    )


def _extract_partial_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    snippets = _extract_balanced_json_candidates(raw_text, max_candidates=4096)
    if not snippets:
        return None

    questions_by_number: Dict[int, Dict[str, Any]] = {}
    section_math_blocks: List[Dict[str, Any]] = []
    section_math_seen: set[Tuple[str, int, float, float]] = set()

    for snippet in snippets:
        parsed = _parse_any_json_value(snippet)
        if parsed is None:
            continue

        # Direct payload style.
        payload = _as_payload_dict(parsed)
        if isinstance(payload, dict):
            for q in (payload.get("questions") or []):
                if not isinstance(q, dict):
                    continue
                qn = _to_int(q.get("number"), 0)
                if qn <= 0:
                    continue
                if qn not in questions_by_number:
                    questions_by_number[qn] = dict(q)
                else:
                    questions_by_number[qn] = _merge_questions(questions_by_number[qn], q)
            for b in (payload.get("section_math_blocks") or []):
                if not isinstance(b, dict):
                    continue
                key = (
                    str(b.get("expression") or "").strip(),
                    _to_int(b.get("question_count"), 0),
                    round(_to_float(b.get("per_question_marks"), 0.0), 4),
                    round(_to_float(b.get("total_marks"), 0.0), 4),
                )
                if key in section_math_seen:
                    continue
                section_math_seen.add(key)
                section_math_blocks.append(dict(b))
            continue

        # Question object style.
        if isinstance(parsed, dict) and _looks_like_question_dict(parsed):
            qn = _to_int(parsed.get("number"), 0)
            if qn not in questions_by_number:
                questions_by_number[qn] = dict(parsed)
            else:
                questions_by_number[qn] = _merge_questions(questions_by_number[qn], parsed)
            continue

        # Section-math object style.
        if isinstance(parsed, dict) and _looks_like_section_math_block(parsed):
            key = (
                str(parsed.get("expression") or "").strip(),
                _to_int(parsed.get("question_count"), 0),
                round(_to_float(parsed.get("per_question_marks"), 0.0), 4),
                round(_to_float(parsed.get("total_marks"), 0.0), 4),
            )
            if key not in section_math_seen:
                section_math_seen.add(key)
                section_math_blocks.append(dict(parsed))
            continue

    if not questions_by_number and not section_math_blocks:
        return None

    ordered_questions = [questions_by_number[n] for n in sorted(questions_by_number.keys())]
    return {
        "questions": ordered_questions,
        "section_math_blocks": section_math_blocks,
        "total_questions": len(ordered_questions),
        "total_marks": sum(_to_float(q.get("marks"), 0.0) for q in ordered_questions),
        "effective_total_marks": 0.0,
        "numbering_contiguous": False,
    }


def _try_parse_candidate(candidate: str) -> Optional[Dict[str, Any]]:
    if not candidate:
        return None

    parsed = _parse_any_json_value(candidate)
    payload = _as_payload_dict(parsed)
    if payload is not None:
        return payload
    return None


def _parse_json_object(raw_text: str) -> Dict[str, Any]:
    if not raw_text:
        raise ValueError("empty_llm_response")

    text = raw_text.strip()
    candidates: List[str] = [text]
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw_text, flags=re.IGNORECASE):
        block = (match.group(1) or "").strip()
        if block:
            candidates.append(block)

    # Add balanced JSON snippets found anywhere in output.
    candidates.extend(_extract_balanced_json_candidates(raw_text))

    # Add broad regex snippets for common wrappers.
    obj_match = re.search(r"\{\s*\"questions\"[\s\S]*\}", raw_text)
    if obj_match:
        candidates.append(obj_match.group(0).strip())
    arr_match = re.search(r"\[[\s\S]*\]", raw_text)
    if arr_match:
        candidates.append(arr_match.group(0).strip())

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        parsed = _try_parse_candidate(candidate)
        if parsed is not None:
            return parsed

    partial = _extract_partial_payload(raw_text)
    if partial:
        logger.warning(
            "STRUCTURE_JSON_PARTIAL_RECOVERY questions=%s section_math_blocks=%s",
            len(partial.get("questions") or []),
            len(partial.get("section_math_blocks") or []),
        )
        return partial

    preview = text[:400].replace("\n", "\\n")
    logger.warning(
        "STRUCTURE_JSON_PARSE_FAILED len=%s preview=%s",
        len(raw_text or ""),
        preview,
    )

    raise ValueError("invalid_json_response")


def _parse_visual_json_object(raw_text: str) -> Dict[str, Any]:
    if not raw_text:
        raise ValueError("empty_llm_response")

    text = raw_text.strip()
    candidates: List[str] = [text]
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw_text, flags=re.IGNORECASE):
        block = (match.group(1) or "").strip()
        if block:
            candidates.append(block)

    candidates.extend(_extract_balanced_json_candidates(raw_text))
    arr_match = re.search(r"\[[\s\S]*\]", raw_text)
    if arr_match:
        candidates.append(arr_match.group(0).strip())
    obj_match = re.search(r"\{[\s\S]*\}", raw_text)
    if obj_match:
        candidates.append(obj_match.group(0).strip())

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        parsed = _parse_any_json_value(candidate)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            if len(parsed) == 1 and isinstance(parsed[0], dict):
                return parsed[0]
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                if any(k in item for k in ("questions", "subparts", "margin_marks", "section_math_rules", "or_pairs", "headers")):
                    return item

    preview = text[:400].replace("\n", "\\n")
    logger.warning(
        "VISUAL_JSON_PARSE_FAILED len=%s preview=%s",
        len(raw_text or ""),
        preview,
    )
    raise ValueError("invalid_json_response")


def _normalize_type(value: Any) -> str:
    t = str(value or "descriptive").strip().lower()
    if t in _ALLOWED_TYPES:
        return t
    alias = {
        "objective": "mcq",
        "fill in the blank": "fill_blank",
        "fill_in_the_blank": "fill_blank",
        "very short": "very_short",
        "short answer": "short",
        "long answer": "long",
        "theory": "descriptive",
        "or": "or_group",
    }
    return alias.get(t, "descriptive")


def _normalize_batch_payload(payload: Dict[str, Any], page_offset: int) -> Dict[str, Any]:
    payload = payload or {}
    questions = payload.get("questions") or []
    normalized_questions: List[Dict[str, Any]] = []
    section_math_blocks: List[Dict[str, Any]] = []

    for q in questions:
        if not isinstance(q, dict):
            continue
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue

        subquestions: List[Dict[str, Any]] = []
        for sq in (q.get("subquestions") or []):
            if not isinstance(sq, dict):
                continue
            label = str(sq.get("label") or "").strip()
            if not label:
                continue
            subquestions.append(
                {
                    "label": label,
                    "text": str(sq.get("text") or "").strip(),
                    # Layer-2 semantic extraction must not assign marks.
                    "marks": 0.0,
                    "mark_source": "inferred",
                    "mark_confidence": 0.0,
                    "confidence": _to_float(sq.get("confidence"), 0.0),
                    "image_evidence": list(sq.get("image_evidence") or []),
                }
            )

        evidence = []
        for ev in (q.get("image_evidence") or []):
            if not isinstance(ev, dict):
                continue
            try:
                page_index = int(ev.get("page_index", 0)) + page_offset
            except Exception:
                page_index = page_offset
            evidence.append(
                {
                    "page_index": max(0, page_index),
                    "bbox": ev.get("bbox"),
                    "visual_confidence": _to_float(ev.get("visual_confidence"), 0.0),
                }
            )

        normalized_questions.append(
            {
                "number": qn,
                "section": (str(q.get("section") or "").strip() or None),
                "instruction": (str(q.get("instruction") or "").strip() or None),
                "question_text": str(q.get("question_text") or "").strip(),
                "question_type": _normalize_type(q.get("question_type")),
                # Layer-2 semantic extraction must not assign marks.
                "marks": 0.0,
                "mark_source": "inferred",
                "mark_confidence": 0.0,
                "options": list(q.get("options") or []) or None,
                "subquestions": subquestions,
                # OR groups are resolved from visual layer.
                "or_group_id": None,
                "image_evidence": evidence,
                "ai_confidence": _to_float(q.get("ai_confidence", q.get("confidence")), 0.0),
                "confidence": _to_float(q.get("confidence", q.get("ai_confidence")), 0.0),
            }
        )

    return {
        "questions": normalized_questions,
        # Stage-2 semantic layer does not emit section math blocks.
        "section_math_blocks": section_math_blocks,
        "total_questions": int(payload.get("total_questions") or len(normalized_questions)),
        "total_marks": 0.0,
        "effective_total_marks": 0.0,
        "numbering_contiguous": bool(payload.get("numbering_contiguous", False)),
    }


def _merge_questions(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    if len(str(incoming.get("question_text") or "")) > len(str(merged.get("question_text") or "")):
        merged["question_text"] = incoming.get("question_text")

    if incoming.get("instruction") and not merged.get("instruction"):
        merged["instruction"] = incoming.get("instruction")
    if incoming.get("section") and not merged.get("section"):
        merged["section"] = incoming.get("section")
    if incoming.get("question_type") and merged.get("question_type") == "descriptive":
        merged["question_type"] = incoming.get("question_type")

    # Prefer higher confidence marks value, fallback max.
    in_marks = _to_float(incoming.get("marks"), 0.0)
    ex_marks = _to_float(merged.get("marks"), 0.0)
    in_conf = _to_float(incoming.get("ai_confidence"), 0.0)
    ex_conf = _to_float(merged.get("ai_confidence"), 0.0)
    if (in_marks > 0 and ex_marks <= 0) or (in_conf > ex_conf and in_marks > 0) or (in_marks > ex_marks):
        merged["marks"] = in_marks
        merged["mark_source"] = str(incoming.get("mark_source") or merged.get("mark_source") or "inferred").strip().lower()
        merged["mark_confidence"] = _to_float(incoming.get("mark_confidence"), _to_float(merged.get("mark_confidence"), 0.0))

    existing_evidence = list(merged.get("image_evidence") or [])
    seen = {
        (
            int(ev.get("page_index", -1)),
            tuple(ev.get("bbox") or []),
        )
        for ev in existing_evidence
        if isinstance(ev, dict)
    }
    for ev in (incoming.get("image_evidence") or []):
        if not isinstance(ev, dict):
            continue
        key = (int(ev.get("page_index", -1)), tuple(ev.get("bbox") or []))
        if key in seen:
            continue
        seen.add(key)
        existing_evidence.append(ev)
    merged["image_evidence"] = existing_evidence

    sub_by_label = {str(sq.get("label")): dict(sq) for sq in (merged.get("subquestions") or [])}
    for sq in (incoming.get("subquestions") or []):
        label = str(sq.get("label") or "").strip()
        if not label:
            continue
        if label not in sub_by_label:
            sub_by_label[label] = dict(sq)
            continue
        ex_sq = sub_by_label[label]
        if len(str(sq.get("text") or "")) > len(str(ex_sq.get("text") or "")):
            ex_sq["text"] = sq.get("text")
        if _to_float(sq.get("marks"), 0.0) > _to_float(ex_sq.get("marks"), 0.0):
            ex_sq["marks"] = _to_float(sq.get("marks"), 0.0)
        ex_ev = list(ex_sq.get("image_evidence") or [])
        ex_sq["image_evidence"] = ex_ev + [
            ev for ev in (sq.get("image_evidence") or []) if ev not in ex_ev
        ]
        ex_sq["confidence"] = max(
            _to_float(ex_sq.get("confidence"), 0.0),
            _to_float(sq.get("confidence"), 0.0),
        )
        sub_by_label[label] = ex_sq
    merged["subquestions"] = sorted(sub_by_label.values(), key=lambda s: str(s.get("label") or ""))

    merged["ai_confidence"] = max(ex_conf, in_conf)
    merged["confidence"] = max(
        _to_float(merged.get("confidence"), ex_conf),
        _to_float(incoming.get("confidence"), in_conf),
    )
    return merged


async def _build_raw_ocr_text(images: List[str]) -> str:
    ocr = get_ocr_provider()
    lines: List[str] = []
    for idx, img in enumerate(images):
        try:
            res = ocr.detect(img)
            page_lines = [str(row.get("text") or "").strip() for row in (res.get("lines") or [])]
            page_lines = [ln for ln in page_lines if ln]
            if page_lines:
                lines.append(f"[PAGE {idx + 1}]")
                lines.extend(page_lines)
        except Exception as exc:
            logger.warning("AI structured OCR pre-pass failed on page %s: %s", idx + 1, exc)
    return "\n".join(lines)


def _extract_ocr_question_anchors(images: List[str]) -> List[Dict[str, Any]]:
    ocr = get_ocr_provider()
    anchors: List[Dict[str, Any]] = []
    pattern = re.compile(r"^\s*(\d{1,3})\s*[\).]")
    for idx, img in enumerate(images):
        try:
            res = ocr.detect(img)
        except Exception as exc:
            logger.warning("OCR anchor pass failed on page %s: %s", idx + 1, exc)
            continue
        for row in (res.get("lines") or []):
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            if re.match(r"^\s*\d{1,3}\s*[x×*]\s*\d", text, flags=re.IGNORECASE):
                continue
            m = pattern.match(text)
            if not m:
                continue
            qn = _to_int(m.group(1), 0)
            if qn <= 0 or qn > 300:
                continue
            bbox = list(row.get("bbox") or row.get("bounding_box") or [0, 0, 0, 0])
            if len(bbox) != 4:
                bbox = [0, 0, 0, 0]
            anchors.append(
                {
                    "number": qn,
                    "bbox": bbox,
                    "page": idx,
                    "confidence": _to_float(row.get("confidence"), 0.6),
                    "source": "ocr",
                }
            )
    return anchors


def _extract_structured_question_anchors(structure: Dict[str, Any]) -> List[Dict[str, Any]]:
    anchors: List[Dict[str, Any]] = []
    for q in (structure or {}).get("questions") or []:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        best: Optional[Dict[str, Any]] = None
        for ev in (q.get("image_evidence") or []):
            if not isinstance(ev, dict):
                continue
            page = _to_int(ev.get("page_index"), -1)
            bbox = list(ev.get("bbox") or [])
            if page < 0 or len(bbox) != 4:
                continue
            conf = _to_float(ev.get("visual_confidence"), 0.0)
            if best is None or conf > best["confidence"]:
                best = {
                    "number": qn,
                    "bbox": bbox,
                    "page": page,
                    "confidence": conf,
                    "source": "structured",
                }
        if best:
            anchors.append(best)
    return anchors


def _merge_question_anchors(
    visual_questions: List[Dict[str, Any]],
    ocr_anchors: List[Dict[str, Any]],
    structured_anchors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    for row in visual_questions:
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("number"), 0)
        if qn <= 0:
            continue
        candidates.append(
            {
                "number": qn,
                "bbox": list(row.get("bbox") or [0, 0, 0, 0]),
                "page": _to_int(row.get("page"), -1),
                "confidence": _to_float(row.get("confidence"), 0.0),
                "source": str(row.get("source") or "visual"),
            }
        )

    candidates.extend([dict(a) for a in (ocr_anchors or [])])
    candidates.extend([dict(a) for a in (structured_anchors or [])])

    by_number: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for cand in candidates:
        qn = _to_int(cand.get("number"), 0)
        if qn <= 0:
            continue
        by_number[qn].append(cand)

    merged: List[Dict[str, Any]] = []
    for qn, items in by_number.items():
        if not items:
            continue
        visuals = [it for it in items if str(it.get("source") or "").lower() == "visual"]
        ocrs = [it for it in items if str(it.get("source") or "").lower() == "ocr"]
        if visuals:
            candidates = visuals
            final_source = "visual"
        elif ocrs:
            candidates = ocrs
            final_source = "ocr"
        else:
            candidates = items
            final_source = "merged"

        centers: List[Tuple[float, float, int]] = []
        for idx, item in enumerate(candidates):
            bbox = item.get("bbox") or [0, 0, 0, 0]
            if len(bbox) != 4:
                bbox = [0, 0, 0, 0]
            cx = (float(bbox[0]) + float(bbox[2])) / 2.0
            cy = (float(bbox[1]) + float(bbox[3])) / 2.0
            centers.append((cx, cy, idx))

        supports: List[int] = []
        for idx, (cx, cy, _) in enumerate(centers):
            page = _to_int(candidates[idx].get("page"), -1)
            count = 0
            for ox, oy, jdx in centers:
                if _to_int(candidates[jdx].get("page"), -1) != page:
                    continue
                if abs(cx - ox) + abs(cy - oy) <= 30.0:
                    count += 1
            supports.append(count)

        best_idx = max(
            range(len(candidates)),
            key=lambda i: (
                supports[i],
                _to_float(candidates[i].get("confidence"), 0.0),
            ),
        )
        best = candidates[best_idx]
        best["source"] = final_source
        merged.append(best)

    merged.sort(key=lambda r: _to_int(r.get("number"), 0))
    return merged


def _extract_header_total_hint(raw_ocr_text: str) -> Tuple[Optional[float], bool, float, Optional[str]]:
    """
    Parse header total marks from OCR support text.
    Returns (marks, reliable, confidence, source).
    """
    text = (raw_ocr_text or "").strip()
    if not text:
        return None, False, 0.0, None

    # Strong headers.
    strong_patterns = [
        r"\bmax(?:imum)?\.?\s*marks?\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\b",
        r"\bm\.?\s*m\.?\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\b",
    ]
    for pat in strong_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if not m:
            continue
        mark = _to_float(m.group(1), 0.0)
        if mark > 0:
            return round(mark, 4), True, 0.95, "header_ocr"

    # Weaker signal.
    m = re.search(r"\btotal\s+marks?\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\b", text, flags=re.IGNORECASE)
    if m:
        mark = _to_float(m.group(1), 0.0)
        if mark > 0:
            return round(mark, 4), False, 0.6, "header_ocr_total"

    return None, False, 0.0, None


def _extract_header_total_from_images(
    images: List[str],
) -> Tuple[Optional[float], bool, float, Optional[str]]:
    """Detect header total marks from the top region of the first page."""
    if not images:
        return None, False, 0.0, None

    try:
        img_b64 = images[0]
        img_bytes = base64.b64decode(img_b64)
        with Image.open(io.BytesIO(img_bytes)) as im:
            width, height = im.size
        if height <= 0:
            return None, False, 0.0, None

        ocr = get_ocr_provider()
        res = ocr.detect(img_b64, min_conf=0.3, min_words=1, min_lines=1, allow_fallback=True)
        lines = res.get("lines") or []

        header_lines: List[Tuple[float, float, str]] = []
        for row in lines:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            bbox = row.get("bbox") or row.get("bounding_box") or [0, 0, 0, 0]
            if len(bbox) != 4:
                continue
            y1 = float(bbox[1])
            y2 = float(bbox[3])
            if y2 <= height * 0.3:
                x1 = float(bbox[0])
                header_lines.append((y1, x1, text))

        if not header_lines:
            return None, False, 0.0, None

        header_lines.sort(key=lambda r: (r[0], r[1]))
        header_text = " ".join(item[2] for item in header_lines)

        strong_patterns = [
            r"\bmax(?:imum)?\.?\s*marks?\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\b",
            r"\bm\.?\s*m\.?\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\b",
            r"\btotal\s+marks?\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\b",
            r"\bmarks?\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\b",
            r"\b(\d{1,3}(?:\.\d+)?)\s*marks?\b",
        ]
        for pat in strong_patterns:
            m = re.search(pat, header_text, flags=re.IGNORECASE)
            if not m:
                continue
            mark = _to_float(m.group(1), 0.0)
            if mark > 0:
                # Header region + explicit "marks" => reliable.
                return round(mark, 4), True, 0.9, "header_region_ocr"
    except Exception as exc:
        logger.warning("HEADER_TOTAL_OCR_FAILED error=%s", exc)

    return None, False, 0.0, None


def _build_or_groups_from_visual(visual_entities: Dict[str, Any]) -> Dict[int, str]:
    edges: List[Tuple[int, int]] = []
    for row in (visual_entities or {}).get("or_connectors") or []:
        if not isinstance(row, dict):
            continue
        q1 = _to_int(row.get("q1"), 0)
        q2 = _to_int(row.get("q2"), 0)
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
        union(a, b)

    comps: Dict[int, List[int]] = defaultdict(list)
    for node in list(parent.keys()):
        comps[find(node)].append(node)

    out: Dict[int, str] = {}
    gid_seq = 1
    for _, members in sorted(comps.items(), key=lambda kv: min(kv[1])):
        uniq = sorted(set(int(m) for m in members if int(m) > 0))
        if len(uniq) < 2:
            continue
        gid = f"visual_or_{gid_seq}"
        gid_seq += 1
        for qn in uniq:
            out[qn] = gid
    return out


def _semantic_structure_from_visual_entities(visual_entities: Dict[str, Any]) -> Dict[str, Any]:
    questions: List[Dict[str, Any]] = []
    sub_by_q: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in (visual_entities or {}).get("subparts") or []:
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("q"), 0)
        label = str(row.get("label") or "").strip()
        if qn <= 0 or not label:
            continue
        sub_by_q[qn].append(
            {
                "label": label,
                "text": "",
                "marks": 0.0,
                "mark_source": "inferred",
                "mark_confidence": 0.0,
                "confidence": _to_float(row.get("confidence"), 0.0),
                "image_evidence": [
                    {
                        "page_index": _to_int(row.get("page"), 0),
                        "bbox": row.get("bbox"),
                        "visual_confidence": _to_float(row.get("confidence"), 0.0),
                    }
                ],
            }
        )

    for row in sorted((visual_entities or {}).get("questions") or [], key=lambda r: _to_int((r or {}).get("number"), 0)):
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("number"), 0)
        if qn <= 0:
            continue
        questions.append(
            {
                "number": qn,
                "section": None,
                "instruction": None,
                "question_text": "",
                "question_type": "descriptive",
                "marks": 0.0,
                "mark_source": "inferred",
                "mark_confidence": 0.0,
                "options": None,
                "subquestions": sorted(sub_by_q.get(qn) or [], key=lambda sq: str(sq.get("label") or "")),
                "or_group_id": None,
                "image_evidence": [
                    {
                        "page_index": _to_int(row.get("page"), 0),
                        "bbox": row.get("bbox"),
                        "visual_confidence": _to_float(row.get("confidence"), 0.0),
                    }
                ],
                "ai_confidence": _to_float(row.get("confidence"), 0.0),
                "confidence": _to_float(row.get("confidence"), 0.0),
            }
        )

    return normalize_structure_payload(
        {
            "questions": questions,
            "section_math_blocks": [],
            "total_questions": len(questions),
            "total_marks": 0.0,
            "effective_total_marks": 0.0,
            "numbering_contiguous": False,
        }
    )


def _merge_semantic_with_visual_entities(stage2_structure: Dict[str, Any], visual_entities: Dict[str, Any]) -> Dict[str, Any]:
    def _demote_choice_subparts(question: Dict[str, Any]) -> bool:
        subparts = list(question.get("subquestions") or [])
        if not subparts:
            return False
        qtype = str((question or {}).get("question_type") or "").strip().lower()
        if qtype in {"passage", "passage_subparts"}:
            return False

        # Explicit subpart marks indicate real subquestions.
        for sq in subparts:
            if _to_float(sq.get("marks"), 0.0) > 0 and str(sq.get("mark_source") or "").strip().lower() in {
                "margin",
                "section_math",
                "instruction",
            }:
                return False

        raw_text = f"{question.get('instruction') or ''}\n{question.get('question_text') or ''}"
        text = raw_text.lower()
        choice_phrases = [
            "any one",
            "any of the following",
            "attempt any one",
            "choose any one",
            "either of the following",
            "alternative question",
            "in lieu of",
        ]
        has_choice_signal = any(phrase in text for phrase in choice_phrases)
        if not has_choice_signal and re.search(r"(^|\n)\s*or\s*(\n|$)", raw_text, flags=re.IGNORECASE):
            has_choice_signal = True
        if qtype == "mcq":
            has_choice_signal = True

        if not has_choice_signal:
            return False

        options = list(question.get("options") or [])
        for sq in subparts:
            opt = str(sq.get("text") or "").strip()
            if opt and opt not in options:
                options.append(opt)
        if options:
            question["options"] = options
        # Drop subquestions to avoid splitting marks for choice-only prompts.
        question["subquestions"] = []
        return True

    def _allows_visual_subparts(question: Dict[str, Any]) -> bool:
        qtype = str((question or {}).get("question_type") or "").strip().lower()
        # Visual a/b/c/d labels are commonly MCQ options, not structural subparts.
        if qtype in {"mcq", "fill_blank", "very_short", "writing", "letter", "essay"}:
            return False
        options = (question or {}).get("options")
        if isinstance(options, list) and len(options) >= 2:
            return False
        return qtype in {"short", "long", "passage", "passage_subparts", "descriptive_choice", "or_group"}

    normalized = normalize_structure_payload(stage2_structure or {})
    q_by_num: Dict[int, Dict[str, Any]] = {
        _to_int(q.get("number"), 0): dict(q)
        for q in (normalized.get("questions") or [])
        if _to_int(q.get("number"), 0) > 0
    }
    visual_subparts_exist = bool((visual_entities or {}).get("subparts") or [])
    visual_labels_by_q: Dict[int, set[str]] = defaultdict(set)
    for row in (visual_entities or {}).get("subparts") or []:
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("q"), 0)
        label = str(row.get("label") or "").strip()
        if qn <= 0 or not label:
            continue
        visual_labels_by_q[qn].add(label.lower())

    # Visual entities are source-of-truth when labels are available for a question.
    if visual_subparts_exist:
        for qn, q in list(q_by_num.items()):
            if not _allows_visual_subparts(q):
                continue
            keep_labels = visual_labels_by_q.get(qn) or set()
            if keep_labels:
                filtered = []
                for sq in (q.get("subquestions") or []):
                    lbl = str(sq.get("label") or "").strip().lower()
                    if lbl and lbl in keep_labels:
                        filtered.append(sq)
                q["subquestions"] = filtered
            q_by_num[qn] = q

    # Ensure every visual question exists.
    for row in (visual_entities or {}).get("questions") or []:
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("number"), 0)
        if qn <= 0:
            continue
        if qn not in q_by_num:
            q_by_num[qn] = {
                "number": qn,
                "section": None,
                "instruction": None,
                "question_text": "",
                "question_type": "descriptive",
                "marks": 0.0,
                "mark_source": "inferred",
                "mark_confidence": 0.0,
                "options": None,
                "subquestions": [],
                "or_group_id": None,
                "image_evidence": [],
                "ai_confidence": 0.0,
                "confidence": 0.0,
            }
        q = q_by_num[qn]
        ev = {
            "page_index": _to_int(row.get("page"), 0),
            "bbox": row.get("bbox"),
            "visual_confidence": _to_float(row.get("confidence"), 0.0),
        }
        existing = list(q.get("image_evidence") or [])
        if ev not in existing:
            existing.append(ev)
        q["image_evidence"] = existing
        q_by_num[qn] = q

    # Ensure every visual subpart exists.
    for row in (visual_entities or {}).get("subparts") or []:
        if not isinstance(row, dict):
            continue
        qn = _to_int(row.get("q"), 0)
        label = str(row.get("label") or "").strip()
        if qn <= 0 or not label:
            continue
        q = q_by_num.get(qn)
        if not q:
            continue
        if not _allows_visual_subparts(q):
            continue
        subparts = list(q.get("subquestions") or [])
        if not any(str(sq.get("label") or "").strip().lower() == label.lower() for sq in subparts):
            subparts.append(
                {
                    "label": label,
                    "text": "",
                    "marks": 0.0,
                    "mark_source": "inferred",
                    "mark_confidence": 0.0,
                    "confidence": _to_float(row.get("confidence"), 0.0),
                    "image_evidence": [
                        {
                            "page_index": _to_int(row.get("page"), 0),
                            "bbox": row.get("bbox"),
                            "visual_confidence": _to_float(row.get("confidence"), 0.0),
                        }
                    ],
                }
            )
        q["subquestions"] = sorted(subparts, key=lambda sq: str(sq.get("label") or ""))
        q_by_num[qn] = q

    # Apply OR groups from visual connectors.
    or_map = _build_or_groups_from_visual(visual_entities)
    for qn, gid in or_map.items():
        if qn in q_by_num:
            q_by_num[qn]["or_group_id"] = gid

    # Demote choice-style subparts (e.g., "any one", alternatives, MCQ options).
    for qn, q in list(q_by_num.items()):
        if _demote_choice_subparts(q):
            q_by_num[qn] = q

    # Section math from visual layer.
    section_math_blocks: List[Dict[str, Any]] = []
    for row in (visual_entities or {}).get("section_math") or []:
        if not isinstance(row, dict):
            continue
        range_raw = row.get("range")
        range_obj = None
        if isinstance(range_raw, dict):
            start = _to_int(range_raw.get("start"), 0)
            end = _to_int(range_raw.get("end"), 0)
            if start > 0 and end >= start:
                range_obj = {"start": start, "end": end}
        section_math_blocks.append(
            {
                "section": None,
                "expression": str(row.get("expr") or ""),
                "question_count": _to_int(row.get("count"), 0),
                "per_question_marks": _to_float(row.get("per"), 0.0),
                "total_marks": _to_float(row.get("total"), 0.0),
                "page_index": _to_int(row.get("page"), 0),
                "confidence": _to_float(row.get("confidence"), 0.0),
                "range": range_obj,
            }
        )

    merged = {
        "questions": [q_by_num[k] for k in sorted(q_by_num.keys())],
        "section_math_blocks": section_math_blocks,
        "total_questions": len(q_by_num),
        "total_marks": 0.0,
        "effective_total_marks": 0.0,
        "numbering_contiguous": True,
    }
    return normalize_structure_payload(merged)


def _clip_to_expected_question_count(
    structure: Dict[str, Any],
    visual_entities: Dict[str, Any],
    expected_question_count: Optional[int],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    expected = _to_int(expected_question_count, 0)
    if expected <= 0:
        return structure, visual_entities

    normalized = normalize_structure_payload(structure or {})
    kept_questions = []
    for q in (normalized.get("questions") or []):
        qn = _to_int(q.get("number"), 0)
        if 1 <= qn <= expected:
            kept_questions.append(q)

    # De-duplicate by question number after clipping.
    by_num: Dict[int, Dict[str, Any]] = {}
    for q in kept_questions:
        qn = _to_int(q.get("number"), 0)
        if qn <= 0:
            continue
        if qn not in by_num:
            by_num[qn] = q
        else:
            by_num[qn] = _merge_questions(by_num[qn], q)

    normalized["questions"] = [by_num[n] for n in sorted(by_num.keys())]
    normalized["total_questions"] = len(normalized["questions"])

    ve = dict(visual_entities or {})
    ve["questions"] = [
        row for row in (ve.get("questions") or [])
        if 1 <= _to_int((row or {}).get("number"), 0) <= expected
    ]
    ve["subparts"] = [
        row for row in (ve.get("subparts") or [])
        if 1 <= _to_int((row or {}).get("q"), 0) <= expected
    ]
    ve["margin_marks"] = [
        row for row in (ve.get("margin_marks") or [])
        if 1 <= _to_int((row or {}).get("q"), 0) <= expected
    ]
    ve["or_connectors"] = [
        row for row in (ve.get("or_connectors") or [])
        if 1 <= _to_int((row or {}).get("q1"), 0) <= expected
        and 1 <= _to_int((row or {}).get("q2"), 0) <= expected
    ]
    return normalized, ve


async def _call_extraction_llm(images: List[str], prompt: str, model_name: str) -> Dict[str, Any]:
    api_key = get_llm_api_key()
    if not api_key:
        raise RuntimeError("missing_gemini_api_key")
    max_output_tokens = _to_int(os.getenv("AI_STRUCTURED_MAX_OUTPUT_TOKENS", "32768"), 32768)
    if max_output_tokens <= 0:
        max_output_tokens = 32768

    chat = LlmChat(
        api_key=api_key,
        session_id=f"ai_struct_extract_{uuid.uuid4().hex[:10]}",
        system_message=get_extraction_system_prompt(),
    ).with_model("gemini", model_name).with_params(
        temperature=0,
        response_mime_type="application/json",
        max_output_tokens=max_output_tokens,
    )

    message = UserMessage(
        text=prompt,
        file_contents=[ImageContent(image_base64=img) for img in images],
    )
    raw = await chat.send_message(message)
    try:
        return _parse_json_object(raw)
    except ValueError as exc:
        # Never hard-fail extraction for malformed model JSON; caller can continue with
        # visual-only structure and deterministic mark reasoning.
        if "invalid_json_response" in str(exc):
            logger.warning("STRUCTURE_JSON_PARSE_RECOVERED fallback=empty_payload")
            return {"questions": [], "section_math_blocks": []}
        raise


async def _call_visual_extraction_llm(images: List[str], prompt: str, model_name: str) -> Dict[str, Any]:
    api_key = get_llm_api_key()
    if not api_key:
        raise RuntimeError("missing_gemini_api_key")
    max_output_tokens = _to_int(os.getenv("AI_STRUCTURED_MAX_OUTPUT_TOKENS", "32768"), 32768)
    if max_output_tokens <= 0:
        max_output_tokens = 32768

    chat = LlmChat(
        api_key=api_key,
        session_id=f"ai_struct_visual_{uuid.uuid4().hex[:10]}",
        system_message=get_visual_extraction_system_prompt(),
    ).with_model("gemini", model_name).with_params(
        temperature=0,
        response_mime_type="application/json",
        max_output_tokens=max_output_tokens,
    )

    message = UserMessage(
        text=prompt,
        file_contents=[ImageContent(image_base64=img) for img in images],
    )
    raw = await chat.send_message(message)
    try:
        return _parse_visual_json_object(raw)
    except ValueError as exc:
        if "invalid_json_response" in str(exc):
            logger.warning("VISUAL_JSON_PARSE_RECOVERED fallback=empty_payload")
            return {
                "questions": [],
                "subparts": [],
                "margin_marks": [],
                "section_math_rules": [],
                "or_pairs": [],
                "headers": [],
            }
        raise


async def extract_question_structure(
    *,
    question_paper_images: List[str],
    raw_ocr_text: Optional[str] = None,
    expected_total_marks: Optional[float] = None,
    expected_question_count: Optional[int] = None,
    max_retries: int = 3,
    model_name: str = "gemini-2.5-flash",
) -> Tuple[Dict[str, Any], Dict[str, Any], str, int]:
    """Extract question structure with layered visual+semantic pipeline."""

    if not question_paper_images:
        raise ValueError("question_paper_images_required")

    # Layer 1: multimodal visual evidence (Gemini Vision), fallback to OCR visual layer.
    batch_size = max(1, int(os.getenv("AI_STRUCTURED_PAGE_BATCH_SIZE", "4")))
    chunks: List[Tuple[int, List[str]]] = []
    for i in range(0, len(question_paper_images), batch_size):
        chunks.append((i, question_paper_images[i:i + batch_size]))

    async def _extract_visual_chunk(start_idx: int, chunk_images: List[str], idx: int, total: int) -> Dict[str, Any]:
        prompt = build_visual_extraction_prompt(
            batch_index=idx,
            total_batches=total,
            page_offset=start_idx,
        )
        try:
            payload = await _call_visual_extraction_llm(chunk_images, prompt, model_name=model_name)
            return _normalize_visual_payload(payload, page_offset=start_idx, page_count=len(chunk_images))
        except Exception as exc:
            logger.warning("VISUAL_CHUNK_FAILED batch=%s/%s error=%s", idx, total, exc)
            return {
                "questions": [],
                "subparts": [],
                "margin_marks": [],
                "section_math": [],
                "or_connectors": [],
                "headers": [],
                "header_total": None,
            }

    async def _extract_all_visual_chunks() -> Dict[str, Any]:
        total = len(chunks)
        merged: Dict[str, Any] = {
            "questions": [],
            "subparts": [],
            "margin_marks": [],
            "section_math": [],
            "or_connectors": [],
            "headers": [],
            "header_total": None,
        }
        for idx, (start_idx, chunk_images) in enumerate(chunks, start=1):
            chunk_payload = await _extract_visual_chunk(start_idx, chunk_images, idx, total)
            merged["questions"].extend(chunk_payload.get("questions") or [])
            merged["subparts"].extend(chunk_payload.get("subparts") or [])
            merged["margin_marks"].extend(chunk_payload.get("margin_marks") or [])
            merged["section_math"].extend(chunk_payload.get("section_math") or [])
            merged["or_connectors"].extend(chunk_payload.get("or_connectors") or [])
            merged["headers"].extend(chunk_payload.get("headers") or [])
            if not merged.get("header_total") and chunk_payload.get("header_total"):
                merged["header_total"] = chunk_payload.get("header_total")
        return merged

    visual_entities: Dict[str, Any]
    try:
        visual_entities = await _extract_all_visual_chunks()
        if not any(visual_entities.get(k) for k in ("questions", "section_math", "margin_marks", "or_connectors")):
            raise RuntimeError("empty_visual_payload")
    except Exception as exc:
        logger.warning("VISUAL_ENTITIES_FAILED error=%s", exc)
        try:
            visual_entities = extract_visual_entities(question_paper_images, force_ocr_fallback=True)
        except Exception as exc2:
            logger.warning("VISUAL_OCR_FALLBACK_FAILED error=%s", exc2)
            visual_entities = {
                "questions": [],
                "subparts": [],
                "margin_marks": [],
                "section_math": [],
                "or_connectors": [],
                "headers": [],
                "header_total": None,
            }

    def _avg_conf(items: List[Dict[str, Any]]) -> float:
        vals = [float(row.get("confidence") or 0.0) for row in items if isinstance(row, dict)]
        if not vals:
            return 0.0
        return round(sum(vals) / float(len(vals)), 4)

    logger.info(
        "VISUAL_EVIDENCE_CONF questions=%s subparts=%s margin_marks=%s section_math=%s or_connectors=%s headers=%s avg_q=%.3f avg_sp=%.3f avg_mm=%.3f avg_sm=%.3f avg_or=%.3f avg_hd=%.3f",
        len((visual_entities or {}).get("questions") or []),
        len((visual_entities or {}).get("subparts") or []),
        len((visual_entities or {}).get("margin_marks") or []),
        len((visual_entities or {}).get("section_math") or []),
        len((visual_entities or {}).get("or_connectors") or []),
        len((visual_entities or {}).get("headers") or []),
        _avg_conf((visual_entities or {}).get("questions") or []),
        _avg_conf((visual_entities or {}).get("subparts") or []),
        _avg_conf((visual_entities or {}).get("margin_marks") or []),
        _avg_conf((visual_entities or {}).get("section_math") or []),
        _avg_conf((visual_entities or {}).get("or_connectors") or []),
        _avg_conf((visual_entities or {}).get("headers") or []),
    )

    if raw_ocr_text is None:
        raw_ocr_text = await _build_raw_ocr_text(question_paper_images)

    # Layer 2: Gemini semantic extraction only (marks ignored).

    prompt_extra_rules: List[str] = []
    expected_count = _to_int(expected_question_count, 0)
    if expected_count > 0:
        prompt_extra_rules.append(
            f"Expected question count = {expected_count}. Do not output question numbers outside 1..{expected_count}."
        )
    prompt_total_marks = None
    if expected_total_marks is not None and _to_float(expected_total_marks, 0.0) > 0:
        prompt_total_marks = round(_to_float(expected_total_marks, 0.0), 4)
    else:
        visual_header = (visual_entities or {}).get("header_total")
        if isinstance(visual_header, dict) and visual_header.get("reliable") and _to_float(visual_header.get("marks"), 0.0) > 0:
            prompt_total_marks = round(_to_float(visual_header.get("marks"), 0.0), 4)
    if prompt_total_marks is not None:
        prompt_extra_rules.append(
            f"Expected total marks = {prompt_total_marks}. Use only as consistency reference; do not assign marks."
        )

    async def _extract_chunk(start_idx: int, chunk_images: List[str], idx: int, total: int) -> Dict[str, Any]:
        prompt = build_extraction_prompt(
            raw_ocr_text=raw_ocr_text,
            batch_index=idx,
            total_batches=total,
            extra_rules=prompt_extra_rules,
        )
        try:
            payload = await _call_extraction_llm(chunk_images, prompt, model_name=model_name)
            return _normalize_batch_payload(payload, page_offset=start_idx)
        except Exception as exc:
            logger.warning("SEMANTIC_CHUNK_FAILED batch=%s/%s error=%s", idx, total, exc)
            return {
                "questions": [],
                "section_math_blocks": [],
                "total_questions": 0,
                "total_marks": 0.0,
                "effective_total_marks": 0.0,
                "numbering_contiguous": False,
            }

    async def _extract_all_chunks() -> Dict[str, Any]:
        total = len(chunks)

        async def _runner(item: Tuple[int, List[str]], idx: int) -> Dict[str, Any]:
            start_idx, imgs = item
            return await _extract_chunk(start_idx, imgs, idx, total)

        tasks = [asyncio.create_task(_runner(item, idx + 1)) for idx, item in enumerate(chunks)]
        batch_payloads = await asyncio.gather(*tasks)

        merged: Dict[int, Dict[str, Any]] = {}
        for payload in batch_payloads:
            for q in (payload.get("questions") or []):
                qn = _to_int(q.get("number"), 0)
                if qn <= 0:
                    continue
                if qn not in merged:
                    merged[qn] = dict(q)
                else:
                    merged[qn] = _merge_questions(merged[qn], q)

        consolidated = {
            "questions": [merged[k] for k in sorted(merged.keys())],
            "section_math_blocks": [],
            "total_questions": len(merged),
            "total_marks": 0.0,
            "effective_total_marks": 0.0,
            "numbering_contiguous": True,
        }
        return normalize_structure_payload(consolidated)

    retry_count = 0
    stage2_structure: Dict[str, Any]
    try:
        retry_result = await run_with_retry(
            name="STRUCTURE_EXTRACTION",
            max_attempts=max_retries,
            operation=lambda _attempt: _extract_all_chunks(),
        )
        stage2_structure = retry_result.value
        retry_count = retry_result.attempts - 1
    except RetryExhaustedError as exc:
        logger.error("STRUCTURE_EXTRACTION_FAILED reason=%s", exc)
        stage2_structure = {"questions": [], "section_math_blocks": [], "total_questions": 0, "total_marks": 0.0}
        retry_count = max_retries

    # If semantic extraction yields nothing, fallback to visual anchors.
    if not (stage2_structure.get("questions") or []):
        stage2_structure = _semantic_structure_from_visual_entities(visual_entities)

    stage2_structure = _merge_semantic_with_visual_entities(stage2_structure, visual_entities)
    stage2_structure, visual_entities = _clip_to_expected_question_count(
        stage2_structure,
        visual_entities,
        expected_question_count,
    )

    # Merge question anchors from visual + OCR + structured sources to avoid anchor drift.
    try:
        ocr_anchors = _extract_ocr_question_anchors(question_paper_images)
    except Exception as exc:
        logger.warning("OCR_ANCHOR_EXTRACTION_FAILED error=%s", exc)
        ocr_anchors = []
    try:
        structured_anchors = _extract_structured_question_anchors(stage2_structure)
    except Exception as exc:
        logger.warning("STRUCTURED_ANCHOR_EXTRACTION_FAILED error=%s", exc)
        structured_anchors = []
    merged_anchors = _merge_question_anchors(
        list((visual_entities or {}).get("questions") or []),
        ocr_anchors,
        structured_anchors,
    )
    if expected_count > 0:
        merged_anchors = [row for row in merged_anchors if 1 <= _to_int(row.get("number"), 0) <= expected_count]
    visual_entities = dict(visual_entities or {})
    visual_entities["questions"] = merged_anchors

    visual_header = (visual_entities or {}).get("header_total") if isinstance(visual_entities, dict) else None
    if isinstance(visual_header, dict) and safe_float(visual_header.get("marks"), 0.0) > 0:
        header_total_marks = round(safe_float(visual_header.get("marks"), 0.0), 4)
        header_total_reliable = bool(visual_header.get("reliable"))
        header_total_conf = safe_float(visual_header.get("confidence"), 0.0)
        header_total_source = str(visual_header.get("source") or "visual_header")
    else:
        header_total_marks, header_total_reliable, header_total_conf, header_total_source = _extract_header_total_from_images(
            question_paper_images
        )
        if not header_total_marks:
            header_total_marks, header_total_reliable, header_total_conf, header_total_source = _extract_header_total_hint(
                raw_ocr_text
            )

    # Layer 3 + 4: deterministic marks + audit tree.
    reasoned = resolve_marks(
        stage2_structure,
        visual_entities=visual_entities,
        header_total_marks=header_total_marks,
        header_total_reliable=header_total_reliable,
    )
    structure = reasoned.get("resolved_structure") or stage2_structure
    question_audit_tree = list(reasoned.get("question_audit_tree") or [])

    # Layer 5: consistency validator with repair tasks.
    validation_report = validate_structure_stage3(
        structure,
        header_total_marks=header_total_marks,
        header_total_reliable=header_total_reliable,
        expected_question_count=expected_question_count,
        visual_entities=visual_entities,
        question_audit_tree=question_audit_tree,
    )
    validation_report["header_total_marks"] = header_total_marks
    validation_report["header_total_reliable"] = header_total_reliable
    validation_report["header_total_confidence"] = header_total_conf
    validation_report["header_total_source"] = header_total_source
    validation_report["mark_override_coverage"] = reasoned.get("mark_override_coverage", 0.0)
    validation_report["effective_marks_map"] = reasoned.get("effective_marks_map") or []
    validation_report["mark_sources"] = {
        "header": 1 if header_total_marks is not None else 0,
        "section_math": len((structure.get("section_math_blocks") or [])),
        "effective_marks_map": len(reasoned.get("effective_marks_map") or []),
    }
    validation_report["visual_entities"] = visual_entities
    validation_report["question_audit_tree"] = question_audit_tree
    validation_report["unresolved_flags"] = []

    ai_reason_mismatches = list(reasoned.get("ai_visual_mismatches") or [])
    if ai_reason_mismatches:
        validation_report.setdefault("warnings", []).append(f"ai_visual_marks_mismatch:{len(ai_reason_mismatches)}")
        validation_report["ai_visual_mismatches"] = ai_reason_mismatches

    # Optional one-time semantic correction retry on validation failure.
    # Skip reconstruction if only subpart-sum mismatch exists (deterministic repair handles it).
    if not validation_report.get("is_valid"):
        errors_now = list(validation_report.get("errors") or [])
        only_subpart_mismatch = bool(errors_now) and all(
            str(err).startswith("subpart_sum_mismatch") for err in errors_now
        )
        if not only_subpart_mismatch:
            logger.warning("RECONSTRUCT_STRUCTURE errors=%s", errors_now)
            try:
                reconstruction_prompt = build_reconstruction_prompt(
                    previous_structure=structure,
                    validation_errors=errors_now or ["unknown_validation_failure"],
                    raw_ocr_text=raw_ocr_text,
                )
                reconstructed_raw = await _call_extraction_llm(
                    question_paper_images,
                    reconstruction_prompt,
                    model_name=model_name,
                )
                reconstructed_semantic = _normalize_batch_payload(reconstructed_raw, page_offset=0)
                reconstructed_semantic = _merge_semantic_with_visual_entities(reconstructed_semantic, visual_entities)
                reconstructed_reasoned = resolve_marks(
                    reconstructed_semantic,
                    visual_entities=visual_entities,
                    header_total_marks=header_total_marks,
                    header_total_reliable=header_total_reliable,
                )
                reconstructed_structure = reconstructed_reasoned.get("resolved_structure") or reconstructed_semantic
                reconstructed_audit = list(reconstructed_reasoned.get("question_audit_tree") or [])
                reconstructed_validation = validate_structure_stage3(
                    reconstructed_structure,
                    header_total_marks=header_total_marks,
                    header_total_reliable=header_total_reliable,
                    expected_question_count=expected_question_count,
                    visual_entities=visual_entities,
                    question_audit_tree=reconstructed_audit,
                )
                if len(reconstructed_validation.get("errors") or []) < len(errors_now):
                    structure = reconstructed_structure
                    question_audit_tree = reconstructed_audit
                    validation_report = reconstructed_validation
                    retry_count += 1
            except Exception as exc:
                logger.warning("RECONSTRUCTION_SKIPPED error=%s", exc)

    # Layer 6: one-pass auto repair + revalidate once.
    if not validation_report.get("is_valid"):
        repair_result = apply_structure_repairs(
            structure=structure,
            validation_report=validation_report,
            visual_entities=visual_entities,
        )
        repaired_structure = repair_result.get("repaired_structure") or structure
        repaired_audit = list(repair_result.get("question_audit_tree") or question_audit_tree)
        repairs_applied = list(repair_result.get("repairs_applied") or [])
        repaired_validation = validate_structure_stage3(
            repaired_structure,
            header_total_marks=header_total_marks,
            header_total_reliable=header_total_reliable,
            expected_question_count=expected_question_count,
            visual_entities=visual_entities,
            question_audit_tree=repaired_audit,
        )
        repaired_validation["repairs_applied"] = repairs_applied
        repaired_validation["question_audit_tree"] = repaired_audit
        repaired_validation["visual_entities"] = visual_entities
        repaired_validation["unresolved_flags"] = list(repaired_validation.get("errors") or [])
        structure = repaired_structure
        question_audit_tree = repaired_audit
        validation_report = repaired_validation

    # Final payload normalization + freeze-friendly metadata.
    structure = validation_report.get("normalized") or normalize_structure_payload(structure)
    structure["total_questions"] = len(structure.get("questions") or [])
    structure["total_marks"] = float(validation_report.get("effective_total_marks") or 0.0)
    structure["effective_total_marks"] = float(validation_report.get("effective_total_marks") or 0.0)
    structure["numbering_contiguous"] = bool(validation_report.get("numbering_contiguous", False))
    structure["question_audit_tree"] = question_audit_tree
    structure["visual_entities"] = visual_entities
    structure["unresolved_flags"] = list(validation_report.get("errors") or [])
    structure["section_math_rules"] = list(structure.get("section_math_rules") or [])

    confidence_vals = [_to_float(q.get("ai_confidence"), 0.0) for q in (structure.get("questions") or [])]
    structure["structure_confidence"] = round((sum(confidence_vals) / len(confidence_vals)) if confidence_vals else 0.0, 4)

    validation_report["question_audit_tree"] = question_audit_tree
    validation_report["visual_entities"] = visual_entities
    validation_report["unresolved_flags"] = list(validation_report.get("errors") or [])
    validation_report["section_math_rules"] = list(structure.get("section_math_rules") or [])
    return structure, validation_report, raw_ocr_text, retry_count


__all__ = ["extract_question_structure"]
