"""
Question extraction and model answer processing services.
Migrated from server.py extraction functions (lines ~202-397, 4266-5296).
"""
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import asyncio
import json
import os
import re
import uuid
import inspect
import pickle
from statistics import median

from bson import ObjectId

import base64
from io import BytesIO
from PIL import Image

from app.database import db, fs
from app.config import (
    logger,
    get_llm_api_key,
    MARK_VALIDATION_ENABLED,
)
from app.services.gridfs_helpers import (
    get_exam_model_answer_images,
    get_exam_question_paper_images,
    get_exam_question_paper_pdf_bytes,
)
from app.services.answer_sheet_pipeline import build_question_blueprint_from_exam_questions
from app.utils.blueprint import compute_blueprint_health, derive_expected_question_count
from app.utils.hashing import get_model_answer_hash
from app.utils.ocr_provider import get_ocr_provider
from app.services.llm import LlmChat, UserMessage, ImageContent

# In-memory cache for model answer extraction results
model_answer_cache = {}

# Require complete question extraction before saving/using extracted structure.
REQUIRE_COMPLETE_QUESTION_EXTRACTION = os.getenv(
    "REQUIRE_COMPLETE_QUESTION_EXTRACTION", "true"
).lower() in ("1", "true", "yes", "on")


def _images_to_pdf_bytes(images: List[str]) -> bytes:
    if not images:
        return b""
    pil_images: List[Image.Image] = []
    for img_b64 in images:
        raw = base64.b64decode(img_b64)
        pil = Image.open(BytesIO(raw)).convert("RGB")
        pil_images.append(pil)
    first, rest = pil_images[0], pil_images[1:]
    buf = BytesIO()
    first.save(buf, format="PDF", save_all=True, append_images=rest)
    return buf.getvalue()


async def get_exam_answer_sheet_images(exam_id: str, max_submissions: int = 3, max_pages: int = 40) -> List[str]:
    """
    Get answer-sheet images from existing graded submissions for question extraction fallback.
    Returns a bounded number of pages to keep prompts stable.
    """
    images: List[str] = []
    try:
        submissions = await db.submissions.find(
            {"exam_id": exam_id},
            {"_id": 0, "answer_images": 1, "file_images": 1, "images_gridfs_id": 1, "created_at": 1}
        ).sort("created_at", 1).to_list(max_submissions)

        for sub in submissions:
            sub_images = sub.get("answer_images") or sub.get("file_images") or []

            if not sub_images and sub.get("images_gridfs_id"):
                try:
                    grid_out = fs.get(ObjectId(sub["images_gridfs_id"]))
                    sub_images = pickle.loads(grid_out.read())
                except Exception as err:
                    logger.warning(f"Failed loading submission images for extraction fallback: {err}")
                    sub_images = []

            if sub_images:
                images.extend(sub_images)
                if len(images) >= max_pages:
                    images = images[:max_pages]
                    break

    except Exception as err:
        logger.error(f"Error fetching answer-sheet images for exam {exam_id}: {err}")

    return images


# ============== AI CALL HELPERS ==============

async def ai_call_with_timeout(chat_model, message, timeout_seconds=60, operation_name="AI call"):
    """
    Wrapper for AI calls with timeout protection.
    Prevents indefinite hanging on API timeouts.
    """
    try:
        async def make_api_call():
            send_message = chat_model.send_message
            if inspect.iscoroutinefunction(send_message):
                return await send_message(message)
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: send_message(message))

        result = await asyncio.wait_for(make_api_call(), timeout=timeout_seconds)
        return result
    except asyncio.TimeoutError:
        logger.error(f"⏱️ TIMEOUT after {timeout_seconds}s: {operation_name}")
        raise TimeoutError(f"{operation_name} exceeded {timeout_seconds}s timeout")


def create_gemini_chat(system_message: str = ""):
    """Create a Gemini chat session with optional system message."""
    return LlmChat(
        api_key=get_llm_api_key() or "",
        session_id=f"legacy_chat_{uuid.uuid4().hex[:8]}",
        system_message=system_message,
    ).with_model("gemini", "gemini-2.5-flash").with_params(
        temperature=0
    )


MARK_VALIDATION_SYSTEM_PROMPT = """You are an exam-analysis assistant. The user will upload a PDF of a question paper (any subject). Your goal is to extract the marks allocation for each question and each sub-question.

Tasks:
1) Identify each question number (e.g., Q1, Q2, etc.) and extract its mark value if explicitly given.
2) Detect implicit marking schemes. If the paper states a range with per-question marks and a total (e.g., "Q1–Q5: 2 marks each (total 10)"), assign the per-question marks accordingly.
3) Handle sub-parts. If a question has parts (e.g., Q1(a), Q1(b), or Q1a/Q1b), extract marks for each sub-part.
4) Be subject-agnostic; use only text/layout cues from the paper.
5) Do not hallucinate. If marks are unclear or not present, set them to null and add an entry in unknown_marks.

Output STRICT JSON only with this schema:
{
  "questions": [
    {
      "question_number": "Q1",
      "marks": 2,
      "subparts": [{"part": "a", "marks": 1}],
      "inferred_from_rule": false
    }
  ],
  "implicit_rules_detected": ["Q1–Q5: 2 marks each (total 10)"],
  "unknown_marks": ["Q12: marks not stated"],
  "total_questions_found": 0,
  "total_marks_inferred": 0
}

Rules:
- marks must be numeric or null
- subparts must be an array (empty if none)
- inferred_from_rule true only when derived from a stated rule
- Output valid JSON with no extra commentary.
"""


def _parse_llm_json(response_text: str) -> Optional[Dict[str, Any]]:
    if not response_text:
        return None
    text = response_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:]
            text = text.strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group())
        except json.JSONDecodeError:
            pass
    return None


def _to_float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _validator_total_from_entry(entry: Dict[str, Any]) -> Optional[float]:
    direct = _to_float_or_none(entry.get("marks"))
    if direct is not None:
        return direct
    subparts = entry.get("subparts") or []
    if not subparts:
        return None
    total = 0.0
    has_any = False
    for sp in subparts:
        sp_mark = _to_float_or_none(sp.get("marks"))
        if sp_mark is not None:
            total += sp_mark
            has_any = True
    return total if has_any else None


def _extracted_total_for_question(question: Dict[str, Any]) -> Optional[float]:
    q_marks = _to_float_or_none(question.get("max_marks"))
    if q_marks is not None and q_marks > 0:
        return q_marks
    sub_total = 0.0
    has_any = False
    for sq in (question.get("sub_questions") or []):
        sq_marks = _to_float_or_none(sq.get("max_marks"))
        if sq_marks is not None and sq_marks > 0:
            sub_total += sq_marks
            has_any = True
    return sub_total if has_any else None


