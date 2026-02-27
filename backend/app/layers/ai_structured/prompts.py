"""Prompt templates for AI-structured layer."""

from __future__ import annotations

import json
from typing import Any, Dict, List


PROMPT_VERSION = "ai_structured_v3_multimodal_first"


EXTRACTION_SCHEMA = {
    "questions": [
        {
            "number": 1,
            "section": "string|null",
            "instruction": "string|null",
            "question_text": "string",
            "question_type": "mcq|fill_blank|very_short|short|long|passage|writing|letter|essay",
            "marks": 0,
            "mark_source": "margin|section_math|instruction|inferred",
            "mark_confidence": 0.0,
            "confidence": 0.0,
            "options": ["string"] or None,
            "subquestions": [{"label": "a|b|i|ii", "text": "string", "marks": 0, "mark_source": "margin|section_math|instruction|inferred", "mark_confidence": 0.0}],
            "or_group_id": "string|null",
            "image_evidence": [{"page_index": 0, "bbox": [0, 0, 0, 0], "visual_confidence": 0.0}],
            "ai_confidence": 0.0,
        }
    ],
    "section_math_blocks": [
        {
            "section": "string|null",
            "expression": "12x1=12",
            "question_count": 12,
            "per_question_marks": 1,
            "total_marks": 12,
            "page_index": 0,
            "confidence": 0.0,
        }
    ],
    "total_questions": 0,
    "total_marks": 0,
    "effective_total_marks": 0,
    "numbering_contiguous": True,
}


VISUAL_EXTRACTION_SCHEMA = {
    "questions": [
        {
            "number": 1,
            "page_index": 0,
            "bbox": [0, 0, 0, 0],
            "confidence": 0.0,
        }
    ],
    "subparts": [
        {
            "q": 1,
            "label": "a",
            "page_index": 0,
            "bbox": [0, 0, 0, 0],
            "confidence": 0.0,
        }
    ],
    "margin_marks": [
        {
            "q": 1,
            "sub": "a|null",
            "marks": 0,
            "text": "2+2",
            "split": [2, 2],
            "page_index": 0,
            "bbox": [0, 0, 0, 0],
            "confidence": 0.0,
        }
    ],
    "section_math_rules": [
        {
            "expression": "4 x 3 = 12",
            "count": 4,
            "per": 3,
            "total": 12,
            "start_question": 27,
            "page_index": 0,
            "bbox": [0, 0, 0, 0],
            "confidence": 0.0,
        }
    ],
    "or_pairs": [
        {"q1": 23, "q2": 24, "page_index": 0, "bbox": [0, 0, 0, 0], "confidence": 0.0}
    ],
    "headers": [
        {"kind": "section", "text": "SECTION IV", "page_index": 0, "bbox": [0, 0, 0, 0], "confidence": 0.0}
    ],
}


ALIGNMENT_SCHEMA = {
    "answers": [
        {
            "question_number": 1,
            "sub_label": "a|null",
            "answer_text": "string",
            "detected_type": "mcq|written|blank",
            "page_index": 0,
            "bbox": [0, 0, 0, 0],
            "confidence": 0.0,
        }
    ]
}


QUALITY_SCHEMA = {
    "question_quality": 0.0,
    "question_status": "graded|not_attempted|not_found",
    "question_feedback": "string",
    "confidence": 0.0,
    "sub_qualities": [{"label": "a", "quality": 0.0, "status": "graded|not_attempted|not_found"}],
}


OBJECTIVE_KEY_SCHEMA = {
    "question_number": 1,
    "key": "A|B|C|D|text",
    "confidence": 0.0,
}


STUDENT_OPTION_SCHEMA = {
    "question_number": 1,
    "selected_option": "A|B|C|D|",
    "confidence": 0.0,
    "reason": "string",
}


EXTRACTION_SYSTEM_PROMPT = """
You are an exam paper structure extraction engine.
Your job is structural parsing, not summarization.

STRICT OUTPUT:
- Return strict JSON only. No Markdown, no code fences.
- Do not include raw newlines inside string values; use \\n for line breaks.
- Do not include unescaped quotes inside string values.

STRUCTURE RULES:
1) Stage-1 only: do not assign marks. Set all marks and subquestion marks to 0.
2) Do not output or_group_id; the visual layer handles OR pairing.
3) Do not invent question numbers or create new questions.
4) Do not invent subquestions from MCQ options. MCQ options must be in options only.
5) Create subquestions only when explicit labels exist (a,b,c,i,ii) or multiple asks under the same number.
6) Section math (e.g., 12x1=12) is distribution evidence; do not split questions or create subquestions from it.
7) Preserve layout intent; do not merge distinct questions.
8) If the paper shows left-margin section math like n×m=x, it means the next n questions are m marks each. Do not create extra questions; do not assign marks.
9) If the paper says "any one/any of the following/alternative question", keep choices in question_text or options; do not create subquestions.
"""


