"""Question blueprint builder for college_v3 (global spans)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_llm_api_key, logger
from app.services.llm import LlmChat, UserMessage
from app.utils.blueprint import compute_blueprint_health


def _parse_first_json_object(raw_text: str) -> Optional[str]:
    if not raw_text:
        return None
    start = raw_text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw_text)):
        ch = raw_text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw_text[start:i + 1]
    return None


def _parse_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None
    raw = (raw_text or "").strip()
    candidates: List[str] = [raw]
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE):
        block = (m.group(1) or "").strip()
        if block:
            candidates.append(block)
    first_obj = _parse_first_json_object(raw)
    if first_obj:
        candidates.append(first_obj)
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]
    return None


def _to_float(value: Any) -> Optional[float]:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except Exception:
        match = re.search(r"(\d+(?:\.\d+)?)", str(value))
        if match:
            try:
                return float(match.group(1))
            except Exception:
                return None
        return None


def _detect_optional_group(text: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    t = (text or "").lower()
    if "internal choice" in t or re.search(r"\bor\b", t):
        return f"group_{uuid.uuid4().hex[:6]}", 2, 1
    return None, None, None


async def build_blueprint_from_spans(
    question_spans: List[Dict[str, Any]],
) -> Dict[str, Any]:
    api_key = get_llm_api_key()
    if not api_key:
        logger.warning("[COLLEGE-V3] GEMINI_API_KEY missing; blueprint extraction will be degraded.")

    questions: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    blueprint_question_pages: Dict[int, List[int]] = {}

    for span in question_spans:
        if str(span.get("anchor_level")) != "question":
            continue
        qn = int(span.get("question_number") or 0)
        span_text = "\n".join((p.get("text", "") for p in span.get("raw_text_by_page") or []))
        span_text = (span_text or "").strip()
        if not span_text:
            failed.append({"type": "empty_span", "question_number": qn})
            continue

        prompt = f"""Extract blueprint for exactly ONE question from OCR text.

Question span OCR text:
{span_text}

Return ONLY JSON:
{{
  "question_number": {qn},
  "marks": 0,
  "question_text": "short title",
  "rubric": "full question text",
  "type": "descriptive",
  "subparts": [
    {{
      "sub_id": "a",
      "marks": 0,
      "text": "subpart text"
    }}
  ],
  "is_optional": false,
  "optional_group_id": null,
  "group_size": null,
  "choose_k": null
}}"""

        payload: Optional[Dict[str, Any]] = None
        response_text = ""
        for attempt in range(4):
            try:
                chat = LlmChat(
                    api_key=api_key or "",
                    session_id=f"college_v3_bp_{uuid.uuid4().hex[:8]}",
                    system_message="Return a single JSON object. No prose.",
                ).with_model("gemini", "gemini-2.5-flash").with_params(
                    temperature=0,
                    response_mime_type="application/json",
                )
                response = await chat.send_message(UserMessage(text=prompt))
                response_text = response or ""
                payload = _parse_payload(response_text)
                if payload:
                    break
            except Exception as e:
                failed.append({"type": "llm_exception", "question_number": qn, "error": str(e)})
        if not payload:
            # Regex fallback
            opt_group_id, group_size, choose_k = _detect_optional_group(span_text)
            questions.append(
                {
                    "question_number": qn,
                    "max_marks": _to_float(None),
                    "question_text": (span_text.splitlines()[0] if span_text else f"Question {qn}")[:200],
                    "rubric": span_text or f"Question {qn}",
                    "type": "descriptive",
                    "sub_questions": [],
                    "is_optional": bool(opt_group_id),
                    "optional_group": opt_group_id,
                    "required_count": choose_k,
                    "group_size": group_size,
                }
            )
            continue

        marks = _to_float(payload.get("marks"))
        subparts = payload.get("subparts") or []
        sub_questions: List[Dict[str, Any]] = []
        if isinstance(subparts, list):
            for sp in subparts:
                if not isinstance(sp, dict):
                    continue
                sid = str(sp.get("sub_id") or "").strip()
                if not sid:
                    continue
                sub_questions.append(
                    {
                        "sub_id": sid,
                        "max_marks": _to_float(sp.get("marks")),
                        "rubric": str(sp.get("text") or "").strip() or f"Part ({sid})",
                    }
                )

        opt_group_id = payload.get("optional_group_id")
        group_size = payload.get("group_size")
        choose_k = payload.get("choose_k")
        if not opt_group_id:
            opt_group_id, group_size, choose_k = _detect_optional_group(span_text)

        questions.append(
            {
                "question_number": qn,
                "max_marks": marks,
                "question_text": str(payload.get("question_text") or "").strip() or (span_text.splitlines()[0] if span_text else f"Question {qn}"),
                "rubric": str(payload.get("rubric") or "").strip() or span_text or f"Question {qn}",
                "type": str(payload.get("type") or "descriptive"),
                "sub_questions": sub_questions,
                "is_optional": bool(payload.get("is_optional")) or bool(opt_group_id),
                "optional_group": opt_group_id,
                "required_count": choose_k,
                "group_size": group_size,
            }
        )
        blueprint_question_pages[qn] = span.get("page_numbers") or []

    # Completeness gate
    parsed_numbers = sorted({int(q.get("question_number")) for q in questions if q.get("question_number")})
    expected = list(range(1, (max(parsed_numbers) if parsed_numbers else 0) + 1))
    missing = sorted(set(expected) - set(parsed_numbers))

    health = compute_blueprint_health(questions, expected_count=len(expected) if expected else None)
    numbering_contiguous = bool(parsed_numbers) and parsed_numbers == expected
    health.update(
        {
            "numbering_contiguous": numbering_contiguous,
            "missing": missing,
            "failed_chunks": failed,
        }
    )

    blockers: List[str] = []
    if missing:
        blockers.append(f"missing_questions:{','.join(str(n) for n in missing)}")

    return {
        "questions": questions,
        "blueprint_question_pages": blueprint_question_pages,
        "blueprint_health": health,
        "blockers": blockers,
    }