def _normalize_validator_questions(payload: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for entry in payload.get("questions") or []:
        qn = _parse_question_number(entry.get("question_number") or entry.get("question") or entry.get("number"))
        if not qn:
            continue
        subparts = entry.get("subparts") or []
        sub_map: Dict[str, Optional[float]] = {}
        for sp in subparts:
            sid = _normalize_sub_id(sp.get("part") or sp.get("sub_id") or "")
            if not sid:
                continue
            sub_map[sid] = _to_float_or_none(sp.get("marks"))
        out[int(qn)] = {
            "marks": _to_float_or_none(entry.get("marks")),
            "subparts": sub_map,
            "inferred_from_rule": bool(entry.get("inferred_from_rule")),
        }
    return out


def _parse_unknown_marks(unknown_marks: List[str]) -> List[int]:
    qnums: List[int] = []
    for item in unknown_marks or []:
        qn = _parse_question_number(item)
        if qn:
            qnums.append(int(qn))
    return qnums


def compare_validator_to_extracted(
    extracted_questions: List[Dict[str, Any]],
    validator_payload: Dict[str, Any],
    tolerance: float = 0.1,
) -> Dict[str, Any]:
    validator_map = _normalize_validator_questions(validator_payload)
    unknown_marks = validator_payload.get("unknown_marks") or []
    unknown_qnums = set(_parse_unknown_marks(unknown_marks))

    issues: List[Dict[str, Any]] = []
    missing_count = 0
    mismatch_count = 0
    inferred_count = 0
    unknown_count = 0

    extracted_total = 0.0
    extracted_total_counted = False
    validator_total = 0.0
    validator_total_counted = False

    for question in extracted_questions or []:
        qn = _parse_question_number(question.get("question_number"))
        if not qn:
            continue
        qn = int(qn)

        extracted_total_q = _extracted_total_for_question(question)
        if extracted_total_q is not None:
            extracted_total += extracted_total_q
            extracted_total_counted = True

        validator_entry = validator_map.get(qn)
        if not validator_entry:
            issues.append({
                "question_number": qn,
                "issue_type": "missing_in_validator",
                "extracted": extracted_total_q,
                "validator": None,
            })
            missing_count += 1
            continue

        if validator_entry.get("inferred_from_rule"):
            inferred_count += 1

        validator_total_q = _validator_total_from_entry({
            "marks": validator_entry.get("marks"),
            "subparts": [
                {"part": k, "marks": v} for k, v in (validator_entry.get("subparts") or {}).items()
            ],
        })

        if validator_total_q is not None:
            validator_total += validator_total_q
            validator_total_counted = True

        if qn in unknown_qnums:
            unknown_count += 1
            issues.append({
                "question_number": qn,
                "issue_type": "unknown_validator_marks",
                "extracted": extracted_total_q,
                "validator": validator_total_q,
            })

        if validator_total_q is None and extracted_total_q is not None:
            issues.append({
                "question_number": qn,
                "issue_type": "missing_validator_marks",
                "extracted": extracted_total_q,
                "validator": None,
            })
            missing_count += 1
        elif validator_total_q is not None and (extracted_total_q is None or extracted_total_q <= 0):
            issues.append({
                "question_number": qn,
                "issue_type": "missing_extracted_marks",
                "extracted": extracted_total_q,
                "validator": validator_total_q,
            })
            missing_count += 1
        elif validator_total_q is not None and extracted_total_q is not None:
            if abs(validator_total_q - extracted_total_q) > tolerance:
                issues.append({
                    "question_number": qn,
                    "issue_type": "mismatch",
                    "extracted": extracted_total_q,
                    "validator": validator_total_q,
                })
                mismatch_count += 1

        extracted_subs = {
            _normalize_sub_id(sq.get("sub_id")): _to_float_or_none(sq.get("max_marks"))
            for sq in (question.get("sub_questions") or [])
            if _normalize_sub_id(sq.get("sub_id"))
        }
        validator_subs = validator_entry.get("subparts") or {}
        for sub_id, v_mark in validator_subs.items():
            e_mark = extracted_subs.get(sub_id)
            if v_mark is None and e_mark is not None:
                issues.append({
                    "question_number": qn,
                    "sub_part": sub_id,
                    "issue_type": "missing_validator_subpart",
                    "extracted": e_mark,
                    "validator": None,
                })
                missing_count += 1
            elif v_mark is not None and (e_mark is None or e_mark <= 0):
                issues.append({
                    "question_number": qn,
                    "sub_part": sub_id,
                    "issue_type": "missing_extracted_subpart",
                    "extracted": e_mark,
                    "validator": v_mark,
                })
                missing_count += 1
            elif v_mark is not None and e_mark is not None:
                if abs(v_mark - e_mark) > tolerance:
                    issues.append({
                        "question_number": qn,
                        "sub_part": sub_id,
                        "issue_type": "mismatch_subpart",
                        "extracted": e_mark,
                        "validator": v_mark,
                    })
                    mismatch_count += 1

    status = "warning" if (missing_count or mismatch_count) else "pass"
    report = {
        "status": status,
        "extracted_total": round(extracted_total, 4) if extracted_total_counted else None,
        "validator_total": round(validator_total, 4) if validator_total_counted else None,
        "missing_count": int(missing_count),
        "mismatch_count": int(mismatch_count),
        "inferred_count": int(inferred_count),
        "unknown_count": int(unknown_count),
        "issues": issues,
        "implicit_rules_detected": validator_payload.get("implicit_rules_detected") or [],
        "unknown_marks": validator_payload.get("unknown_marks") or [],
        "validator_questions_found": int(validator_payload.get("total_questions_found") or len(validator_payload.get("questions") or [])),
    }
    return report


async def validate_marks_with_llm(question_paper_images: List[str]) -> Optional[Dict[str, Any]]:
    api_key = get_llm_api_key()
    if not api_key:
        logger.warning("No API key for mark validation")
        return None
    if not question_paper_images:
        return None

    chat = LlmChat(
        api_key=api_key,
        session_id=f"validate_marks_{uuid.uuid4().hex[:8]}",
        system_message=MARK_VALIDATION_SYSTEM_PROMPT,
    ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

    image_contents = [ImageContent(image_base64=img) for img in question_paper_images]
    prompt = "Extract the marking scheme from this question paper. Return ONLY JSON."
    user_message = UserMessage(text=prompt, file_contents=image_contents)

    ai_response = await ai_call_with_timeout(
        chat,
        user_message,
        timeout_seconds=90,
        operation_name="Mark validation extraction",
    )
    response_text_raw = ai_response.text if hasattr(ai_response, "text") else str(ai_response)
    parsed = _parse_llm_json(response_text_raw)
    if not parsed:
        logger.warning("Mark validation: failed to parse JSON from LLM response")
        return None
    return parsed


# ============== MODEL ANSWER TEXT EXTRACTION ==============

async def get_exam_model_answer_text(exam_id: str) -> str:
    """Get pre-extracted model answer text content for faster grading."""
    try:
        file_doc = await db.exam_files.find_one(
            {"exam_id": exam_id, "file_type": "model_answer"},
            {"_id": 0, "model_answer_text": 1}
        )
        if file_doc and file_doc.get("model_answer_text"):
            return file_doc["model_answer_text"]
    except Exception as e:
        logger.error(f"Error getting model answer text: {e}")
    return ""


async def get_exam_model_answer_map(exam_id: str) -> Dict[str, Any]:
    """Get pre-extracted model answer map (per question) for precise grading."""
    try:
        file_doc = await db.exam_files.find_one(
            {"exam_id": exam_id, "file_type": "model_answer"},
            {"_id": 0, "model_answer_map": 1}
        )
        model_answer_map = (file_doc or {}).get("model_answer_map")
        if isinstance(model_answer_map, dict):
            return model_answer_map
    except Exception as e:
        logger.error(f"Error getting model answer map: {e}")
    return {}


def _parse_model_answer_json(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None
    candidates = [raw_text.strip()]
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw_text, flags=re.IGNORECASE):
        block = (match.group(1) or "").strip()
        if block:
            candidates.append(block)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_subpart_label(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned or cleaned in {"none", "null"}:
        return ""
    cleaned = re.sub(r"[^a-z0-9]+", "", cleaned)
    return cleaned


def _merge_model_answer_entries(answer_map: Dict[str, Dict[str, str]], entries: List[Dict[str, Any]]) -> None:
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        q_raw = entry.get("question") or entry.get("question_number")
        try:
            qn = str(int(q_raw))
        except Exception:
            continue

        subpart = _normalize_subpart_label(entry.get("subpart") or entry.get("sub_id"))
        text = str(entry.get("answer_text") or entry.get("answer") or "").strip()
        key_points = entry.get("key_points") or entry.get("keyPoints") or []
        if key_points and isinstance(key_points, list):
            key_points = [str(k).strip() for k in key_points if str(k).strip()]
        else:
            key_points = []

        if not text and isinstance(entry.get("subparts"), list):
            for sub_entry in entry.get("subparts") or []:
                if not isinstance(sub_entry, dict):
                    continue
                sub_label = _normalize_subpart_label(sub_entry.get("subpart") or sub_entry.get("label"))
                sub_text = str(sub_entry.get("answer_text") or sub_entry.get("answer") or "").strip()
                if sub_text:
                    answer_map.setdefault(qn, {})
                    existing = answer_map[qn].get(sub_label, "")
                    answer_map[qn][sub_label] = (existing + "\n" + sub_text).strip() if existing else sub_text
            continue

        if key_points:
            kp_block = "\n".join(f"- {kp}" for kp in key_points)
            text = f"{text}\nKey points:\n{kp_block}" if text else f"Key points:\n{kp_block}"

        if not text:
            continue

        answer_map.setdefault(qn, {})
        existing = answer_map[qn].get(subpart, "")
        if existing:
            if text not in existing:
                answer_map[qn][subpart] = (existing + "\n" + text).strip()
        else:
            answer_map[qn][subpart] = text


def _render_model_answer_map(answer_map: Dict[str, Dict[str, str]]) -> str:
    if not answer_map:
        return ""
    lines: List[str] = []
    def _sort_key(item: str) -> int:
        try:
            return int(item)
        except Exception:
            return 999999

    for qn in sorted(answer_map.keys(), key=_sort_key):
        sub_map = answer_map.get(qn) or {}
        lines.append(f"QUESTION {qn}:")
        if not sub_map:
            lines.append("")
            lines.append("---")
            continue
        sub_labels = [k for k in sub_map.keys() if k]
        sub_labels = sorted(sub_labels)
        if "" in sub_map:
            if not sub_labels:
                lines.append(sub_map.get("") or "")
            else:
                lines.append(sub_map.get("") or "")
        for label in sub_labels:
            label_text = f"Part {label}:"
            answer_text = sub_map.get(label) or ""
            if answer_text:
                lines.append(f"{label_text} {answer_text}")
        lines.append("---")
    return "\n".join(lines).strip()


async def extract_model_answer_content(
    model_answer_images: List[str],
    questions: List[dict]
) -> tuple[str, Dict[str, Dict[str, str]]]:
    """
    Extract detailed answer content from model answer images as structured text.
    This is done ONCE during upload and stored for use during grading.
    """
    api_key = get_llm_api_key()
    if not api_key:
        logger.error("No API key for model answer content extraction")
        return ""
    
    if not model_answer_images:
        return "", {}
    
    try:
        # Build questions context
        questions_context = ""
        for q in questions:
            q_num = q.get("question_number") or q.get("number") or "?"
            q_marks = q.get("total_marks") or q.get("max_marks") or q.get("marks") or 0
            questions_context += f"- Question {q_num} ({q_marks} marks)\n"
            sub_list = q.get("sub_questions") or q.get("subquestions") or []
            for sq in sub_list:
                sq_id = sq.get("sub_id") or sq.get("label") or "?"
                sq_marks = sq.get("marks") or sq.get("max_marks") or 0
                questions_context += f"  - Part {sq_id} ({sq_marks} marks)\n"
        
        # Process in chunks for large model answers
        CHUNK_SIZE = 15  # Process 15 pages at a time for stability
        all_extracted_content = []
        answer_map: Dict[str, Dict[str, str]] = {}
        
        for chunk_start in range(0, len(model_answer_images), CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, len(model_answer_images))
            chunk_images = model_answer_images[chunk_start:chunk_end]
            
            chat = LlmChat(
                api_key=api_key,
                session_id=f"extract_content_{uuid.uuid4().hex[:8]}",
                system_message="""You are an expert at extracting model answer content from exam papers.

Your task is to extract ALL answer content and structure it clearly.

For each question/sub-question:
1. Identify the question number
2. Extract the COMPLETE model answer text
3. Note any marking points or criteria

Return strict JSON only using this schema:
{
  "answers": [
    {"question": 1, "subpart": null, "answer_text": "...", "key_points": ["..."]},
    {"question": 17, "subpart": "a", "answer_text": "...", "key_points": []}
  ]
}

Rules:
- Use the question numbers provided.
- Use subpart labels like "a", "b", "c" when applicable.
- If an answer continues across pages, include the visible portion.
- Be thorough - extract EVERY detail useful for grading."""
            ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)
            
            image_contents = [ImageContent(image_base64=img) for img in chunk_images]
            
            prompt = f"""Extract ALL model answer content from pages {chunk_start + 1} to {chunk_end}.

Questions in this exam:
{questions_context}

Extract complete answers for ALL questions visible on these pages.
Return strict JSON only."""

            user_message = UserMessage(text=prompt, file_contents=image_contents)
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"Extracting model answer content: pages {chunk_start + 1}-{chunk_end} (attempt {attempt + 1})")
                    response = await ai_call_with_timeout(
                        chat, 
                        user_message, 
                        timeout_seconds=120,
                        operation_name=f"Model answer extraction attempt {attempt+1}"
                    )
                    if response:
                        response_text = response.text if hasattr(response, "text") else str(response)
                        logger.info(
                            "[EXTRACT-MA-CHUNK] Extracted %s chars from pages %s-%s",
                            len(response_text),
                            chunk_start + 1,
                            chunk_end,
                        )
                        parsed = _parse_model_answer_json(response_text)
                        if parsed:
                            _merge_model_answer_entries(answer_map, parsed.get("answers") or [])
                        all_extracted_content.append(f"=== PAGES {chunk_start + 1}-{chunk_end} ===\n{response_text}")
                        break
                except Exception as e:
                    logger.error(f"Error extracting content chunk: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5 * (attempt + 1))
        
        rendered_text = _render_model_answer_map(answer_map)
        full_content = rendered_text or "\n\n".join(all_extracted_content)
        logger.info(
            "Extracted model answer content: %s chars from %s pages (map_entries=%s)",
            len(full_content),
            len(model_answer_images),
            len(answer_map),
        )
        return full_content, answer_map
        
    except Exception as e:
        logger.error(f"Error in extract_model_answer_content: {e}")
        return "", {}


# ============== QUESTION EXTRACTION FROM QUESTION PAPER ==============

async def extract_questions_from_question_paper(
    question_paper_images: List[str],
    num_questions: int
) -> List[str]:
    """Extract question text from question paper images using AI with improved sub-question handling"""
    
    api_key = get_llm_api_key()
    if not api_key:
        return []
    
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"extract_qp_{uuid.uuid4().hex[:8]}",
            system_message="""You are an expert at extracting question text from exam question papers.

Extract ALL question text from the provided question paper images.
Return a JSON array with structured objects for each question.

CRITICAL INSTRUCTIONS FOR SUB-QUESTIONS:

1. For questions WITH sub-parts (a, b, c or i, ii, iii):
   - The parent question's rubric should be EMPTY or contain only a brief intro
   - Each sub-question's rubric MUST contain its FULL text
   - DO NOT put all text in the parent question

2. Text distribution example:
   Original: "Q5: (a) Explain photosynthesis. (b) Draw a diagram of a leaf."

   WRONG:
   {
     question_text: "Q5: (a) Explain photosynthesis. (b) Draw a diagram of a leaf.",
     rubric: "Explain photosynthesis. Draw a diagram of a leaf.",
     sub_questions: [
       { sub_id: "a", rubric: "" },
       { sub_id: "b", rubric: "" }
     ]
   }

   CORRECT:
   {
     question_text: "Q5:",
     rubric: "",
     sub_questions: [
       { sub_id: "a", rubric: "Explain photosynthesis." },
       { sub_id: "b", rubric: "Draw a diagram of a leaf." }
     ]
   }

3. For questions WITHOUT sub-parts:
   - Put the full text in the parent question's rubric field
   - sub_questions array should be empty []

4. Parsing rules:
   - (a), (b), (c) or (i), (ii), (iii) indicate sub-parts
   - Split text at each sub-part marker
   - Include the marker with its text: "(a) Explain..." not just "Explain..."

5. Nested sub-parts like (a)(i), (a)(ii):
   - These belong to sub-question "a"
   - Include them in sub_id "a"'s rubric: "(a) (i) First part (ii) Second part"

Required JSON structure for each question:
{
  "questions": [
    {
      "question_number": "string",
      "question_text": "Brief identifier only, e.g. 'Q5:' - NOT full text",
      "rubric": "Empty if has sub-parts, full text if no sub-parts",
      "max_marks": number,
      "sub_questions": [
        {
          "sub_id": "a",
          "rubric": "FULL TEXT of sub-part (a) goes here",
          "max_marks": number
        }
      ]
    }
  ]
}
"""
        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)
        
        # Create image contents - process ALL pages, no limit
        image_contents = [ImageContent(image_base64=img) for img in question_paper_images]
        logger.info(f"Extracting questions from {len(image_contents)} question paper pages")
        
        prompt = f"""Extract the questions from this question paper.
        
Expected number of questions: {num_questions}

Return ONLY the JSON, no other text."""
        
        user_message = UserMessage(text=prompt, file_contents=image_contents)
        
        # Retry logic for question extraction
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Question extraction attempt {attempt + 1}/{max_retries}")
                ai_response = await ai_call_with_timeout(
                    chat,
                    user_message,
                    timeout_seconds=90,
                    operation_name=f"Question extraction attempt {attempt+1}"
                )
                
                # Parse response with robust JSON extraction
                # Extract text from Gemini response object
                response_text_raw = ai_response.text if hasattr(ai_response, 'text') else str(ai_response)
                response_text = response_text_raw.strip()
                
                # Strategy 1: Direct parse
                try:
                    result = json.loads(response_text)
                    logger.info(f"Successfully extracted {len(result.get('questions', []))} questions")
                    return result.get("questions", [])
                except json.JSONDecodeError:
                    pass
                
                # Strategy 2: Remove code blocks
                if response_text.startswith("```"):
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]
                    response_text = response_text.strip()
                    try:
                        result = json.loads(response_text)
                        logger.info(f"Successfully extracted {len(result.get('questions', []))} questions")
                        return result.get("questions", [])
                    except json.JSONDecodeError:
                        pass
                
                # Strategy 3: Find JSON object in text
                json_match = re.search(r'\{[^{}]*"questions"[^{}]*\[[^\]]*\][^{}]*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                        logger.info(f"Successfully extracted {len(result.get('questions', []))} questions (pattern match)")
                        return result.get("questions", [])
                    except json.JSONDecodeError:
                        pass
                
                # If all strategies fail, log and retry
                logger.warning(f"Failed to parse JSON from response (attempt {attempt + 1}). Response preview: {response_text[:200]}")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying question extraction in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"All JSON parsing strategies failed after {max_retries} attempts")
                    return []
                
            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Error during question extraction attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1 and ("502" in error_str or "503" in error_str or "timeout" in error_str or "gateway" in error_str or "rate limit" in error_str):
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying question extraction in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    if attempt >= max_retries - 1:
                        logger.error(f"Question extraction failed after {max_retries} attempts")
                    raise e
        
        return []
        
    except Exception as e:
        logger.error(f"Error extracting questions from question paper: {e}")
        return []


# ============== QUESTION EXTRACTION FROM MODEL ANSWER ==============

async def extract_questions_from_model_answer(
    model_answer_images: List[str],
    num_questions: int
) -> List[str]:
    """Extract question text from model answer images using AI with improved sub-question handling"""
    
    # Check cache
    cache_key = get_model_answer_hash(model_answer_images)
    if cache_key in model_answer_cache:
        logger.info(f"Cache hit (memory) for model answer extraction")
        return model_answer_cache[cache_key]

    api_key = get_llm_api_key()
    if not api_key:
        return []
    
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"extract_{uuid.uuid4().hex[:8]}",
            system_message="""You are an expert at extracting question text from exam papers.
            
Extract ONLY the question text (not answers) from the provided model answer images.
Return a JSON array with structured objects for each question.

CRITICAL INSTRUCTIONS FOR SUB-QUESTIONS:

1. For questions WITH sub-parts (a, b, c or i, ii, iii):
   - The parent question's rubric should be EMPTY or contain only a brief intro
   - Each sub-question's rubric MUST contain its FULL text
   - DO NOT put all text in the parent question

2. Text distribution example:
   Original: "Q5: (a) Explain photosynthesis. (b) Draw a diagram of a leaf."

   WRONG:
   {
     question_text: "Q5: (a) Explain photosynthesis. (b) Draw a diagram of a leaf.",
     rubric: "Explain photosynthesis. Draw a diagram of a leaf.",
     sub_questions: [
       { sub_id: "a", rubric: "" },
       { sub_id: "b", rubric: "" }
     ]
   }

   CORRECT:
   {
     question_text: "Q5:",
     rubric: "",
     sub_questions: [
       { sub_id: "a", rubric: "Explain photosynthesis." },
       { sub_id: "b", rubric: "Draw a diagram of a leaf." }
     ]
   }

3. For questions WITHOUT sub-parts:
   - Put the full text in the parent question's rubric field
   - sub_questions array should be empty []

4. DO NOT include answer content, only question text
5. Look through ALL pages carefully
6. Return questions in order (Q1, Q2, Q3, etc.)

Required JSON structure:
{
  "questions": [
    {
      "question_number": "string",
      "question_text": "Brief identifier only",
      "rubric": "Empty if has sub-parts, full text if no sub-parts",
      "max_marks": number,
      "sub_questions": [
        {
          "sub_id": "a",
          "rubric": "FULL TEXT of sub-part (a)",
          "max_marks": number
        }
      ]
    }
  ]
}
"""
        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)
        
        # Create image contents - process ALL pages, no limit
        image_contents = [ImageContent(image_base64=img) for img in model_answer_images]
        logger.info(f"Extracting questions from {len(image_contents)} model answer pages")
        
        prompt = f"""Extract the question text from these model answer images.
        
CRITICAL: There are {num_questions} questions in this exam. You MUST extract ALL {num_questions} questions!

Look carefully through ALL images. Questions might be on different pages.

Extract each question's complete text. Do NOT include answers, only the question text.

Return ONLY the JSON with ALL {num_questions} questions, no other text."""
        
        user_message = UserMessage(
            text=prompt,
            file_contents=image_contents
        )
        
        # Retry logic for model answer extraction
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Model answer extraction attempt {attempt + 1}/{max_retries}")
                ai_response = await chat.send_message(user_message)
                
                # Parse JSON response
                # Extract text from Gemini response object
                response_text_raw = ai_response.text if hasattr(ai_response, 'text') else str(ai_response)
                response_text = response_text_raw.strip()
                if response_text.startswith("```"):
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:]
                
                result = json.loads(response_text)
                questions = result.get("questions", [])

                logger.info(f"Successfully extracted {len(questions)} questions from model answer")

                # Cache result
                model_answer_cache[cache_key] = questions
                return questions
                
            except Exception as e:
                error_str = str(e).lower()
                if attempt < max_retries - 1 and ("502" in error_str or "503" in error_str or "timeout" in error_str or "gateway" in error_str):
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying model answer extraction in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    raise e
        
        return []
        
    except Exception as e:
        logger.error(f"Error extracting questions: {e}")
        return []