VISUAL_EXTRACTION_SYSTEM_PROMPT = """
You are a visual structure extraction engine for exam question papers.
Your job is to read the page images directly and output ONLY structural evidence.

STRICT OUTPUT:
- Return strict JSON only. No Markdown, no code fences.
- Do not include raw newlines inside string values; use \\n for line breaks.
- Do not include unescaped quotes inside string values.

RULES:
1) Do NOT assign final marks or totals for questions. Only output visible margin marks and section math expressions.
2) Do NOT infer or compute missing marks.
3) Do NOT apply rules; return evidence only.
3) Detect question numbers, subpart labels, margin marks, section math expressions (n x m = total), OR connectors, and section headings.
4) Do NOT output question text or answers; output structural evidence only.
5) Include page_index (0-based), bbox [x1,y1,x2,y2] in pixels, and confidence for every item.
6) If section math appears inside a heading (e.g., "SECTION IV 4 x 3 = 12"), still extract the math.
7) If you can see the next question number after a section math expression, set start_question.
8) If a margin mark includes a split like "2+2", include the raw text in "text" and the parts in "split".
"""


def get_extraction_system_prompt() -> str:
    return EXTRACTION_SYSTEM_PROMPT.strip()


def get_visual_extraction_system_prompt() -> str:
    return VISUAL_EXTRACTION_SYSTEM_PROMPT.strip()


def _json_schema_block(schema_obj: Dict[str, Any]) -> str:
    return json.dumps(schema_obj, ensure_ascii=True, indent=2)


def build_extraction_prompt(
    *,
    raw_ocr_text: str,
    batch_index: int,
    total_batches: int,
    extra_rules: List[str] | None = None,
) -> str:
    rules = [
        "You are extracting structure, not summarizing prose.",
        "Question paper images are ground truth.",
        "OCR text is supporting evidence only.",
        "Do not invent question numbers.",
        "Do not assign marks; set all marks and subquestion marks to 0.",
        "Do not assign authoritative final marks; deterministic mark layer resolves marks from visual entities.",
        "Do not output or_group_id; visual layer detects OR connectors.",
        "MCQ options must be in options, never in subquestions.",
        "If the paper says 'any one/any of the following/alternative question', keep choices in question_text or options; do not create subquestions.",
        "Create subquestions only when explicit labels like (a)/(b)/(i)/(ii) are visible or multiple asks appear under the same number.",
        "Do not create subquestions from section math or marks text.",
        "Interpret section math N x M only as distribution evidence; do not split questions or create subquestions from it.",
        "If section math appears in the left margin (n x m = x), it applies to the next n questions; do not assign marks.",
        "Do not include section math blocks; visual layer detects section math.",
        "Return effective_total_marks only as 0 in stage-1.",
        "Preserve subparts exactly as written.",
        "Keep question_text concise and parseable JSON-safe text (plain ASCII punctuation preferred).",
        "If a question has long dot/blank leaders or repeated punctuation, collapse them to a short placeholder like '...'.",
        "Do not copy very long filler sequences from OCR (e.g., hundreds of dots/underscores).",
        "Return strict JSON only, no markdown.",
        "Do not include raw newlines inside string values; use \\n for line breaks.",
        "Do not include unescaped quotes inside strings; JSON must be valid.",
        "Include image_evidence with page_index and approximate bbox for each question.",
    ]
    rules.extend(extra_rules or [])

    return (
        "You are extracting exam structure for GradeSense.\n"
        f"Batch {batch_index}/{total_batches}.\n"
        "Follow all rules strictly:\n"
        + "\n".join(f"- {r}" for r in rules)
        + "\n\nRequired JSON schema:\n"
        + _json_schema_block(EXTRACTION_SCHEMA)
        + "\n\nOCR Support Text:\n"
        + (raw_ocr_text or "")[:40000]
    )


def build_visual_extraction_prompt(
    *,
    batch_index: int,
    total_batches: int,
    page_offset: int,
) -> str:
    rules = [
        "You are extracting visual structure from images only.",
        "Do not use OCR text; do not transcribe long text.",
        "Return strict JSON only.",
        "Only output structural evidence fields; no question text.",
        "Do not assign final marks; only include visible margin marks and section math expressions.",
        "Do not apply rules or compute totals; return evidence only.",
        "Use page_index as absolute index starting at 0.",
        f"This batch starts at page_index={page_offset}.",
    ]
    return (
        "You are extracting visual evidence for GradeSense.\n"
        f"Batch {batch_index}/{total_batches}.\n"
        "Follow all rules strictly:\n"
        + "\n".join(f"- {r}" for r in rules)
        + "\n\nRequired JSON schema:\n"
        + _json_schema_block(VISUAL_EXTRACTION_SCHEMA)
    )


