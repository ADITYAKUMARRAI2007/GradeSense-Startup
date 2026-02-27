"""Simplified linear grading pipeline for question-paper + student answer-sheet.

This module provides a minimal path from two PDF uploads to per-question
scores and feedback.  It is intentionally stripped of the college/UPSC
heuristics and confidence gates present elsewhere; everything operates
deterministically and sequentially so that question N on the paper is
matched with the corresponding answer on the sheet and graded in isolation.

The intended use-case is when you just want to upload a paper and a response
and immediately get back marks for each question, without any of the other
"blueprint health", "mapping confidence" or packet-recovery logic.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

# many of the functions used below live in the heavy-weight
# "answer_sheet_pipeline" module which depends on cv2, numpy, etc.
# those libraries may not be installed in lightweight test environments,
# so we import them lazily and provide a simple fallback that operates on
# plain PDF text if the full pipeline isn't available.
try:
    from app.services.answer_sheet_pipeline import (
        pdf_to_clean_images,
        detect_page_layout,
        run_region_ocr,
        build_packets,
        build_question_blueprint_from_pdf,
    )
    _HAS_FULL_ANSWER_PIPE = True
except ImportError:
    # fall back to minimal functionality
    from app.services.answer_sheet_pipeline import build_question_blueprint_from_pdf

    _HAS_FULL_ANSWER_PIPE = False

    # define a very small "packets" builder based on raw PDF text
    import fitz
    import re

    _SIMPLE_Q_ANCHOR = re.compile(r"(?:q\.?\s*)?0*(\d{1,3})(?:[\).:]|\b)", re.IGNORECASE)

    def _text_only_build_packets(pdf_bytes: bytes, blueprint: List[Dict[str, Any]]) -> Dict[int, dict]:
        """Minimal packet builder that ignores layout and just splits by line anchors."""
        out: Dict[int, dict] = {}
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for page in doc:
                text = page.get_text("text") or ""
                for ln in text.splitlines():
                    m = _SIMPLE_Q_ANCHOR.search(ln or "")
                    if m:
                        qn = int(m.group(1))
                        if qn not in out:
                            out[qn] = {"combined_text": ""}
                        current = qn
                    if out and 'current' in locals() and current:
                        out[current]["combined_text"] += ln + "\n"
        except Exception:
            pass
        return out

# helpers for grading


def grade_mcq(answer_text: str, question: Dict[str, Any]) -> Tuple[float, str]:
    """Very basic MCQ grader.

    Looks for a single letter (A/B/C/D) in the student's response and
    compares it to ``question['correct_option']`` (case-insensitive).
    Returns full marks for a match, zero otherwise.  If no anchor letter is
    found the score is zero.
    """
    correct = str(question.get("correct_option", "")).strip().lower()
    ans = ""
    for ch in answer_text.upper():
        if ch in "ABCD":
            ans = ch
            break
    if not ans and answer_text.strip():
        # fall back to first word (users sometimes write "4" or "C")
        ans = answer_text.strip().split()[0]
    score = float(question.get("marks", 0.0) or 0.0)
    if correct and ans.lower() == correct.lower():
        return score, "Correct"
    else:
        return 0.0, f"Incorrect (expected {correct})" if correct else "Unable to evaluate MCQ"


def grade_descriptive(answer_text: str, question: Dict[str, Any]) -> Tuple[float, str]:
    """Simple descriptive grader.

    This stub implementation always awards full marks if any text is present.
    It exists to keep the pipeline self-contained and avoid network calls in
    tests; you can replace it with a real LLM call or more advanced logic.
    """
    if not answer_text or not answer_text.strip():
        return 0.0, "No answer provided"
    return float(question.get("marks", 0.0) or 0.0), "Answer received"


def _merge_question_meta(
    blueprint: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]],
) -> None:
    """Update blueprint entries in-place with values from user-provided meta."""
    if not meta:
        return
    for q in blueprint:
        qid = q.get("question_id")
        if qid is None:
            continue
        extra = meta.get(str(qid)) or meta.get(int(qid))
        if isinstance(extra, dict):
            q.update(extra)


def run_simple_pipeline(
    question_paper_pdf: bytes,
    answer_sheet_pdf: bytes,
    question_meta: Optional[Dict[Any, Any]] = None,
) -> List[Dict[str, Any]]:
    """Execute the full simple pipeline and return per-question results.

    ``question_meta`` is an optional dictionary keyed by question number; the
    values are merged into the extracted blueprint.  This allows callers to
    supply things like ``{'1': {'type': 'mcq', 'correct_option': 'B',
    'marks': 2}}`` if the paper itself lacks that information.
    """

    # 1. extract blueprint from question paper
    blueprint = build_question_blueprint_from_pdf(question_paper_pdf)
    _merge_question_meta(blueprint, question_meta or {})

    # 2. parse answer sheet into packets
    if _HAS_FULL_ANSWER_PIPE:
        clean_imgs = pdf_to_clean_images(answer_sheet_pdf)
        layout = detect_page_layout(clean_imgs)
        regions = run_region_ocr(clean_imgs, layout)
        packets = build_packets(regions, blueprint)
    else:
        # heavy dependencies missing (cv2 etc). use simple text-based
        # extraction so tests and lightweight environments still work.
        packets = _text_only_build_packets(answer_sheet_pdf, blueprint)

    # 3. grade each question independently
    results: List[Dict[str, Any]] = []
    for q in blueprint:
        qnum = int(q.get("question_id") or -1)
        pkt = packets.get(qnum, {})
        answer_text = str(pkt.get("combined_text", "") or "").strip()
        qtype = str(q.get("type", "descriptive") or "").lower()

        if qtype == "mcq":
            score, feedback = grade_mcq(answer_text, q)
        else:
            score, feedback = grade_descriptive(answer_text, q)

        results.append(
            {
                "question_number": qnum,
                "answer_text": answer_text,
                "question_text": q.get("rubric") or q.get("question_text"),
                "max_marks": float(q.get("marks", 0.0) or 0.0),
                "score": score,
                "feedback": feedback,
            }
        )

    return results


__all__ = [
    "run_simple_pipeline",
    "grade_mcq",
    "grade_descriptive",
]