# ============== QUESTION STRUCTURE EXTRACTION ==============

async def extract_question_structure_from_paper(
    paper_images: List[str],
    paper_type: str = "question_paper"
) -> List[dict]:
    """
    Extract COMPLETE question structure including:
    - Question numbers
    - Sub-questions with IDs (a, b, c OR i, ii, iii)
    - Sub-sub-questions if any
    - Marks for each question/sub-question
    - Question text
    
    Returns a list of question dictionaries matching the exam structure.
    """
    
    api_key = get_llm_api_key()
    if not api_key:
        logger.error("LLM API Key not configured")
        return []
    
    def normalize_extracted_questions(questions: List[dict]) -> List[dict]:
        normalized = []
        for q in questions or []:
            q_num = q.get("question_number")
            q_text = (q.get("question_text") or "").strip()
            rubric = (q.get("rubric") or "").strip()

            # Ensure question_text is always meaningful
            if not q_text:
                q_text = f"Question {q_num}" if q_num is not None else "Question"

            # Ensure rubric has something readable
            if not rubric:
                rubric = f"Answer context not clear for Question {q_num}" if q_num is not None else "Answer context not clear"

            # Normalize sub-questions
            sub_qs = q.get("sub_questions") or []
            normalized_subs = []
            for sq in sub_qs:
                sub_id = (sq.get("sub_id") or "").strip() or "a"
                sq_rubric = (sq.get("rubric") or "").strip()
                if not sq_rubric:
                    sq_rubric = f"Part {sub_id} answer context not clear"
                normalized_subs.append({
                    **sq,
                    "sub_id": sub_id,
                    "rubric": sq_rubric
                })

            # Ensure max_marks exists; derive from sub-questions if needed
            max_marks = q.get("max_marks")
            if max_marks in (None, "", 0) and normalized_subs:
                max_marks = sum(float(sq.get("max_marks") or 0) for sq in normalized_subs)

            normalized.append({
                **q,
                "question_text": q_text,
                "rubric": rubric,
                "sub_questions": normalized_subs,
                "max_marks": max_marks
            })

        return normalized

    def parse_questions_payload(raw_text: str) -> List[dict]:
        """Parse Gemini output that may contain fenced JSON or explanatory wrappers."""
        if not raw_text:
            return []

        candidates: List[str] = [raw_text.strip()]

        # Prefer fenced code blocks when present.
        for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw_text, re.IGNORECASE):
            block = (m.group(1) or "").strip()
            if block:
                candidates.append(block)

        # Try to isolate likely JSON array/object regions.
        array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", raw_text)
        if array_match:
            candidates.append(array_match.group(0).strip())
        obj_match = re.search(r"\{\s*\"questions\"[\s\S]*\}", raw_text)
        if obj_match:
            candidates.append(obj_match.group(0).strip())

        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            try:
                parsed = json.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
                return parsed["questions"]
        return []

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

    def _parse_question_object_payload(raw_text: str) -> Optional[Dict[str, Any]]:
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

    def _parse_qnum_from_anchor(text: str) -> Optional[int]:
        if not text:
            return None
        normalized = re.sub(r"\s+", " ", text).strip()
        patterns = [
            re.compile(r"^\s*[Qq](?:uestion)?\s*[:.\-]?\s*(\d{1,3})\b"),
            re.compile(r"^\s*(\d{1,3})\s*[\.\)]\s+"),
            re.compile(r"^\s*(\d{1,3})\s+"),
            re.compile(r"\b[Qq]\s*(\d{1,3})\b"),
        ]
        for pattern in patterns:
            m = pattern.search(normalized)
            if not m:
                continue
            try:
                qn = int(m.group(1))
            except Exception:
                continue
            if 0 < qn <= 500:
                return qn
        return None

    def _is_section_heading(text: str) -> bool:
        if not text:
            return False
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) > 120:
            return False
        upper = normalized.upper()
        if re.match(r"^\s*(SECTION|PART)\b", upper):
            return True
        if re.match(r"^\s*(VERY\s+SHORT\s+ANSWER|SHORT\s+ANSWER|LONG\s+ANSWER|CASE\s+STUDY)\b", upper):
            return True
        if re.match(r"^\s*INTERNAL\s+CHOICE\b", upper):
            return True
        if re.match(r"^\s*\(?OR\)?\s*$", upper):
            return True
        return False

    def _is_isolated_question_prefix(text: str) -> bool:
        if not text:
            return False
        return bool(
            re.match(
                r"^\s*(?:Q(?:uestion)?\s*)?\d{1,3}\s*(?:[.\):\-]|$)",
                text.strip(),
                re.IGNORECASE,
            )
        )

    def _is_subpart_pattern(text: str) -> bool:
        if not text:
            return False
        t = text.strip()
        patterns = [
            re.compile(r"^\s*\(?[a-z]\)\s+", re.IGNORECASE),
            re.compile(r"^\s*[a-z]\)\s+", re.IGNORECASE),
            re.compile(r"^\s*\(?[ivxlcdm]{1,6}\)\s+", re.IGNORECASE),
            re.compile(r"^\s*[ivxlcdm]{1,6}\)\s+", re.IGNORECASE),
        ]
        return any(p.search(t) for p in patterns)

    def _has_marks_pattern(text: str) -> bool:
        if not text:
            return False
        t = text.strip()
        if re.search(r"\b\d+(?:\.\d+)?\s*marks?\b", t, re.IGNORECASE):
            return True
        if re.search(r"\(\s*\d+(?:\.\d+)?\s*\)\s*(marks?)?$", t, re.IGNORECASE):
            return True
        if re.search(r"\bmarks?\s*[:=\-]?\s*\d+(?:\.\d+)?\b", t, re.IGNORECASE):
            return True
        return False

    def _extract_table_bboxes(tables: Any) -> List[List[float]]:
        bboxes: List[List[float]] = []
        for table in list(tables or []):
            if not isinstance(table, dict):
                continue
            bbox = table.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            try:
                x1, y1, x2, y2 = [float(v) for v in bbox]
            except Exception:
                continue
            if x2 > x1 and y2 > y1:
                bboxes.append([x1, y1, x2, y2])
        return bboxes

    def _line_inside_table(line: Dict[str, Any], table_bboxes: List[List[float]]) -> bool:
        if not table_bboxes:
            return False
        cx = (float(line.get("x", 0.0)) + float(line.get("x2", line.get("x", 0.0)))) * 0.5
        cy = (float(line.get("y", 0.0)) + float(line.get("y2", line.get("y", 0.0)))) * 0.5
        for bbox in table_bboxes:
            x1, y1, x2, y2 = bbox
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                return True
        return False

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

    def _infer_type(text: str) -> str:
        t = (text or "").lower()
        if any(k in t for k in ["mcq", "choose the correct", "multiple choice", "true/false", "tick the correct"]):
            return "mcq"
        if any(k in t for k in ["ledger", "journal", "balance sheet", "dr", "cr", "table", "account"]):
            return "table"
        if any(k in t for k in ["calculate", "compute", "numerical", "find the value"]):
            return "numerical"
        if any(k in t for k in ["short answer", "state briefly", "one word"]):
            return "short"
        return "descriptive"

    def _infer_subparts_from_text(text: str) -> List[Dict[str, Any]]:
        if not text:
            return []
        tokens = re.findall(r"\(([a-z])\)|\b([a-z])\)", text, flags=re.IGNORECASE)
        labels = []
        seen = set()
        for a, b in tokens:
            token = (a or b or "").lower()
            if token and token not in seen:
                seen.add(token)
                labels.append(token)
        subparts = []
        for token in labels[:12]:
            subparts.append({"sub_id": token, "max_marks": None, "rubric": f"Part ({token})"})
        return subparts

    def _regex_recover_question(span: Dict[str, Any], response_text: str) -> Dict[str, Any]:
        combined_text = (span.get("combined_text") or "").strip()
        qn = int(span.get("question_number"))
        marks = None
        for source in [response_text or "", combined_text]:
            m = re.search(r"(?i)\b(?:marks?|max[_\s-]?marks?)\s*[:=\-]?\s*(\d+(?:\.\d+)?)\b", source)
            if m:
                marks = _to_float(m.group(1))
                if marks is not None:
                    break
        sub_questions = _infer_subparts_from_text(combined_text)
        title = (combined_text.splitlines()[0] if combined_text else f"Question {qn}")[:200]
        return {
            "question_number": qn,
            "max_marks": marks,
            "rubric": combined_text or f"Question {qn}",
            "question_text": title,
            "is_optional": False,
            "optional_group": None,
            "required_count": None,
            "sub_questions": sub_questions,
            "question_type": _infer_type(combined_text),
        }

    def _normalize_llm_question(span: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        span_qn = int(span.get("question_number"))
        payload_qn = _parse_qnum_from_anchor(str(payload.get("question_number") or "")) or span_qn
        marks = _to_float(payload.get("marks"))
        if marks is None:
            marks = _to_float(payload.get("max_marks"))

        raw_subparts = payload.get("subparts")
        if raw_subparts is None:
            raw_subparts = payload.get("sub_questions")
        if not isinstance(raw_subparts, list):
            raw_subparts = []

        normalized_subs: List[Dict[str, Any]] = []
        for sq in raw_subparts:
            if not isinstance(sq, dict):
                continue
            sid = str(sq.get("sub_id") or sq.get("id") or sq.get("label") or "").strip()
            if not sid:
                continue
            sq_marks = _to_float(sq.get("marks"))
            if sq_marks is None:
                sq_marks = _to_float(sq.get("max_marks"))
            sq_text = str(sq.get("text") or sq.get("rubric") or f"Part ({sid})").strip()
            normalized_subs.append({
                "sub_id": sid,
                "max_marks": sq_marks,
                "rubric": sq_text,
            })

        combined_text = (span.get("combined_text") or "").strip()
        question_text = str(payload.get("question_text") or "").strip()
        if not question_text:
            question_text = (combined_text.splitlines()[0] if combined_text else f"Question {span_qn}")[:200]

        rubric = str(payload.get("rubric") or "").strip()
        if not rubric:
            rubric = combined_text or f"Question {span_qn}"

        q_type = str(payload.get("type") or payload.get("question_type") or "").strip().lower()
        if not q_type:
            q_type = _infer_type(combined_text)

        return {
            "question_number": payload_qn,
            "max_marks": marks,
            "rubric": rubric,
            "question_text": question_text,
            "is_optional": bool(payload.get("is_optional", False)),
            "optional_group": payload.get("optional_group"),
            "required_count": payload.get("required_count"),
            "sub_questions": normalized_subs,
            "question_type": q_type,
        }

    failed_chunks: List[Dict[str, Any]] = []
    extract_question_structure_from_paper.last_failed_chunks = []
    extract_question_structure_from_paper.last_question_spans = []
    try:
        if not paper_images:
            failed_chunks.append(
                {
                    "type": "empty_input",
                    "paper_type": paper_type,
                    "message": "No paper images provided for extraction",
                }
            )
            extract_question_structure_from_paper.last_failed_chunks = failed_chunks
            return []

        ocr = get_ocr_provider()
        all_lines: List[Dict[str, Any]] = []
        anchor_candidates: List[Dict[str, Any]] = []
        page_table_bboxes: Dict[int, List[List[float]]] = {}
        page_line_heights: Dict[int, List[float]] = {}

        logger.info("[EXTRACT-ANCHOR] Running OCR line scan over %s pages", len(paper_images))
        for page_idx, page_b64 in enumerate(paper_images, start=1):
            try:
                ocr_res = ocr.detect(
                    image_base64=page_b64,
                    min_conf=0.25,
                    min_words=3,
                    min_lines=2,
                    allow_fallback=True,
                )
            except Exception as e:
                failed_chunks.append(
                    {
                        "type": "ocr_page_exception",
                        "paper_type": paper_type,
                        "page": int(page_idx),
                        "error": str(e),
                    }
                )
                logger.error("[EXTRACT-ANCHOR] OCR failed for page %s: %s", page_idx, e)
                continue

            page_width = float(ocr_res.get("width") or 1.0)
            page_table_bboxes[page_idx] = _extract_table_bboxes(ocr_res.get("tables") or [])
            page_lines = list(ocr_res.get("lines") or [])
            if not page_lines:
                page_lines = list(ocr_res.get("words") or [])
                failed_chunks.append(
                    {
                        "type": "ocr_page_lines_empty",
                        "paper_type": paper_type,
                        "page": int(page_idx),
                        "fallback": "words",
                    }
                )

            page_lines.sort(key=lambda l: (float(l.get("y1", 0.0)), float(l.get("x1", 0.0))))
            for local_idx, line in enumerate(page_lines):
                text = str(line.get("text") or "").strip()
                if not text:
                    continue
                x1 = float(line.get("x1", 0.0))
                x2 = float(line.get("x2", x1))
                y1 = float(line.get("y1", 0.0))
                y2 = float(line.get("y2", y1))
                line_h = max(0.0, y2 - y1)
                if line_h > 0:
                    page_line_heights.setdefault(page_idx, []).append(line_h)
                line_doc = {
                    "line_id": f"p{page_idx}_l{local_idx + 1}",
                    "page": int(page_idx),
                    "x": x1,
                    "x2": x2,
                    "y": y1,
                    "y2": y2,
                    "line_height": line_h,
                    "page_width": page_width,
                    "raw_text": text,
                    "confidence": float(line.get("conf", line.get("confidence", 0.0)) or 0.0),
                }
                all_lines.append(line_doc)
                qn = _parse_qnum_from_anchor(text)
                is_section = _is_section_heading(text)
                if qn is not None or is_section:
                    anchor_candidates.append(
                        {
                            "page": int(page_idx),
                            "y_position": float(y1),
                            "x1": float(x1),
                            "x2": float(x2),
                            "line_height": float(line_h),
                            "page_width": float(page_width),
                            "raw_text": text,
                            "canonical_question_number": int(qn) if qn is not None else None,
                            "anchor_kind": "question" if qn is not None else "section",
                            "line_id": line_doc["line_id"],
                            "line_index": int(len(all_lines) - 1),
                        }
                    )

        all_lines.sort(key=lambda l: (int(l["page"]), float(l["y"]), float(l["x"])))
        line_id_to_index: Dict[str, int] = {}
        for idx, line in enumerate(all_lines):
            line["global_index"] = idx
            line_id_to_index[str(line.get("line_id"))] = idx

        for anchor in anchor_candidates:
            line_id = str(anchor.get("line_id") or "")
            if line_id in line_id_to_index:
                anchor["line_index"] = int(line_id_to_index[line_id])

        anchor_candidates.sort(key=lambda a: (int(a["page"]), float(a["y_position"])))

        page_median_height: Dict[int, float] = {}
        for page, heights in page_line_heights.items():
            if heights:
                try:
                    page_median_height[page] = float(median(heights))
                except Exception:
                    page_median_height[page] = float(sum(heights) / max(1, len(heights)))

        section_window_lines = int(os.getenv("EXTRACTION_SECTION_BOUNDARY_WINDOW_LINES", "12"))
        section_header_indices = sorted(
            int(line["global_index"])
            for line in all_lines
            if _is_section_heading(str(line.get("raw_text") or ""))
        )

        def _section_boundary_within_window(line_index: int) -> bool:
            if line_index < 0 or not section_header_indices:
                return False
            for sec_idx in reversed(section_header_indices):
                if sec_idx >= line_index:
                    continue
                gap = line_index - sec_idx
                if gap <= section_window_lines:
                    return True
                # Earlier section headers are even farther away.
                break
            return False

        # STEP 2 — Anchor scoring (candidates only -> filtered anchors).
        scored_candidates: List[Dict[str, Any]] = []
        rejected_low_score = 0
        prev_seen_qn: Optional[int] = None
        for cand in anchor_candidates:
            qn = cand.get("canonical_question_number")
            if qn is None:
                continue

            score = 0
            trace: Dict[str, Any] = {}
            text = str(cand.get("raw_text") or "")
            page = int(cand.get("page") or 1)
            width = float(cand.get("page_width") or 1.0)
            x1 = float(cand.get("x1") or 0.0)
            line_h = float(cand.get("line_height") or 0.0)
            page_med_h = float(page_median_height.get(page, 0.0) or 0.0)
            line_index = int(cand.get("line_index") or -1)
            section_boundary_detected = _section_boundary_within_window(line_index)
            trace["section_boundary_detected"] = bool(section_boundary_detected)

            if x1 <= float(width * 0.38):
                score += 2
                trace["left_margin"] = 2
            else:
                trace["left_margin"] = 0

            isolated = _is_isolated_question_prefix(text)
            if isolated:
                score += 2
                trace["isolated_prefix"] = 2
            else:
                trace["isolated_prefix"] = 0

            # Section-aware rule: near section boundaries, avoid sequence rejection pressure.
            # Sequence now contributes as a penalty-only signal outside section windows.
            sequential = False
            sequence_penalty = 0
            if prev_seen_qn is not None and not section_boundary_detected:
                if int(qn) in (int(prev_seen_qn), int(prev_seen_qn) + 1):
                    sequential = True
                elif int(qn) < int(prev_seen_qn):
                    sequence_penalty = -2
                elif int(qn) > int(prev_seen_qn) + 6:
                    sequence_penalty = -2
                elif int(qn) > int(prev_seen_qn) + 3:
                    sequence_penalty = -1
            score += sequence_penalty
            trace["sequence_penalty"] = int(sequence_penalty)

            if _is_subpart_pattern(text):
                score -= 3
                trace["subpart_penalty"] = -3
            else:
                trace["subpart_penalty"] = 0

            if _line_inside_table(cand, page_table_bboxes.get(page, [])):
                score -= 3
                trace["table_penalty"] = -3
            else:
                trace["table_penalty"] = 0

            inline_sentence = len(text.strip()) > 70 and not isolated
            small_font = bool(page_med_h > 0 and line_h > 0 and line_h < (0.65 * page_med_h))
            if inline_sentence or small_font:
                score -= 2
                trace["inline_or_small_penalty"] = -2
            else:
                trace["inline_or_small_penalty"] = 0

            if _has_marks_pattern(text):
                score -= 2
                trace["marks_penalty"] = -2
            else:
                trace["marks_penalty"] = 0

            trace["isolated"] = isolated
            trace["sequential_match"] = sequential
            trace["small_font"] = small_font
            trace["inline_sentence"] = inline_sentence
            trace["score_total"] = int(score)

            cand = {
                **cand,
                "anchor_score": int(score),
                "anchor_trace": trace,
                "section_boundary_detected": bool(section_boundary_detected),
            }
            # Lowered threshold from 3 to 1 to catch more valid questions
            # Section boundaries get extra leniency
            min_score = 0 if section_boundary_detected else 1
            if int(score) >= min_score:
                scored_candidates.append(cand)
            else:
                rejected_low_score += 1
            prev_seen_qn = int(qn)

        scored_candidates.sort(key=lambda a: (int(a["page"]), float(a["y_position"])))

        # STEP 3 — Sequence repair (reject outliers).
        question_anchors: List[Dict[str, Any]] = []
        sequence_rejected = 0
        section_boundary_kept = 0
        for idx, cand in enumerate(scored_candidates):
            qn = int(cand.get("canonical_question_number"))
            if not question_anchors:
                question_anchors.append(cand)
                continue

            prev = question_anchors[-1]
            prev_qn = int(prev.get("canonical_question_number"))
            delta = qn - prev_qn
            section_boundary_detected = bool(cand.get("section_boundary_detected"))

            # After a section header, do not reject anchors just because numbering jumps.
            if section_boundary_detected:
                same_page = int(cand.get("page")) == int(prev.get("page"))
                y_gap = abs(float(cand.get("y_position", 0.0)) - float(prev.get("y_position", 0.0)))
                if delta == 0 and same_page and y_gap < 120:
                    sequence_rejected += 1
                    continue
                question_anchors.append(cand)
                section_boundary_kept += 1
                continue

            if delta < 0:
                sequence_rejected += 1
                continue

            if delta == 0:
                same_page = int(cand.get("page")) == int(prev.get("page"))
                y_gap = abs(float(cand.get("y_position", 0.0)) - float(prev.get("y_position", 0.0)))
                if same_page and y_gap < 120:
                    sequence_rejected += 1
                    continue
                question_anchors.append(cand)
                continue

            # Allow small numbering gaps before considering outlier rejection.
            if delta <= 6:
                question_anchors.append(cand)
                continue

            # Large jump: keep only when very confident and not contradicted by near-sequential lookahead.
            next_qn = None
            if idx + 1 < len(scored_candidates):
                try:
                    next_qn = int(scored_candidates[idx + 1].get("canonical_question_number"))
                except Exception:
                    next_qn = None
            if next_qn is not None and 0 <= (next_qn - prev_qn) <= 3:
                sequence_rejected += 1
                continue
            if delta <= 8 and int(cand.get("anchor_score", 0)) >= 7:
                question_anchors.append(cand)
            else:
                sequence_rejected += 1

        failed_chunks.append(
            {
                "type": "anchor_filter_summary",
                "paper_type": paper_type,
                "candidate_count": int(len(anchor_candidates)),
                "scored_question_candidates": int(len(scored_candidates)),
                "filtered_anchor_count": int(len(question_anchors)),
                "rejected_low_score": int(rejected_low_score),
                "sequence_rejected": int(sequence_rejected),
                "section_boundary_candidates": int(
                    sum(1 for c in scored_candidates if c.get("section_boundary_detected"))
                ),
                "section_boundary_kept": int(section_boundary_kept),
                "section_boundary_window_lines": int(section_window_lines),
            }
        )
        logger.info(
            "[EXTRACT-ANCHOR] candidates=%s scored=%s kept=%s low_score_reject=%s seq_reject=%s section_kept=%s",
            len(anchor_candidates),
            len(scored_candidates),
            len(question_anchors),
            rejected_low_score,
            sequence_rejected,
            section_boundary_kept,
        )

        if not question_anchors:
            failed_chunks.append(
                {
                    "type": "no_question_anchors",
                    "paper_type": paper_type,
                    "total_pages": int(len(paper_images)),
                    "lines_seen": int(len(all_lines)),
                    "candidate_count": int(len(anchor_candidates)),
                }
            )
            extract_question_structure_from_paper.last_failed_chunks = failed_chunks
            return []

        # Build question spans from each anchor to next distinct question anchor.
        question_spans: List[Dict[str, Any]] = []
        i = 0
        while i < len(question_anchors):
            anchor = question_anchors[i]
            qn = int(anchor["canonical_question_number"])
            start_idx = int(anchor["line_index"])

            j = i + 1
            while j < len(question_anchors) and int(question_anchors[j]["canonical_question_number"]) == qn:
                j += 1

            end_idx = int(question_anchors[j]["line_index"]) - 1 if j < len(question_anchors) else len(all_lines) - 1
            if end_idx < start_idx:
                end_idx = start_idx
            span_blocks = all_lines[start_idx:end_idx + 1]
            combined_text = "\n".join((b.get("raw_text") or "").strip() for b in span_blocks if (b.get("raw_text") or "").strip()).strip()
            page_values = [int(b["page"]) for b in span_blocks] if span_blocks else [int(anchor["page"])]

            question_spans.append(
                {
                    "question_number": int(qn),
                    "page_range": [int(min(page_values)), int(max(page_values))],
                    "blocks": span_blocks,
                    "combined_text": combined_text,
                }
            )
            i = j

        extract_question_structure_from_paper.last_question_spans = question_spans
        logger.info("[EXTRACT-SPAN] Built %s question spans from %s anchors", len(question_spans), len(question_anchors))

        # Extract each question span independently (never mix multiple questions).
        per_question_retries = 4
        extracted_questions: List[Dict[str, Any]] = []

        for span in question_spans:
            qn = int(span["question_number"])
            span_text = (span.get("combined_text") or "").strip()
            if not span_text:
                failed_chunks.append(
                    {
                        "type": "empty_question_span",
                        "paper_type": paper_type,
                        "question_number": int(qn),
                        "page_range": span.get("page_range"),
                    }
                )
                extracted_questions.append(_regex_recover_question(span, ""))
                continue

            prompt = f"""Extract blueprint for exactly ONE question from OCR text.

Question span OCR text (single question):
{span_text}

Rules:
- Return a single JSON object.
- question_number MUST be {qn}.
- Never include another question.
- If uncertain about marks, use null.
- Keep subparts as an array (empty if none).

Return ONLY JSON with this exact schema:
{{
  "question_number": {qn},
  "marks": 0,
  "type": "descriptive",
  "subparts": [
    {{
      "sub_id": "a",
      "marks": 0,
      "text": "subpart text"
    }}
  ],
  "question_text": "short title",
  "rubric": "full question text",
  "is_optional": false,
  "optional_group": null,
  "required_count": null
}}"""

            parsed_question: Optional[Dict[str, Any]] = None
            last_response_text = ""

            for attempt in range(per_question_retries):
                try:
                    chat = LlmChat(
                        api_key=api_key,
                        session_id=f"extract_q_{uuid.uuid4().hex[:8]}",
                        system_message=(
                            "You extract one exam question as strict JSON. "
                            "No prose, no markdown, only JSON object."
                        ),
                    ).with_model("gemini", "gemini-2.5-flash").with_params(
                        temperature=0,
                        response_mime_type="application/json",
                    )

                    response = await ai_call_with_timeout(
                        chat,
                        UserMessage(text=prompt),
                        timeout_seconds=60,
                        operation_name=f"Question extraction q{qn} attempt {attempt + 1}",
                    )
                    last_response_text = (response.text if hasattr(response, "text") else str(response) or "").strip()
                    payload = _parse_question_object_payload(last_response_text)
                    if payload:
                        parsed_question = _normalize_llm_question(span, payload)
                        break

                    failed_chunks.append(
                        {
                            "type": "question_parse_failure",
                            "paper_type": paper_type,
                            "question_number": int(qn),
                            "page_range": span.get("page_range"),
                            "attempt": int(attempt + 1),
                            "response_preview": last_response_text[:600],
                        }
                    )
                except Exception as e:
                    failed_chunks.append(
                        {
                            "type": "question_extract_exception",
                            "paper_type": paper_type,
                            "question_number": int(qn),
                            "page_range": span.get("page_range"),
                            "attempt": int(attempt + 1),
                            "error": str(e),
                        }
                    )
                    logger.warning("[EXTRACT-Q] q%s attempt %s failed: %s", qn, attempt + 1, e)
                if attempt < per_question_retries - 1:
                    await asyncio.sleep(1.0 + float(attempt))

            if parsed_question is None:
                recovered = _regex_recover_question(span, last_response_text)
                extracted_questions.append(recovered)
                failed_chunks.append(
                    {
                        "type": "question_regex_recovery",
                        "paper_type": paper_type,
                        "question_number": int(qn),
                        "page_range": span.get("page_range"),
                        "used_fallback": True,
                    }
                )
            else:
                extracted_questions.append(parsed_question)

        # Deduplicate by question number (prefer richer rubric text).
        dedup_map: Dict[int, Dict[str, Any]] = {}
        for q in extracted_questions:
            q_num = _parse_qnum_from_anchor(str(q.get("question_number") or ""))
            if q_num is None:
                continue
            current = dedup_map.get(q_num)
            if current is None or len(str(q.get("rubric") or "")) > len(str(current.get("rubric") or "")):
                dedup_map[q_num] = q

        final_questions = [dedup_map[n] for n in sorted(dedup_map.keys())]
        final_questions = normalize_extracted_questions(final_questions)

        # Completeness gate: enforce contiguous Q1..Qmax.
        parsed_nums = sorted({
            int(_parse_qnum_from_anchor(str(q.get("question_number") or "")))
            for q in final_questions
            if _parse_qnum_from_anchor(str(q.get("question_number") or "")) is not None
        })
        if not parsed_nums:
            failed_chunks.append(
                {
                    "type": "no_questions_after_extraction",
                    "paper_type": paper_type,
                }
            )
            extract_question_structure_from_paper.last_failed_chunks = failed_chunks
            return []

        max_q = max(parsed_nums)
        expected = set(range(1, max_q + 1))
        missing = sorted(expected - set(parsed_nums))
        if missing:
            failed_chunks.append(
                {
                    "type": "completeness_gap",
                    "paper_type": paper_type,
                    "parsed_numbers": parsed_nums,
                    "missing_numbers": missing,
                    "max_question_number": int(max_q),
                }
            )
            logger.error(
                "[EXTRACT-COMPLETE] Contiguous numbering failed for %s. Parsed=%s Missing=%s",
                paper_type,
                parsed_nums,
                missing,
            )
            extract_question_structure_from_paper.last_failed_chunks = failed_chunks
            return []

        logger.info(
            "[EXTRACT-COMPLETE] Extracted %s questions with contiguous numbering Q1..Q%s",
            len(final_questions),
            max_q,
        )
        extract_question_structure_from_paper.last_failed_chunks = failed_chunks
        return final_questions

    except Exception as e:
        logger.error(f"Error extracting question structure: {e}")
        failed_chunks.append(
            {
                "type": "question_structure_exception",
                "paper_type": paper_type,
                "error": str(e),
            }
        )
        extract_question_structure_from_paper.last_failed_chunks = failed_chunks
        return []


# ============== AUTO EXTRACT QUESTIONS ==============

def _parse_question_number(value: Any) -> Optional[int]:
    """Parse numeric question number from values like 1, '1', 'Q1', 'Question 1'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = int(value)
        return num if num > 0 else None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    num = int(match.group(1))
    return num if num > 0 else None


def _validate_extraction_completeness(
    extracted_questions: List[dict],
    expected_question_count: Optional[int],
) -> Dict[str, Any]:
    """
    Validate that extraction covers all expected question numbers.
    Returns:
      { "ok": bool, "parsed_numbers": List[int], "missing": List[int], "reason": str }
    """
    parsed_numbers = sorted({
        n for n in (_parse_question_number(q.get("question_number")) for q in (extracted_questions or []))
        if n is not None
    })
    if not parsed_numbers:
        return {
            "ok": False,
            "parsed_numbers": [],
            "missing": [],
            "reason": "No valid numeric question numbers were extracted.",
        }

    expected = int(expected_question_count or 0)
    if expected > 0:
        missing = sorted(set(range(1, expected + 1)) - set(parsed_numbers))
        if missing:
            return {
                "ok": False,
                "parsed_numbers": parsed_numbers,
                "missing": missing,
                "reason": f"Missing expected question numbers: {missing}",
            }
        return {"ok": True, "parsed_numbers": parsed_numbers, "missing": [], "reason": ""}

    # Fallback validation: if numbering starts at Q1, enforce no gaps up to max observed.
    if parsed_numbers[0] == 1:
        missing = sorted(set(range(1, parsed_numbers[-1] + 1)) - set(parsed_numbers))
        if missing:
            return {
                "ok": False,
                "parsed_numbers": parsed_numbers,
                "missing": missing,
                "reason": f"Numbering has gaps: {missing}",
            }

    return {"ok": True, "parsed_numbers": parsed_numbers, "missing": [], "reason": ""}


def _normalize_sub_id(value: Any) -> str:
    """Normalize sub-question id to a stable comparable key."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"^[\(\)\[\]\{\}\s\.\-]+|[\(\)\[\]\{\}\s\.\-]+$", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _question_number_key(value: Any) -> str:
    n = _parse_question_number(value)
    return str(n) if n is not None else ""


def _pick_better_text(current: str, candidate: str) -> str:
    """Prefer richer text while avoiding placeholder-only replacements."""
    current = (current or "").strip()
    candidate = (candidate or "").strip()
    if not current:
        return candidate
    if not candidate:
        return current

    placeholders = ("answer context not clear", "question")
    current_is_placeholder = any(p in current.lower() for p in placeholders)
    candidate_is_placeholder = any(p in candidate.lower() for p in placeholders)

    if current_is_placeholder and not candidate_is_placeholder:
        return candidate
    if candidate_is_placeholder and not current_is_placeholder:
        return current
    return candidate if len(candidate) > len(current) else current


def _sub_sort_key(sub_id: str):
    """Sort sub-ids like a,b,c,i,ii,iii,1,2 in natural exam order."""
    sid = _normalize_sub_id(sub_id)
    roman_map = {
        "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
        "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10
    }
    if sid in roman_map:
        return (0, roman_map[sid], sid)
    if len(sid) == 1 and sid.isalpha():
        return (1, ord(sid), sid)
    if sid.isdigit():
        return (2, int(sid), sid)
    return (3, 0, sid)


def _dedupe_and_sort_questions(extracted_questions: List[dict]) -> List[dict]:
    """
    Merge duplicate questions (common in bilingual papers) and return sequential order.
    """
    merged: Dict[int, dict] = {}
    unknowns: List[dict] = []

    for raw in extracted_questions or []:
        q_num = _parse_question_number(raw.get("question_number"))
        if q_num is None:
            candidate = dict(raw)
            candidate.setdefault("question_text", "")
            candidate.setdefault("rubric", "")
            candidate.setdefault("sub_questions", [])
            unknowns.append(candidate)
            continue

        candidate = dict(raw)
        candidate["question_number"] = q_num
        candidate.setdefault("question_text", "")
        candidate.setdefault("rubric", "")
        candidate.setdefault("sub_questions", [])

        if q_num not in merged:
            merged[q_num] = candidate
            continue

        existing = merged[q_num]
        existing["question_text"] = _pick_better_text(existing.get("question_text"), candidate.get("question_text"))
        existing["rubric"] = _pick_better_text(existing.get("rubric"), candidate.get("rubric"))

        # Keep the higher non-zero max marks if duplicates disagree.
        ex_marks = float(existing.get("max_marks") or 0)
        cand_marks = float(candidate.get("max_marks") or 0)
        if cand_marks > ex_marks:
            existing["max_marks"] = cand_marks

        # Merge sub-questions by normalized sub_id.
        existing_subs = { _normalize_sub_id(sq.get("sub_id")): sq for sq in (existing.get("sub_questions") or []) }
        for sq in (candidate.get("sub_questions") or []):
            key = _normalize_sub_id(sq.get("sub_id"))
            if not key:
                continue
            if key not in existing_subs:
                existing_subs[key] = sq
                continue
            ex_sq = existing_subs[key]
            ex_sq["rubric"] = _pick_better_text(ex_sq.get("rubric"), sq.get("rubric"))
            ex_sq_marks = float(ex_sq.get("max_marks") or 0)
            sq_marks = float(sq.get("max_marks") or 0)
            if sq_marks > ex_sq_marks:
                ex_sq["max_marks"] = sq_marks

        existing["sub_questions"] = sorted(
            list(existing_subs.values()),
            key=lambda s: _sub_sort_key(str(s.get("sub_id", ""))),
        )
        merged[q_num] = existing

    ordered = [merged[q] for q in sorted(merged.keys())]
    return ordered + unknowns


async def auto_extract_questions(
    exam_id: str,
    force: bool = False,
    use_model_answer_fallback: bool = True,
    lock_owner: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Auto-extract COMPLETE question structure from question paper (priority) or answer sheets.
    
    Priority:
    1. Question Paper (if exists)
    2. Answer Sheets (if exists)
    3. Model Answer (optional fallback only when enabled)

    If 'force' is True, re-extraction is performed even if already extracted from the target source.
    """
    from app.layers.ai_structured.engine import extract_and_persist

    try:
        # AI-structured pipeline cutover (image-first, deterministic, versioned blueprint).
        return await extract_and_persist(exam_id=exam_id, force=force, lock_owner=lock_owner)
    except Exception as e:
        logger.error(f"AI-structured extraction error for {exam_id}: {e}", exc_info=True)
        return {"success": False, "message": f"Error during extraction: {str(e)}"}

    try:
        # Get exam
        exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        if not exam:
            logger.error(f"Auto-extraction failed: Exam {exam_id} not found")
            return {"success": False, "message": "Exam not found"}
        exam_type = str(exam.get("exam_type", "") or "").lower()
        # Force AWS Textract for all non-UPSC exams (college OCR removed)
        use_aws_pipeline = exam_type != "upsc"
        use_college_v3_extraction = False

        # Check available sources
        qp_imgs = await get_exam_question_paper_images(exam_id)
        answer_sheet_imgs = await get_exam_answer_sheet_images(exam_id)
        ma_imgs = await get_exam_model_answer_images(exam_id)

        target_source = None
        images_to_use = []

        if qp_imgs:
            target_source = "question_paper"
            images_to_use = qp_imgs
        elif answer_sheet_imgs:
            target_source = "answer_sheet"
            images_to_use = answer_sheet_imgs
        elif use_model_answer_fallback and ma_imgs:
            target_source = "model_answer"
            images_to_use = ma_imgs
        else:
            return {"success": False, "message": "No question paper or answer sheets available for extraction"}

        # Check if already extracted
        current_source = exam.get("extraction_source")
        questions_exist = len(exam.get("questions", [])) > 0 and any(q.get("rubric") for q in exam.get("questions", []))

        if not force and questions_exist and current_source == target_source:
            logger.info(f"Skipping extraction for {exam_id}: Already extracted from {current_source}")
            return {
                "success": True,
                "message": f"Questions already extracted from {target_source.replace('_', ' ')}",
                "count": len(exam.get("questions", [])),
                "source": target_source,
                "skipped": True
            }

        logger.info(f"Auto-extracting COMPLETE question structure for {exam_id} from {target_source} (Force={force})")

        # Perform NEW structure extraction
        extracted_questions = []
        failed_chunks: List[Dict[str, Any]] = []
        blueprint_payload: Optional[Dict[str, Any]] = None
        if use_aws_pipeline:
            qp_pdf_bytes = b""
            try:
                if target_source == "question_paper":
                    qp_pdf_bytes = await get_exam_question_paper_pdf_bytes(exam_id)
            except Exception:
                qp_pdf_bytes = b""
            if not qp_pdf_bytes:
                qp_pdf_bytes = _images_to_pdf_bytes(images_to_use)
            blueprint_payload = await extract_aws_blueprint(
                exam_id=exam_id,
                question_paper_pdf_bytes=qp_pdf_bytes,
            )
            extracted_questions = list(blueprint_payload.get("questions") or [])
        else:
            extracted_questions = await extract_question_structure_from_paper(
                images_to_use,
                paper_type=target_source
            )
            failed_chunks = list(getattr(extract_question_structure_from_paper, "last_failed_chunks", []) or [])
            if failed_chunks:
                logger.warning(
                    "Extraction had %s failed chunk diagnostics for exam %s",
                    len(failed_chunks),
                    exam_id,
                )

        if not extracted_questions and use_aws_pipeline:
            extracted_questions = [
                {
                    "question_number": "unknown_1",
                    "question_text": "",
                    "rubric": "",
                    "max_marks": None,
                    "sub_questions": [],
                    "source": "fallback_span",
                }
            ]
        if not extracted_questions and not use_aws_pipeline:
            logger.warning(f"Structure extraction returned no questions for {exam_id} from {target_source}")
            return {"success": False, "message": f"Failed to extract question structure from {target_source.replace('_', ' ')}"}

        extracted_questions = _dedupe_and_sort_questions(extracted_questions)
        if not extracted_questions:
            return {
                "success": False,
                "message": f"Could not normalize question extraction from {target_source.replace('_', ' ')}",
            }

        # Validate completeness against the current extraction span (and exam metadata),
        # not only stale pre-existing question counts.
        expected_question_count = derive_expected_question_count(
            exam,
            fallback_questions=extracted_questions,
        )

        if REQUIRE_COMPLETE_QUESTION_EXTRACTION and not use_aws_pipeline:
            completeness = _validate_extraction_completeness(extracted_questions, expected_question_count)
            if not completeness["ok"]:
                logger.error(
                    f"Incomplete extraction for exam {exam_id} from {target_source}: {completeness['reason']}. "
                    f"Parsed={completeness['parsed_numbers']}, expected_count={expected_question_count}"
                )
                return {
                    "success": False,
                    "message": (
                        f"Incomplete question extraction from {target_source.replace('_', ' ')}. "
                        f"{completeness['reason']}"
                    ),
                    "source": target_source,
                    "parsed_question_numbers": completeness["parsed_numbers"],
                    "missing_question_numbers": completeness["missing"],
                }

        # Preserve existing marks from exam schema when re-extraction misses them.
        existing_questions = exam.get("questions") or []
        existing_map: Dict[str, dict] = {
            _question_number_key(q.get("question_number")): q for q in existing_questions
            if _question_number_key(q.get("question_number"))
        }

        for q in extracted_questions:
            q_key = _question_number_key(q.get("question_number"))
            existing_q = existing_map.get(q_key) or {}

            extracted_q_max = float(q.get("max_marks") or 0)
            existing_q_max = float(existing_q.get("max_marks") or 0)
            if extracted_q_max <= 0 and existing_q_max > 0:
                q["max_marks"] = existing_q_max
            elif (
                existing_q_max > 0
                and extracted_q_max > 0
                and extracted_q_max < existing_q_max
                and extracted_q_max <= 1
            ):
                # Common OCR/LLM failure: replaced real marks with fallback 1.
                q["max_marks"] = existing_q_max

            existing_subs = {
                _normalize_sub_id(sq.get("sub_id")): sq
                for sq in (existing_q.get("sub_questions") or [])
                if _normalize_sub_id(sq.get("sub_id"))
            }
            for sq in (q.get("sub_questions") or []):
                sq_key = _normalize_sub_id(sq.get("sub_id"))
                existing_sq = existing_subs.get(sq_key) or {}
                extracted_sq_max = float(sq.get("max_marks") or 0)
                existing_sq_max = float(existing_sq.get("max_marks") or 0)
                if extracted_sq_max <= 0 and existing_sq_max > 0:
                    sq["max_marks"] = existing_sq_max
                elif (
                    existing_sq_max > 0
                    and extracted_sq_max > 0
                    and extracted_sq_max < existing_sq_max
                    and extracted_sq_max <= 1
                ):
                    sq["max_marks"] = existing_sq_max

        # Preserve missing marks as 0 so visual/audit layers can resolve them.
        for q in extracted_questions:
            if not q.get("max_marks") or float(q.get("max_marks") or 0) <= 0:
                q["max_marks"] = 0
            if q.get("sub_questions"):
                for sq in q["sub_questions"]:
                    if not sq.get("max_marks") or float(sq.get("max_marks") or 0) <= 0:
                        sq["max_marks"] = 0

        # Enrich extracted questions with a deterministic blueprint footprint.
        blueprint_rows = build_question_blueprint_from_exam_questions(extracted_questions)
        blueprint_by_q = {int(b["question_id"]): b for b in blueprint_rows if b.get("question_id") is not None}
        for q in extracted_questions:
            try:
                q_num = int(q.get("question_number"))
            except Exception:
                continue
            b = blueprint_by_q.get(q_num)
            if not b:
                continue
            q["question_type"] = b.get("type", "theory")
            q["expected_components"] = b.get("expected_components", [])

        # VALIDATE extraction
        print(f"\n{'='*70}")
        print(f"[EXTRACTION-VALIDATION] Validating extracted questions...")
        print(f"[EXTRACTION-VALIDATION] Total questions extracted: {len(extracted_questions)}")
        
        for idx, q in enumerate(extracted_questions, 1):
            q_num = q.get('question_number')
            q_text = q.get('question_text', '')[:50]
            q_marks = q.get('max_marks', '?')
            sub_q_count = len(q.get('sub_questions', []))
            print(f"[EXTRACTION-VALIDATION] {idx}. Q{q_num}: '{q_text}...' | Marks={q_marks} | SubQ={sub_q_count}")
        
        q_nums = [q.get('question_number') for q in extracted_questions]
        print(f"[EXTRACTION-VALIDATION] Question numbers: {q_nums}")
        print(f"{'='*70}\n")
        
        logger.info(f"✅ Extraction returned {len(extracted_questions)} questions: Q{q_nums}")

        # Keep totals consistent with final optional-group aware computation below.
        # (Do not persist provisional totals from raw sub-question sums.)
        print(f"\n[EXTRACTION] Got {len(extracted_questions)} questions from AI: Q{q_nums}\n")

        # Calculate total marks from extracted structure, handling optional questions
        total_marks = 0
        optional_groups = {}
        
        for q in extracted_questions:
            is_optional = q.get("is_optional", False)
            
            if is_optional:
                group_id = q.get("optional_group", "default_optional")
                if group_id not in optional_groups:
                    optional_groups[group_id] = {
                        "questions": [],
                        "required_count": q.get("required_count", 0)
                    }
                optional_groups[group_id]["questions"].append(q)
            else:
                total_marks += q.get("max_marks", 0)
        
        # Calculate marks for optional groups
        for group_id, group_data in optional_groups.items():
            questions = group_data["questions"]
            # Normalize required_count to an int (avoid None comparisons)
            required_count = int(group_data["required_count"] or 0)
            
            if required_count > 0 and len(questions) > 0:
                marks_per_question = float(questions[0].get("max_marks") or 0)
                group_effective_marks = marks_per_question * min(required_count, len(questions))
                total_marks += group_effective_marks
                logger.info(f"Optional group '{group_id}': {len(questions)} questions, need {required_count}, contributing {group_effective_marks} marks")
            else:
                for q in questions:
                    total_marks += float(q.get("max_marks") or 0)

        logger.info(f"Calculated total marks from extraction: {total_marks} (including optional question handling)")

        # Preserve user's original total_marks if it was explicitly set during exam creation
        user_total_marks = exam.get("total_marks", 100)

        preserve_user_marks = bool(user_total_marks and user_total_marks != 100)
        # Guard against stale/corrupted low totals from previous failed runs.
        if preserve_user_marks and total_marks > 0 and float(user_total_marks) < max(5.0, total_marks * 0.25):
            preserve_user_marks = False
            logger.warning(
                "User total marks (%s) looks stale vs extracted (%s); using extracted value",
                user_total_marks,
                total_marks,
            )

        if preserve_user_marks:
            final_total_marks = user_total_marks
            logger.info(f"✓ Preserving user's total marks: {final_total_marks} (extracted: {total_marks})")
        else:
            final_total_marks = total_marks
            logger.info(f"✓ Using extracted total marks: {final_total_marks}")

        # STEP 1: Delete old questions for this exam to prevent duplicates
        delete_result = await db.questions.delete_many({"exam_id": exam_id})
        logger.info(f"Deleted {delete_result.deleted_count} old questions for exam {exam_id}")
        print(f"[EXTRACTION-DB] Deleted {delete_result.deleted_count} old questions")

        # STEP 2: Prepare questions for insertion with exam_id and unique question_id
        questions_to_insert = []
        for q in extracted_questions:
            question_doc = {
                "question_id": f"q_{uuid.uuid4().hex[:12]}",
                "exam_id": exam_id,
                **q
            }
            questions_to_insert.append(question_doc)

        # STEP 3: Insert questions into the questions collection
        if questions_to_insert:
            await db.questions.insert_many(questions_to_insert)
            q_nums = [q.get("question_number") for q in questions_to_insert]
            logger.info(f"Inserted {len(questions_to_insert)} questions into database: Q{q_nums}")
            print(f"[EXTRACTION-DB] Inserted {len(questions_to_insert)} questions: Q{q_nums}")
            
            # Check for missing question numbers
            if q_nums:
                parsed_q_nums = sorted({n for n in (_parse_question_number(v) for v in q_nums) if n is not None})
                if parsed_q_nums:
                    max_q_num = parsed_q_nums[-1]
                    expected_q_nums = set(range(1, max_q_num + 1))
                    actual_q_nums = set(parsed_q_nums)
                    missing_q_nums = expected_q_nums - actual_q_nums

                    if missing_q_nums:
                        print(f"[EXTRACTION-WARNING] ⚠️ MISSING QUESTIONS: {sorted(missing_q_nums)}")
                        logger.warning(f"Missing questions: {sorted(missing_q_nums)}")
                    else:
                        print(f"[EXTRACTION-OK] ✅ All questions Q1 to Q{max_q_num} present")
                        logger.info(f"✅ All questions Q1 to Q{max_q_num} extracted correctly")

        blueprint_health = None
        if blueprint_payload and blueprint_payload.get("blueprint_health"):
            blueprint_health = blueprint_payload.get("blueprint_health")
        else:
            blueprint_health = compute_blueprint_health(
                extracted_questions,
                expected_count=expected_question_count,
                failed_chunks=failed_chunks,
            )

        # STEP 4: Update exam document with questions array, metadata, and correct counts
        prior_blueprint_version = int(exam.get("blueprint_version", 0) or 0)
        next_blueprint_version = prior_blueprint_version + 1
        if use_aws_pipeline and blueprint_payload:
            prev_structured = exam.get("blueprint_spans_structured") or []
            next_structured = blueprint_payload.get("blueprint_spans_structured") or []
            if prev_structured == next_structured and prev_structured:
                next_blueprint_version = prior_blueprint_version
        update_payload: Dict[str, Any] = {
            "questions": extracted_questions,
            "questions_count": len(extracted_questions),
            "extraction_source": target_source,
            "total_marks": final_total_marks,
            "blueprint_status": (
                blueprint_payload.get("blueprint_status")
                if use_aws_pipeline and blueprint_payload
                else "ready_unlocked"
            ),
            "blueprint_locked_at": None,
            "blueprint_version": next_blueprint_version,
            "blueprint_health": blueprint_health,
        }
        if use_aws_pipeline:
            update_payload["extraction_version"] = int(exam.get("extraction_version", 0) or 0) + 1
        if exam_type == "college":
            update_payload["college_pipeline_version"] = "v3"
        if blueprint_payload:
            update_payload.update(
                {
                    "blueprint_pages": blueprint_payload.get("blueprint_pages", []),
                    "global_anchor_list": blueprint_payload.get("global_anchor_list", []),
                    "blueprint_question_pages": blueprint_payload.get("blueprint_question_pages", {}),
                    "blueprint_spans": [
                        {
                            "question_number": span.get("question_number"),
                            "preview_text": span.get("preview_text"),
                            "anchor_confidence": span.get("anchor_confidence"),
                            "span_length": span.get("span_length"),
                            "page_numbers": span.get("page_numbers", []),
                        }
                        for span in (blueprint_payload.get("question_spans") or [])
                    ],
                    "blueprint_spans_raw": blueprint_payload.get("blueprint_spans_raw", []),
                    "blueprint_spans_structured": blueprint_payload.get("blueprint_spans_structured", []),
                    "missing_questions": blueprint_payload.get("missing_questions", []),
                    "uncertain_questions": blueprint_payload.get("uncertain_questions", []),
                    "anchor_confidence_map": blueprint_payload.get("anchor_confidence_map", {}),
                    "span_previews": blueprint_payload.get("span_previews", []),
                    "numbering_gaps": blueprint_payload.get("numbering_gaps", []),
                    "duplicate_numbers": blueprint_payload.get("duplicate_numbers", []),
                    "probable_optional_groups": blueprint_payload.get("probable_optional_groups", []),
                    "textract_job_id": blueprint_payload.get("textract_job_id"),
                    "page_texts": blueprint_payload.get("page_texts", []),
                    "anchors_detected": blueprint_payload.get("anchors_detected", []),
                    "spans_built": blueprint_payload.get("spans_built", []),
                    "span_structuring_errors": blueprint_payload.get("span_structuring_errors", []),
                    "layout_segmentation_version": blueprint_payload.get("layout_segmentation_version"),
                }
            )
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": update_payload}
        )

        logger.info(f"✅ Successfully extracted and saved {len(extracted_questions)} questions with complete structure from {target_source}")
        print(f"[EXTRACTION-COMPLETE] Saved {len(extracted_questions)} questions to both db.questions and exam.questions")
        blueprint_status_final = update_payload.get("blueprint_status", "ready_unlocked")
        return {
            "success": True,
            "message": f"Successfully extracted {len(extracted_questions)} questions with structure from {target_source.replace('_', ' ')}",
            "count": len(extracted_questions),
            "total_marks": final_total_marks,
            "extracted_total_marks": total_marks,
            "source": target_source,
            "skipped": False,
            "blueprint_health": blueprint_health,
            "blueprint_status": blueprint_status_final,
        }

    except Exception as e:
        logger.error(f"Auto-extraction error for {exam_id}: {e}")
        return {"success": False, "message": f"Error during extraction: {str(e)}"}


# ============== ASYNC BACKGROUND PROCESSING ==============

async def _process_question_paper_async(exam_id: str):
    """Background processing for question paper: extract questions and refresh model answer text."""
    try:
        print(f"\n{'='*70}")
        print(f"[QP-ASYNC-START] exam_id={exam_id}")
        print(f"{'='*70}")
        logger.info(f"[QP-ASYNC] Starting question extraction for exam {exam_id}")
        exam_doc = await db.exams.find_one(
            {"exam_id": exam_id},
            {"_id": 0, "exam_type": 1, "teacher_id": 1, "exam_name": 1, "total_marks": 1},
        )
        exam_type = str((exam_doc or {}).get("exam_type", "") or "").lower()
        teacher_id = (exam_doc or {}).get("teacher_id")
        exam_name = (exam_doc or {}).get("exam_name") or "exam"
        from app.services.notifications import create_notification

        # Force extraction from question paper
        print(f"[QP-ASYNC] Calling auto_extract_questions with force=True")
        result = await auto_extract_questions(
            exam_id,
            force=True,
            lock_owner=f"upload_question_paper:{exam_id}",
        )
        print(f"[QP-ASYNC] Extraction result: {result}")

        print(f"[QP-ASYNC] Extraction result: {result}")

        # Update extraction status
        blueprint_status = result.get("blueprint_status")
        if not blueprint_status:
            blueprint_status = "ready_unlocked" if result.get("success") else "failed"
        update_data = {
            "question_extraction_status": "completed" if result.get("success") else "failed",
            "question_extraction_count": result.get("count", 0),
            "question_extraction_source": result.get("source", "question_paper"),
            "question_extraction_message": result.get("message", ""),
            "question_paper_processing": False,
            "processing_state": "idle",
            "processing_lock_owner": None,
            "question_extraction_completed_at": datetime.now(timezone.utc).isoformat(),
            "blueprint_status": blueprint_status,
            "blueprint_locked": bool(blueprint_status == "ready_locked"),
            "blueprint_locked_at": None,
            "college_pipeline_version": "v3" if exam_type == "college" else None,
            "blueprint_health": result.get("blueprint_health"),
        }
        if update_data.get("college_pipeline_version") is None:
            update_data.pop("college_pipeline_version", None)
        if update_data.get("blueprint_health") is None:
            update_data.pop("blueprint_health", None)
        print(f"[QP-ASYNC] Updating exam with: {update_data}")
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": update_data}
        )
        print(f"[QP-ASYNC] Exam updated successfully")

        logger.info(f"[QP-ASYNC] Extraction result for {exam_id}: {result}")

        # If model answer exists, re-extract text with updated questions for better grading
        print(f"[QP-ASYNC] Fetching model answer images")
        model_images = await get_exam_model_answer_images(exam_id)
        print(f"[QP-ASYNC] Got {len(model_images)} model answer images")
        if model_images:
            exam_updated = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "questions": 1})
            questions_count = len(exam_updated.get("questions", [])) if exam_updated else 0
            print(f"[QP-ASYNC] Exam has {questions_count} questions, extracting model answer text")
            model_answer_text, model_answer_map = await extract_model_answer_content(
                model_answer_images=model_images,
                questions=exam_updated.get("questions", []) if exam_updated else []
            )
            print(f"[QP-ASYNC] Model answer text: {len(model_answer_text)} chars")
            if model_answer_text or model_answer_map:
                await db.exam_files.update_one(
                    {"exam_id": exam_id, "file_type": "model_answer"},
                    {"$set": {
                        "model_answer_text": model_answer_text,
                        "model_answer_map": model_answer_map,
                        "text_extracted_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
                await db.exams.update_one(
                    {"exam_id": exam_id},
                    {"$set": {
                        "model_answer_text_status": "success",
                        "model_answer_text_chars": len(model_answer_text),
                        "model_answer_map_count": len(model_answer_map)
                    }}
                )
                logger.info(f"[QP-ASYNC] Updated model answer text ({len(model_answer_text)} chars) for exam {exam_id}")
                print(f"[QP-ASYNC] Saved model answer text successfully")
        else:
            print(f"[QP-ASYNC] No model answer images found")

        # Marking scheme validation (soft-fail)
        if MARK_VALIDATION_ENABLED:
            try:
                qp_images = await get_exam_question_paper_images(exam_id)
                validator_payload = await validate_marks_with_llm(qp_images)
                if validator_payload:
                    extracted_questions = await db.questions.find(
                        {"exam_id": exam_id},
                        {"_id": 0}
                    ).to_list(2000)
                    report = compare_validator_to_extracted(extracted_questions, validator_payload)
                    status = report.get("status", "warning")
                    now_iso = datetime.now(timezone.utc).isoformat()

                    update_fields = {
                        "mark_validation_status": status,
                        "mark_validation_report": report,
                        "mark_validation_updated_at": now_iso,
                    }
                    validator_total = _to_float_or_none(report.get("validator_total"))
                    current_total = _to_float_or_none((exam_doc or {}).get("total_marks"))
                    if validator_total and validator_total > 0:
                        if not current_total or abs(validator_total - current_total) / validator_total > 0.1:
                            update_fields["total_marks"] = validator_total

                    await db.exams.update_one(
                        {"exam_id": exam_id},
                        {"$set": update_fields}
                    )

                    validator_map = _normalize_validator_questions(validator_payload)
                    issues_by_q: Dict[int, List[Dict[str, Any]]] = {}
                    for issue in report.get("issues") or []:
                        qn = issue.get("question_number")
                        if qn:
                            issues_by_q.setdefault(int(qn), []).append(issue)

                    for q in extracted_questions or []:
                        qn = _parse_question_number(q.get("question_number"))
                        if not qn:
                            continue
                        qn = int(qn)
                        v_entry = validator_map.get(qn) or {}
                        v_subparts = [
                            {"part": k, "marks": v} for k, v in (v_entry.get("subparts") or {}).items()
                        ]
                        q_issues = issues_by_q.get(qn, [])
                        await db.questions.update_one(
                            {"exam_id": exam_id, "question_number": qn},
                            {"$set": {
                                "mark_validation": {
                                    "status": "warning" if q_issues else "ok",
                                    "validator_marks": v_entry.get("marks"),
                                    "validator_subparts": v_subparts,
                                    "issues": q_issues,
                                }
                            }}
                        )

                    logger.info(
                        "MARK_VALIDATION exam_id=%s status=%s missing=%s mismatch=%s unknown=%s inferred=%s",
                        exam_id,
                        status,
                        report.get("missing_count", 0),
                        report.get("mismatch_count", 0),
                        report.get("unknown_count", 0),
                        report.get("inferred_count", 0),
                    )
                    if status != "pass":
                        top_issues = (report.get("issues") or [])[:10]
                        logger.warning("MARK_VALIDATION_ISSUES exam_id=%s issues=%s", exam_id, top_issues)

                    if teacher_id:
                        if status == "pass":
                            await create_notification(
                                user_id=teacher_id,
                                notification_type="mark_validation_complete",
                                title="Mark Validation Complete",
                                message=(
                                    f"Marks validated for {exam_name}. "
                                    f"Missing: {report.get('missing_count', 0)}, "
                                    f"Mismatches: {report.get('mismatch_count', 0)}."
                                ),
                                link=f"/teacher/review?exam={exam_id}",
                            )
                        else:
                            await create_notification(
                                user_id=teacher_id,
                                notification_type="mark_validation_warning",
                                title="Mark Validation Found Issues",
                                message=(
                                    f"{exam_name} has mark mismatches. "
                                    f"Missing: {report.get('missing_count', 0)}, "
                                    f"Mismatches: {report.get('mismatch_count', 0)}."
                                ),
                                link=f"/teacher/review?exam={exam_id}",
                            )
            except Exception as validation_err:
                logger.warning("Mark validation failed for exam %s: %s", exam_id, validation_err)

        if teacher_id:
            await create_notification(
                user_id=teacher_id,
                notification_type="question_extraction_complete",
                title="Question Paper Processing Complete",
                message=(
                    f"Extracted {result.get('count', 0)} questions for {exam_name}. "
                    f"Total marks: {result.get('total_marks', 0)}."
                ),
                link=f"/teacher/review?exam={exam_id}",
            )

        print(f"{'='*70}")
        print(f"[QP-ASYNC-COMPLETE] exam_id={exam_id} SUCCESS")
        print(f"{'='*70}\n")

    except Exception as e:
        print(f"{'='*70}")
        print(f"[QP-ASYNC-ERROR] exam_id={exam_id}")
        print(f"[QP-ASYNC-ERROR] {str(e)}")
        import traceback
        print(traceback.format_exc())
        print(f"{'='*70}\n")
        logger.error(f"[QP-ASYNC] Failed for exam {exam_id}: {e}", exc_info=True)
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": {
                "question_extraction_status": "failed",
                "question_paper_processing": False,
                "processing_state": "idle",
                "processing_lock_owner": None,
                "question_extraction_message": str(e),
                "blueprint_status": "failed",
                "blueprint_locked": False,
                "blueprint_locked_at": None,
            }}
        )
        try:
            from app.services.notifications import create_notification
            exam_doc = await db.exams.find_one(
                {"exam_id": exam_id},
                {"_id": 0, "teacher_id": 1, "exam_name": 1},
            )
            if exam_doc and exam_doc.get("teacher_id"):
                await create_notification(
                    user_id=exam_doc["teacher_id"],
                    notification_type="question_extraction_failed",
                    title="Question Paper Processing Failed",
                    message=f"Question extraction failed for {exam_doc.get('exam_name', 'exam')}: {str(e)}",
                    link=f"/teacher/review?exam={exam_id}",
                )
        except Exception:
            logger.warning("Failed to emit question_extraction_failed notification for exam %s", exam_id)


async def _process_model_answer_async(exam_id: str):
    """Background processing for model answer: extract questions (if needed) and model answer text."""
    try:
        print(f"\n{'='*70}")
        print(f"[MA-ASYNC-START] exam_id={exam_id}")
        print(f"{'='*70}")
        logger.info(f"[MA-ASYNC] Starting model answer processing for exam {exam_id}")

        # Determine whether to force extraction (no question paper)
        print(f"[MA-ASYNC] Checking if question paper exists")
        qp_imgs = await get_exam_question_paper_images(exam_id)
        print(f"[MA-ASYNC] Question paper has {len(qp_imgs)} images")
        force_extraction = not bool(qp_imgs)
        print(f"[MA-ASYNC] Force extraction: {force_extraction}")

        # Extract questions if needed
        print(f"[MA-ASYNC] Calling auto_extract_questions with force={force_extraction}")
        result = await auto_extract_questions(
            exam_id,
            force=force_extraction,
            lock_owner=f"upload_model_answer:{exam_id}",
        )
        print(f"[MA-ASYNC] Extraction result: {result}")

        exam_before = await db.exams.find_one(
            {"exam_id": exam_id},
            {"_id": 0, "blueprint_status": 1, "blueprint_locked_at": 1, "exam_type": 1},
        ) or {}
        exam_type = str(exam_before.get("exam_type", "") or "").lower()
        prior_blueprint_status = str(exam_before.get("blueprint_status", "pending")).lower()
        keep_locked = bool(result.get("success")) and bool(result.get("skipped")) and prior_blueprint_status == "ready_locked"

        blueprint_status = result.get("blueprint_status")
        if not blueprint_status:
            blueprint_status = "ready_locked" if keep_locked else ("ready_unlocked" if result.get("success") else "failed")
        update_data = {
            "question_extraction_status": "completed" if result.get("success") else "failed",
            "question_extraction_count": result.get("count", 0),
            "question_extraction_source": result.get("source", "model_answer"),
            "question_extraction_message": result.get("message", ""),
            "processing_state": "idle",
            "processing_lock_owner": None,
            "question_extraction_completed_at": datetime.now(timezone.utc).isoformat(),
            "blueprint_status": blueprint_status,
            "blueprint_locked": bool(blueprint_status == "ready_locked"),
            "blueprint_locked_at": exam_before.get("blueprint_locked_at") if keep_locked else None,
            "college_pipeline_version": "v3" if exam_type == "college" else None,
            "blueprint_health": result.get("blueprint_health"),
        }
        if update_data.get("college_pipeline_version") is None:
            update_data.pop("college_pipeline_version", None)
        if update_data.get("blueprint_health") is None:
            update_data.pop("blueprint_health", None)
        print(f"[MA-ASYNC] Updating exam with: {update_data}")
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": update_data}
        )
        print(f"[MA-ASYNC] Exam updated with extraction status")

        # Extract model answer text for grading
        print(f"[MA-ASYNC] Fetching model answer images")
        model_images = await get_exam_model_answer_images(exam_id)
        print(f"[MA-ASYNC] Got {len(model_images)} model answer images")
        exam_updated = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "questions": 1})
        questions_count = len(exam_updated.get("questions", [])) if exam_updated else 0
        print(f"[MA-ASYNC] Exam has {questions_count} questions")
        print(f"[MA-ASYNC] Extracting model answer content text")
        model_answer_text, model_answer_map = await extract_model_answer_content(
            model_answer_images=model_images,
            questions=exam_updated.get("questions", []) if exam_updated else []
        )
        print(f"[MA-ASYNC] Extracted {len(model_answer_text) if model_answer_text else 0} chars")

        if model_answer_text or model_answer_map:
            await db.exam_files.update_one(
                {"exam_id": exam_id, "file_type": "model_answer"},
                {"$set": {
                    "model_answer_text": model_answer_text,
                    "model_answer_map": model_answer_map,
                    "text_extracted_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            await db.exams.update_one(
                {"exam_id": exam_id},
                {"$set": {
                    "model_answer_text_status": "success",
                    "model_answer_text_chars": len(model_answer_text),
                    "model_answer_map_count": len(model_answer_map)
                }}
            )
            logger.info(f"[MA-ASYNC] Model answer text extracted ({len(model_answer_text)} chars) for exam {exam_id}")
            print(f"[MA-ASYNC] Saved model answer text to database")
        else:
            print(f"[MA-ASYNC] Model answer text extraction returned empty")
            await db.exams.update_one(
                {"exam_id": exam_id},
                {"$set": {
                    "model_answer_text_status": "failed",
                    "model_answer_text_chars": 0
                }}
            )

        # Mark processing done
        print(f"[MA-ASYNC] Marking processing as done")
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": {
                "model_answer_processing": False,
                "model_answer_processed_at": datetime.now(timezone.utc).isoformat()
            }}
        )

        logger.info(f"[MA-ASYNC] Completed model answer processing for exam {exam_id}")
        print(f"{'='*70}")
        print(f"[MA-ASYNC-COMPLETE] exam_id={exam_id} SUCCESS")
        print(f"{'='*70}\n")

    except Exception as e:
        print(f"{'='*70}")
        print(f"[MA-ASYNC-ERROR] exam_id={exam_id}")
        print(f"[MA-ASYNC-ERROR] {str(e)}")
        import traceback
        print(traceback.format_exc())
        print(f"{'='*70}\n")
        logger.error(f"[MA-ASYNC] Failed for exam {exam_id}: {e}", exc_info=True)
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": {
                "model_answer_processing": False,
                "model_answer_text_status": "failed",
                "question_extraction_status": "failed",
                "processing_state": "idle",
                "processing_lock_owner": None,
                "blueprint_locked": False,
                "model_answer_processing_error": str(e)
            }}
        )