def build_reconstruction_prompt(
    *,
    previous_structure: Dict[str, Any],
    validation_errors: List[str],
    raw_ocr_text: str,
) -> str:
    return (
        "Reconstruct the same exam structure and fix only validation errors.\n"
        "Hard guardrails:\n"
        "- Do not invent numbering.\n"
        "- Do not merge distinct questions.\n"
        "- This is structural parsing, not summarization.\n"
        "- Stage-1 only: do not assign marks; set all marks to 0.\n"
        "- Never split one question's marks unless explicit visual subparts exist.\n"
        "- Treat N x M as section distribution evidence; do not split questions.\n"
        "- Do not create subquestions from marks math alone.\n"
        "- Do not create subquestions from MCQ options.\n"
        "- If section math appears in the left margin (n x m = x), it applies to the next n questions; do not assign marks.\n"
        "- If the paper says 'any one/any of the following/alternative question', keep choices in question_text or options; do not create subquestions.\n"
        "- Do not output or_group_id; visual layer handles OR pairing.\n"
        "- Do not compute final totals or redistribute marks.\n"
        "- Keep mark hints only when explicitly visible in paper.\n"
        "- Do not include section_math_blocks; visual layer detects section math.\n"
        "- Keep visual evidence for every question.\n"
        "- Keep question_text concise and JSON-safe; collapse long dot leaders/repeated punctuation to '...'.\n"
        "- Do not include raw newlines inside string values; use \\n for line breaks.\n"
        "- Do not include unescaped quotes inside strings.\n"
        "Return strict JSON only.\n\n"
        "Current extracted structure:\n"
        f"{json.dumps(previous_structure, ensure_ascii=True)[:30000]}\n\n"
        "Validation errors to fix:\n"
        + "\n".join(f"- {e}" for e in (validation_errors or ["unknown_error"]))
        + "\n\nSchema:\n"
        + _json_schema_block(EXTRACTION_SCHEMA)
        + "\n\nOCR Support Text:\n"
        + (raw_ocr_text or "")[:40000]
    )


def build_alignment_prompt(*, question_structure: Dict[str, Any]) -> str:
    return (
        "Align student answers to the provided question structure.\n"
        "Use answer images as source of truth.\n"
        "No fuzzy string matching heuristics. Use visual numbering/location cues.\n"
        "Return strict JSON only.\n\n"
        "Question structure:\n"
        f"{json.dumps(question_structure, ensure_ascii=True)[:50000]}\n\n"
        "Required schema:\n"
        + _json_schema_block(ALIGNMENT_SCHEMA)
    )


def build_quality_prompt(
    *,
    question: Dict[str, Any],
    student_answer_text: str,
    model_answer_text: str,
    grading_contract: Dict[str, Any],
) -> str:
    return (
        "You are a grading quality assessor.\n"
        "You are NOT allowed to assign marks.\n"
        "Return only quality signals and statuses.\n"
        "Return strict JSON only.\n\n"
        "If images are provided, use them as source of truth when text is incomplete.\n\n"
        "Leniency rules:\n"
        "- Grade like a school English teacher: focus on meaning, be lenient on phrasing.\n"
        "- If a 1-mark or very short answer is correct in meaning, give full credit even if brief.\n"
        "- Accept concise, paraphrased, or synonym-based answers if meaning matches the model answer.\n"
        "- Do not penalize for lack of elaboration when the question only requires a short response.\n\n"
        "Question:\n"
        f"{json.dumps(question, ensure_ascii=True)}\n\n"
        "Grading contract:\n"
        f"{json.dumps(grading_contract, ensure_ascii=True)}\n\n"
        "Student answer:\n"
        f"{student_answer_text[:15000]}\n\n"
        "Model/reference answer:\n"
        f"{(model_answer_text or '')[:15000]}\n\n"
        "Required schema:\n"
        + _json_schema_block(QUALITY_SCHEMA)
    )


def build_objective_key_prompt(*, question: Dict[str, Any], model_answer_text: str) -> str:
    return (
        "Infer objective key for one question.\n"
        "Do not grade, only infer key and confidence.\n"
        "Return strict JSON only.\n\n"
        "If model answer images are provided, use them when text is incomplete.\n\n"
        "Question:\n"
        f"{json.dumps(question, ensure_ascii=True)}\n\n"
        "Model/reference answer:\n"
        f"{(model_answer_text or '')[:12000]}\n\n"
        "Schema:\n"
        + _json_schema_block(OBJECTIVE_KEY_SCHEMA)
    )


def build_student_option_prompt(*, question: Dict[str, Any]) -> str:
    return (
        "Read the student's selected option for the given MCQ from the provided images.\n"
        "Look for ticks/circles/letters written by the student.\n"
        "Return empty string if not visible.\n"
        "Return strict JSON only.\n\n"
        "Question:\n"
        f"{json.dumps(question, ensure_ascii=True)}\n\n"
        "Schema:\n"
        + _json_schema_block(STUDENT_OPTION_SCHEMA)
    )
