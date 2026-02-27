"""
Grading service - AI-powered answer paper evaluation.
Migrated from server.py grade_with_ai and related functions (lines ~5297-6828, 9157-9205).
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import asyncio
import base64
import io
import json
import math
import re
import hashlib
import uuid
import os

from fastapi import HTTPException
from pymongo import ReturnDocument
from PIL import Image

from app.database import db
from app.config import (
    COLLEGE_V2_HARD_STOP,
    COLLEGE_V2_PIPELINE_ENABLED,
    AWS_PIPELINE_ENABLED,
    AWS_PIPELINE_EXAM_TYPES,
    UNIVERSAL_HARD_STOP,
    UNIVERSAL_PIPELINE_ENABLED,
    UNIVERSAL_PIPELINE_EXAM_TYPES,
    get_llm_api_key,
    logger,
)
from app.layers.resolver import resolve_grading_layer
from app.layers.upsc.policy import enforce_upsc_strict_caps
from app.models.submission import QuestionScore, SubQuestionScore, AnnotationData
from app.services.gridfs_helpers import (
    get_exam_question_paper_pdf_bytes,
    get_exam_model_answer_images,
    get_exam_question_paper_images,
)
from app.services.file_processing import correct_all_images_rotation
from app.services.llm import LlmChat, UserMessage, ImageContent
from app.services.blueprint_enrichment import (
    apply_grading_contract,
    build_blueprint_enrichment,
    extract_quality_score,
)
from app.services.score_normalization import normalize_submission_scores
from app.utils.annotation_utils import Annotation, AnnotationType
from app.utils.ocr_provider import get_ocr_provider

# In-memory grading cache
grading_cache = {}
grading_cache_meta = {}

# Feature flag: allow turning off annotated image generation (requested)
DISABLE_ANNOTATIONS = os.getenv("DISABLE_ANNOTATIONS", "true").lower() in ("1", "true", "yes", "on")
MODEL_ANSWER_OPTIONAL = os.getenv("MODEL_ANSWER_OPTIONAL", "true").lower() in ("1", "true", "yes", "on")
DISABLE_GRADING_CACHE = os.getenv("DISABLE_GRADING_CACHE", "false").lower() in ("1", "true", "yes", "on")
GRADING_CACHE_VERSION = os.getenv("GRADING_CACHE_VERSION", "packet-v5").strip() or "packet-v5"
QUESTION_EXTRACTION_WAIT_SECONDS = int(os.getenv("QUESTION_EXTRACTION_WAIT_SECONDS", "120"))
MAPPING_HARD_STOP = os.getenv("MAPPING_HARD_STOP", "true").lower() in ("1", "true", "yes", "on")
MAPPED_QUESTION_RATIO_MIN = float(os.getenv("MAPPED_QUESTION_RATIO_MIN", "0.85"))
MAPPING_COVERAGE_GATE_MIN = float(os.getenv("MAPPING_COVERAGE_GATE_MIN", "0.75"))
UNRESOLVED_RATIO_MAX = float(os.getenv("UNRESOLVED_RATIO_MAX", "0.10"))
COLLEGE_V2_PARTIAL_GRADING_ENABLED = os.getenv("COLLEGE_V2_PARTIAL_GRADING_ENABLED", "true").lower() in ("1", "true", "yes", "on")
COLLEGE_V2_PARTIAL_MIN_MAPPED = int(os.getenv("COLLEGE_V2_PARTIAL_MIN_MAPPED", "1"))
COLLEGE_V2_PARTIAL_MIN_COVERAGE = float(os.getenv("COLLEGE_V2_PARTIAL_MIN_COVERAGE", "0.85"))


def _allow_college_v2_partial_grading(
    *,
    college_v2_active: bool,
    mapped_questions_count: int,
    mapping_coverage: float,
) -> bool:
    """Allow partial grading for college V2 when mapping is usable but incomplete."""
    if not college_v2_active:
        return False
    if not COLLEGE_V2_PARTIAL_GRADING_ENABLED:
        return False
    if int(mapped_questions_count or 0) < int(max(1, COLLEGE_V2_PARTIAL_MIN_MAPPED)):
        return False
    if float(mapping_coverage or 0.0) < float(COLLEGE_V2_PARTIAL_MIN_COVERAGE):
        return False
    return True


# ============== TEACHER LEARNING PATTERNS ==============

async def fetch_teacher_learning_patterns(teacher_id: str, subject_id: str, exam_id: str = None):
    """
    Fetch past teacher corrections to apply as learned patterns.
    Returns list of relevant corrections for this teacher + subject.
    """
    try:
        query = {
            "teacher_id": teacher_id,
            "subject_id": subject_id,
            "$or": [
                {"apply_to_all": True},
                {"exam_id": exam_id} if exam_id else {}
            ]
        }
        
        corrections = await db.grading_feedback.find(
            query,
            {"_id": 0, "question_number": 1, "question_topic": 1, "teacher_correction": 1, 
             "teacher_expected_grade": 1, "ai_grade": 1, "created_at": 1, "exam_id": 1}
        ).sort("created_at", -1).limit(100).to_list(100)
        
        logger.info(f"Found {len(corrections)} learned patterns for teacher {teacher_id}, subject {subject_id}")
        return corrections
    except Exception as e:
        logger.error(f"Error fetching learning patterns: {e}")
        return []


# ============== TEACHER EDIT TRACKING ==============

async def track_teacher_edits(submission_id: str, question_number: int, 
                               original_marks: float, new_marks: float,
                               original_feedback: str, new_feedback: str,
                               teacher_id: str, exam_id: str):
    """Track teacher edits for learning patterns."""
    try:
        edit_distance = calculate_edit_distance(original_feedback, new_feedback)
        
        await db.teacher_edits.insert_one({
            "edit_id": f"edit_{uuid.uuid4().hex[:12]}",
            "submission_id": submission_id,
            "question_number": question_number,
            "original_marks": original_marks,
            "new_marks": new_marks,
            "marks_delta": new_marks - original_marks,
            "original_feedback": original_feedback,
            "new_feedback": new_feedback,
            "edit_distance": edit_distance,
            "teacher_id": teacher_id,
            "exam_id": exam_id,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"Tracked teacher edit for submission {submission_id} Q{question_number}")
    except Exception as e:
        logger.error(f"Error tracking teacher edit: {e}")


def calculate_edit_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings."""
    if not s1:
        return len(s2) if s2 else 0
    if not s2:
        return len(s1)
    
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i-1] == s2[j-1]:
                dp[i][j] = dp[i-1][j-1]
            else:
                dp[i][j] = 1 + min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1])
    
    return dp[m][n]


def calculate_grading_cost(num_images: int, num_questions: int) -> float:
    """Estimate grading cost based on images and questions."""
    # Rough estimate: ~$0.01 per image processed
    base_cost = num_images * 0.01
    question_cost = num_questions * 0.002
    return round(base_cost + question_cost, 4)


async def log_grading_analytics(exam_id: str, submission_id: str, 
                                 grading_time_ms: int, num_questions: int,
                                 total_marks: float, obtained_marks: float,
                                 grading_mode: str, teacher_id: str = None):
    """Log grading analytics for insights."""
    try:
        await db.grading_analytics.insert_one({
            "analytics_id": f"ga_{uuid.uuid4().hex[:12]}",
            "exam_id": exam_id,
            "submission_id": submission_id,
            "grading_time_ms": grading_time_ms,
            "num_questions": num_questions,
            "total_marks": total_marks,
            "obtained_marks": obtained_marks,
            "percentage": round((obtained_marks / total_marks * 100) if total_marks > 0 else 0, 2),
            "grading_mode": grading_mode,
            "teacher_id": teacher_id,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        logger.error(f"Error logging grading analytics: {e}")


# ============== MAIN GRADING FUNCTION ==============

async def grade_with_ai(
    images: List[str],
    model_answer_images: List[str],
    questions: List[dict],
    grading_mode: str,
    total_marks: float,
    model_answer_text: str = "",
    model_answer_map: Optional[Dict[str, Any]] = None,
    teacher_id: str = None,
    subject_id: str = None,
    exam_id: str = None,
    subject_name: str = None,
    exam_name: str = None,
    exam_type: str = None,
    skip_cache: bool = False
) -> List[QuestionScore]:
    """Grade answer paper using Gemini with GradeSense Master Instruction Set + Teacher's Learned Patterns."""
    grade_with_ai.last_packet_meta = {}
    grade_with_ai.last_grading_reference_mode = "rubric_only"
    grade_with_ai.last_college_pipeline = {}
    grade_with_ai.last_answer_segments = {}
    grade_with_ai.last_blueprint_enrichment = {}

    # AI-structured deterministic cutover path.
    from app.layers.ai_structured.engine import grade_images_with_locked_blueprint

    api_key = get_llm_api_key()
    
    if not api_key:
        raise HTTPException(status_code=500, detail="AI service not configured (Missing API Key)")

    # Use latest exam blueprint when available. Public route contracts remain unchanged.
    try:
        exam_doc = None
        if exam_id:
            exam_doc = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        if not exam_doc:
            exam_doc = {
                "exam_id": exam_id,
                "questions": questions or [],
                "total_marks": total_marks,
                "blueprint_status": "ready_locked",
                "blueprint_locked": True,
                "blueprint_version": 0,
            }
        model_answer_images = []
        question_paper_images = []
        if exam_id:
            try:
                model_answer_images = await get_exam_model_answer_images(exam_id)
                question_paper_images = await get_exam_question_paper_images(exam_id)
            except Exception as exc:
                logger.warning("MODEL_QP_IMAGE_FETCH_FAILED exam_id=%s error=%s", exam_id, exc)
        scores, packet_meta = await grade_images_with_locked_blueprint(
            exam=exam_doc,
            images=images,
            model_answer_text=model_answer_text or "",
            model_answer_map=model_answer_map or {},
            model_answer_images=model_answer_images,
            question_paper_images=question_paper_images,
            grading_mode=grading_mode or "balanced",
            exam_id=exam_id,
        )
        grade_with_ai.last_packet_meta = packet_meta
        grade_with_ai.last_grading_reference_mode = "rubric_only"
        grade_with_ai.last_blueprint_enrichment = {}
        return scores
    except Exception as exc:
        logger.error("AI-structured grading failed exam_id=%s error=%s", exam_id, exc, exc_info=True)
        raise HTTPException(status_code=400, detail=f"Deterministic grading blocked: {exc}")
    
    # Apply rotation correction to student images
    logger.info("Applying rotation correction to student images...")
    corrected_images = await asyncio.to_thread(correct_all_images_rotation, images)
    
    # Fetch teacher's learned patterns
    learned_patterns = []
    if teacher_id and subject_id:
        learned_patterns = await fetch_teacher_learning_patterns(teacher_id, subject_id, exam_id)
        if learned_patterns:
            logger.info(f"🧠 Applying {len(learned_patterns)} learned patterns from teacher's past corrections")
    
    # Determine grading mode
    grading_mode = (grading_mode or "balanced").strip().lower()
    use_text_based_grading = bool(model_answer_text and len(model_answer_text) > 100)
    has_model_reference = use_text_based_grading or bool(model_answer_images)
    grading_reference_mode = "rubric_plus_model" if has_model_reference else "rubric_only"
    grade_with_ai.last_grading_reference_mode = grading_reference_mode

    if not MODEL_ANSWER_OPTIONAL and not has_model_reference:
        raise HTTPException(status_code=400, detail="Model answer is required for grading by current configuration")

    # Guardrail: strict grading without model reference is overly punitive and unstable.
    if grading_mode == "strict" and not has_model_reference:
        logger.warning(
            "Strict grading requested without model answer (exam_id=%s). Falling back to balanced mode.",
            exam_id or "unknown",
        )
        grading_mode = "balanced"
    
    print(f"\n{'='*70}")
    print(f"[GRADING-START]")
    print(f"  Images: {len(images)} student pages")
    print(f"  Model answer: {len(model_answer_images)} images, {len(model_answer_text)} text chars")
    print(f"  Questions: {len(questions)}")
    print(f"  Use text-based: {use_text_based_grading}")
    print(f"  Effective mode: {grading_mode}")
    print(f"{'='*70}\n")
    
    if use_text_based_grading:
        logger.info(f"Using TEXT-BASED grading (model answer: {len(model_answer_text)} chars)")
        print(f"[GRADING] TEXT-BASED mode - Model answer preview: {model_answer_text[:200]}...")
    else:
        logger.info(f"Using IMAGE-BASED grading (model answer: {len(model_answer_images)} images)")
        print(f"[GRADING] IMAGE-BASED mode - {len(model_answer_images)} model images + {len(images)} student images")
    
    effective_skip_cache = bool(skip_cache or DISABLE_GRADING_CACHE)

    # Create content hash for deterministic grading.
    # Include a pipeline version salt so stale DB cache from older mapping logic
    # cannot be reused after major grading pipeline changes.
    hash_content = (
        f"{GRADING_CACHE_VERSION}|".encode()
        + "".join(corrected_images).encode()
        + str(questions).encode()
        + grading_mode.encode()
    )
    if use_text_based_grading:
        hash_content += model_answer_text.encode()
    else:
        hash_content += "".join(model_answer_images).encode()
    paper_hash = hashlib.sha256(hash_content).hexdigest()
    content_hash = paper_hash[:16]

    # Check cache (Memory)
    if not effective_skip_cache and paper_hash in grading_cache:
        logger.info(f"Cache hit (memory) for paper {paper_hash}")
        cached_meta = grading_cache_meta.get(paper_hash, {}) or {}
        grade_with_ai.last_packet_meta = cached_meta
        grade_with_ai.last_grading_reference_mode = cached_meta.get("grading_reference_mode", grading_reference_mode)
        grade_with_ai.last_answer_segments = {}
        return grading_cache[paper_hash]

    # Check cache (Database)
    if not effective_skip_cache:
        try:
            cached_result = await db.grading_results.find_one({"paper_hash": paper_hash})
            if cached_result and "results" in cached_result:
                logger.info(f"Cache hit (db) for paper {paper_hash}")
                results_data = json.loads(cached_result["results"])
                cached_meta = cached_result.get("mapping_meta", {}) or {}
                grade_with_ai.last_packet_meta = cached_meta
                grade_with_ai.last_grading_reference_mode = cached_meta.get("grading_reference_mode", grading_reference_mode)
                grading_cache_meta[paper_hash] = cached_meta
                grade_with_ai.last_answer_segments = {}
                return [QuestionScore(**s) for s in results_data]
        except Exception as e:
            logger.error(f"Error checking grading cache: {e}")
    
    # ============== GRADING MODE SPECIFICATIONS ==============
    mode_instructions = {
        "strict": """🔴 STRICT MODE - UPSC-LEVEL EVALUATION. Zero tolerance for errors. Complete perfection required.

**CRITICAL GRADING PHILOSOPHY: STRICT = UPSC/CIVIL SERVICES STANDARD**
This mode emulates UPSC Main Examination evaluation standards where:
- Only perfect, complete, accurate answers receive full marks
- Any deviation, error, or incompleteness results in zero marks
- No sympathy marks. No benefit of doubt. No partial credit for effort.
- The evaluator is looking for EXCELLENCE, not just understanding.

**ABSOLUTE GRADING RULE: ALL OR NOTHING**
- Everything correct (method + calculation + presentation + answer) = FULL MARKS ✅
- Anything wrong/missing/incomplete = 0 MARKS ❌
- No partial credit. No carry-forward. No consolation marks.

**STRICT UPSC CAP (CRITICAL)**
- Maximum awardable marks for ANY question is (0.5 × max_marks − 1).
- Award this maximum ONLY for a flawless, complete answer. If anything is missing or weak, go lower.

**MATHEMATICAL/NUMERICAL PROBLEMS (UPSC STANDARD)**:
1. **Formula/Method Correctness** - MANDATORY but NOT SUFFICIENT for marks
2. **Calculation Precision** - ZERO TOLERANCE
3. **Final Answer Requirements**: Numerically accurate, proper units, properly formatted
4. **Multi-Step Problems** - CHAIN OF PERFECTION: One error anywhere = 0 marks

**THEORETICAL/DESCRIPTIVE ANSWERS (UPSC STANDARD)**:
1. ALL key points from model answer must be present
2. Keywords MUST appear
3. Introduction-Body-Conclusion structure required
4. Relevant examples MUST be provided

**SUB-QUESTIONS (INDEPENDENT ALL-OR-NOTHING PER PART)**:
- Each sub-part evaluated INDEPENDENTLY
- Part perfect = Full marks | Part imperfect = 0

**BLANK/NO ATTEMPT**:
- Question not attempted = -1.0 marks (NOT FOUND marker)
- Blank space = 0 marks

**ABSOLUTE RULE FOR STRICT MODE**:
"PERFECT = Full Marks | IMPERFECT (even slightly) = 0 Marks\"""",

        "balanced": """⚖️ BALANCED MODE (DEFAULT) - Fair and reasonable evaluation.

DUAL ASSESSMENT:
- Evaluate both PROCESS and OUTCOME
- Approximate weight: 60% process, 40% outcome

STANDARD PARTIAL MARKING:
- Correct method, wrong answer: 30-45% marks
- Wrong method, correct answer: 15-30% marks
- Partially correct: Proportional to correctness
- Missing minor elements: Minor deductions
- Missing major elements: Significant deductions

PRACTICAL TOLERANCE:
- Minor calculation errors: Small penalty if method is correct
- Unit errors: Small penalty (typically 0.5-1 mark)
- Minor spelling errors in non-technical terms: Ignore""",

        "conceptual": """🔵 CONCEPTUAL MODE - Understanding over procedure.

UNDERSTANDING VERIFICATION:
- Focus on whether the student understands the core concept
- Can the student explain WHY, not just WHAT

METHOD FLEXIBILITY:
- Accept alternative valid methods
- Steps can be skipped IF logic is evident

KEYWORD FLEXIBILITY:
- Accept synonyms for technical terms
- Understanding demonstrated through explanation = keyword credit

PARTIAL MARKING:
- Award marks for demonstrated understanding even if execution is flawed
- Minimum threshold for any marks = 50% correctness of concept""",

        "lenient": """🟢 LENIENT MODE - Encourage and reward effort.

ATTEMPT RECOGNITION:
- Any genuine attempt at answering earns consideration
- Starting the problem correctly = minimum marks

FLOOR MARKS SYSTEM:
- Writing relevant formula = 10-20% of question marks
- Floor = MAX(attempt_value, 10% of question marks)

GENEROUS PARTIAL MARKING:
- Each correct element independently credited
- Minimum threshold for any marks = 25% correctness

ERROR TOLERANCE:
- Calculation errors: Still credit the method
- Missing units: Minor penalty
- Give benefit of doubt on ambiguous answers"""
    }
    
    grading_instruction = mode_instructions.get(grading_mode, mode_instructions["balanced"])

    
    layer_context = resolve_grading_layer(
        exam_type=exam_type,
        exam_name=exam_name,
        subject_name=subject_name,
    )
    is_upsc = layer_context.is_upsc
    is_universal = layer_context.layer == "universal"
    exam_type_norm = str(exam_type or "").strip().lower()
    universal_v2_active = bool(
        False
    )
    aws_pipeline_active = bool(
        exam_type_norm != "upsc"
    )
    college_v2_active = bool(
        COLLEGE_V2_PIPELINE_ENABLED
        and exam_type_norm != "upsc"
        and not universal_v2_active
        and not aws_pipeline_active
    )
    upsc_paper = layer_context.upsc_paper
    base_prompt = layer_context.base_prompt

    exam_blueprint_failed_chunks: List[Dict[str, Any]] = []
    if exam_id and (college_v2_active or universal_v2_active):
        try:
            exam_doc = await db.exams.find_one(
                {"exam_id": exam_id},
                {"_id": 0, "blueprint_health.failed_chunks": 1},
            )
            exam_blueprint_failed_chunks = (
                ((exam_doc or {}).get("blueprint_health", {}) or {}).get("failed_chunks", [])
                or []
            )
        except Exception as exc:
            logger.warning("Could not fetch blueprint failed-chunk diagnostics for exam %s: %s", exam_id, exc)

    # Default grading_mode based on exam_type when not explicitly set
    grading_mode = grading_mode or layer_context.default_grading_mode

    master_system_prompt = f"""{base_prompt}

UPSC PAPER DETECTED: {upsc_paper or "Unknown"}

# GRADESENSE AI GRADING ENGINE - MASTER SYSTEM

You are the GradeSense Grading Engine - an advanced AI system designed to evaluate handwritten student answer papers.

## FUNDAMENTAL PRINCIPLES
### 1. CONSISTENCY IS SACRED
- Same paper graded twice = identical marks (100% reproducibility)
- Identical answers = identical marks

### 2. THE MODEL ANSWER IS YOUR HOLY GRAIL
- Model answer is the definitive reference
- Never contradict what the model answer establishes

### 3. FAIRNESS ABOVE ALL
- Grade the CONTENT, not the handwriting aesthetics
- Apply the same standards consistently

## CURRENT GRADING MODE: {grading_mode.upper()}

{grading_instruction}

## ANSWER TYPE HANDLING

### 📐 MATHEMATICAL PROBLEMS
- **STRICT MODE**: Correct method + Correct calculation + Correct answer = FULL marks, Anything wrong = 0
- **Other modes**: Correct method + Wrong calculation = Partial marks (20-60%)
- Units MUST be present in final answers
- Alternative valid methods = full marks ONLY if both method AND calculation are correct

### 📝 SHORT / LONG ANSWERS
- Key-point coverage; each key point = proportional marks
- Extra correct info does not compensate missing key points

### ✅ MCQ / OBJECTIVE
- Single correct = full marks, wrong = 0

## HANDWRITING INTERPRETATION
- Use question context and subject vocabulary
- If ambiguous, choose most likely correct interpretation
- Honor final visible answer (ignore crossed-out content)

## EDGE CASE HANDLING
- BLANK ANSWERS: 0 marks, status "not_attempted"
- IRRELEVANT CONTENT: 0 marks, status "graded"
- **QUESTION NOT FOUND**: Use quality_score = -1.0

## OUTPUT FORMAT (STRICT)
Return ONLY valid JSON:
{{
  "scores": [
    {{
      "question_number": 1,
      "quality_score": 0.82,
      "ai_feedback": "Specific, constructive feedback (20-150 words)",
      "status": "graded|not_attempted|not_found",
      "confidence": 0.0,
      "annotations": [
        {{
          "page_number": 1,
          "segment_id_start": "P2-S3",
          "segment_id_end": "P2-S4",
          "annotation_type": "TICK|CROSS|UNDERLINE|COMMENT|BOX",
          "short_label": "2-4 word abbreviation (REQUIRED). Use terse examiner shorthand: 'Good pt', 'Correct defn', 'Wrong date', 'Vague', 'Incomplete', 'Key term missing', 'Nice eg', 'Irrelevant'",
          "sentiment": "positive|negative",
          "color": "green (for correct/positive BOX) or red (for errors/negative BOX)"
        }}
      ],
      "sub_scores": [
        {{
          "sub_id": "a",
          "quality_score": 0.75,
          "status": "graded|not_attempted|not_found",
          "ai_feedback": "Feedback for part a",
          "annotations": []
        }}
      ]
    }}
  ],
  "grading_notes": "Overall observations"
}}

### CRITICAL FIELD RULES
1. You are NOT allowed to assign marks (no obtained_marks, no max_marks in output).
2. quality_score = -1.0 means question/subpart not found.
3. quality_score in [0.0, 1.0] for graded answers.
4. sub_scores required for sub-questions.
5. ai_feedback must be improvement-focused and actionable.
6. confidence must be between 0.0 and 1.0.
7. **SKIP INTRO/RUBRIC/HEADER PAGES** — Pages at the START showing: exam headers, rubric tables, evaluation parameters, instructions, blank pages = DO NOT ANNOTATE AT ALL. Only annotate pages containing actual handwritten ANSWERS to questions.
8. **PROVIDE 7-15 ANNOTATIONS PER ANSWER PAGE** — Only for pages with actual answer content. Spread marks across entire page (top, middle, bottom), not clustered.
9. **IGNORE PRINTED QUESTIONS** - Only annotate handwritten answers
10. **USE BOXES + MIXED FEEDBACK** — Boxes are primary. Generate BALANCED feedback: praise good points (GREEN BOXES) AND point out improvement areas (RED BOXES). Do NOT make feedback one-sided. Mix 50-60% positive, 40-50% constructive criticism. Every answer needs BOTH types of feedback. Feedback MUST be UPSC-exam-level detailed (not generic).
11. Use segment_id_start/segment_id_end from STRUCTURED ANSWER SEGMENTS. If single segment, set both to same value.
12. **UPSC-LEVEL MIXED FEEDBACK (REQUIRED for EVERY annotation)** — Use detailed, specific feedback explaining WHY. Generate BALANCED annotations: roughly 50-60% strengths (GREEN), 40-50% improvement areas (RED). Examples:
    - ✅ GREEN feedback (strengths): 'Correct mechanism', 'Well-explained with act reference', 'Good constitutional basis', 'Relevant historical example', 'Proper case law cited', 'Accurate data point', 'Strong substantiation'
    - ❌ RED feedback (improvements): 'Factual error - Act does not provide this', 'Incomplete list of artifacts', 'Missed constitutional provision', 'Vague on mechanism', 'Missing critical example', 'Needs more substantiation', 'Should mention schedule/article', 'Lacks contextual clarity'
    - CRITICAL: In EVERY answer, provide BOTH praise AND constructive criticism. Do NOT make feedback one-sided.
13. **NO DUPLICATE ANNOTATIONS** — if the same reason applies to multiple adjacent segments, create ONE annotation with segment_id_start and segment_id_end range.
14. **COLOR STRICT RULE**: Use color="green" ONLY for correct/positive content. Use color="red" ONLY when there IS an actual error/mistake that needs correction.
15. **MULTI-PAGE ANSWER COVERAGE**: When answer spans multiple answer pages, you MUST annotate EVERY answer page. Do NOT cluster all annotations on first page only.
16. **NO ANNOTATIONS ON INTRO PAGES**: Pages showing exam headers, registration tables, rubric tables, marking schemes, instructions, blank separator pages = ZERO ANNOTATIONS. These remain completely unmodified.

## QUALITY ASSURANCE CHECKLIST
- ARITHMETIC CHECK: no question exceeds max marks
- CONSISTENCY CHECK: similar answers get similar marks
- COMPLETENESS CHECK: every question evaluated
"""


    # Normalize AI annotations helper
    def normalize_ai_annotations(raw_annotations: List[dict]) -> List[AnnotationData]:
        normalized: List[AnnotationData] = []

        def _skip_anchor(anchor: str, ann_type: str) -> bool:
            if not anchor:
                return True
            cleaned = str(anchor).strip().lower()
            if len(cleaned) < 3:
                return True
            if re.fullmatch(r"\d+[\.)]?$", cleaned):
                return True
            return False

        for ann in raw_annotations or []:
            if not isinstance(ann, dict):
                continue
            line_id = ann.get("line_id")
            line_id_start = ann.get("line_id_start") or ann.get("line_start")
            line_id_end = ann.get("line_id_end") or ann.get("line_end")
            segment_id = ann.get("segment_id")
            segment_id_start = ann.get("segment_id_start") or ann.get("segment_start")
            segment_id_end = ann.get("segment_id_end") or ann.get("segment_end")
            has_span_ref = bool(line_id or line_id_start or line_id_end or segment_id or segment_id_start or segment_id_end)
            if "style" in ann and "annotation_type" not in ann:
                style = str(ann.get("style", "")).upper()
                label = str(ann.get("short_label") or ann.get("label") or "")
                
                if style == "GROUP_BRACKET":
                    page_number = ann.get("page_number")
                    page_index = max(0, int(page_number) - 1) if page_number else ann.get("page_index", -1)
                    if page_index is None or page_index < 0:
                        continue
                    normalized.append(AnnotationData(
                        type="GROUP_BRACKET", text=label, label=label,
                        feedback=str(ann.get("feedback") or "").strip() or None,
                        color=ann.get("color", "#D32F2F"), page_index=page_index,
                        y_start=float(ann.get("y_start", 0.3)), y_end=float(ann.get("y_end", 0.45))
                    ))
                    continue
                
                if style == "MARGIN_LEASH":
                    anchor_text = ann.get("anchor") or ann.get("anchor_text") or ""
                    if _skip_anchor(anchor_text, style):
                        continue
                    page_number = ann.get("page_number")
                    page_index = max(0, int(page_number) - 1) if page_number else ann.get("page_index", -1)
                    if page_index is None or page_index < 0:
                        continue
                    normalized.append(AnnotationData(
                        type="MARGIN_LEASH", text=label, label=label,
                        feedback=str(ann.get("feedback") or "").strip() or None,
                        color=ann.get("color", "#D32F2F"), page_index=page_index,
                        anchor_text=anchor_text, anchor_x=0.5, anchor_y=0.5,
                        margin_x=0.92, margin_y=0.5
                    ))
                    continue

                if style == "MARGIN_NOTE":
                    anchor_text = ann.get("anchor") or ann.get("anchor_text") or ""
                    if _skip_anchor(anchor_text, style):
                        continue
                    page_number = ann.get("page_number")
                    page_index = max(0, int(page_number) - 1) if page_number else ann.get("page_index", -1)
                    if page_index is None or page_index < 0:
                        continue
                    normalized.append(AnnotationData(
                        type="MARGIN_NOTE", text=label, label=label,
                        feedback=str(ann.get("feedback") or "").strip() or None,
                        color=ann.get("color", "#D32F2F"), page_index=page_index,
                        anchor_text=anchor_text
                    ))
                    continue

                # Map style to type
                anchor_text = ann.get("anchor") or ann.get("anchor_text") or label
                if has_span_ref:
                    anchor_text = None
                elif _skip_anchor(anchor_text, style):
                    continue

                if style == "EMPHASIS_UNDERLINE":
                    mapped_type = "EMPHASIS_UNDERLINE"
                elif style == "DOUBLE_TICK":
                    mapped_type = "DOUBLE_TICK"
                elif style in ("FEEDBACK_UNDERLINE", "FEEDBACK"):
                    mapped_type = "FEEDBACK_UNDERLINE"
                elif style == "TICK":
                    mapped_type = "TICK"
                elif style == "CROSS":
                    mapped_type = "CROSS"
                elif style == "BOX_COMMENT":
                    mapped_type = "BOX_COMMENT"
                elif style == "INLINE_TICK":
                    mapped_type = AnnotationType.CHECKMARK
                elif style == "INLINE_SYMBOL":
                    symbol = label.strip().upper()
                    mapped_type = AnnotationType.CHECKMARK if symbol == "TICK" else AnnotationType.CROSS_MARK
                elif style == "STRUCTURAL_BOX":
                    mapped_type = AnnotationType.HIGHLIGHT_BOX
                else:
                    mapped_type = AnnotationType.COMMENT

                page_number = ann.get("page_number")
                page_index = max(0, int(page_number) - 1) if page_number else ann.get("page_index", -1)
                if page_index is None or page_index < 0:
                    continue

                print(f"[ANNOTATION-EXTRACT] Type={mapped_type}, Line_ID={line_id}, Start={line_id_start}, End={line_id_end}, Anchor={anchor_text}")
                normalized.append(AnnotationData(
                    type=mapped_type, x=0, y=0, text=label, label=label,
                    feedback=str(ann.get("feedback") or "").strip() or None,
                    color=ann.get("color", "red"), size=26, page_index=page_index,
                    anchor_text=anchor_text, line_id=line_id,
                    line_id_start=line_id_start, line_id_end=line_id_end,
                    segment_id=segment_id, segment_id_start=segment_id_start, segment_id_end=segment_id_end
                ))
            elif "annotation_type" in ann:
                ann_type = str(ann.get("annotation_type", "")).upper()
                type_map = {
                    "TICK": "TICK",
                    "UNDERLINE": AnnotationType.ERROR_UNDERLINE,
                    "CROSS": "CROSS",
                    "BOX": AnnotationType.HIGHLIGHT_BOX,
                    "COMMENT": AnnotationType.COMMENT,
                    "FEEDBACK_UNDERLINE": "FEEDBACK_UNDERLINE",
                    "FEEDBACK": "FEEDBACK_UNDERLINE",
                    "BOX_COMMENT": "BOX_COMMENT"
                }
                mapped_type = type_map.get(ann_type, ann.get("type", AnnotationType.CHECKMARK))
                sentiment = str(ann.get("sentiment", "")).lower()
                if ann_type == "UNDERLINE":
                    color = ann.get("color", "red")
                else:
                    color = "green" if sentiment == "positive" else "red" if sentiment == "negative" else ann.get("color", "red")
                label = ann.get("short_label") or ann.get("reason") or ann.get("anchor_text") or ""
                page_number = ann.get("page_number")
                page_index = max(0, int(page_number) - 1) if page_number else ann.get("page_index", -1)
                if page_index is None or page_index < 0:
                    continue
                anchor_text = ann.get("anchor_text") or ann.get("short_label") or ann.get("reason") or label
                if has_span_ref:
                    anchor_text = None
                elif _skip_anchor(anchor_text, mapped_type):
                    continue
                normalized.append(AnnotationData(
                    type=mapped_type, x=0, y=0, text=str(label), color=color,
                    size=26, page_index=page_index, anchor_text=anchor_text,
                    line_id=line_id, line_id_start=line_id_start,
                    line_id_end=line_id_end,
                    segment_id=segment_id, segment_id_start=segment_id_start, segment_id_end=segment_id_end
                ))
            else:
                try:
                    normalized.append(AnnotationData(**ann))
                except Exception:
                    continue

        if not normalized:
            return normalized

        priority = {
            AnnotationType.CROSS_MARK: 0,
            AnnotationType.HIGHLIGHT_BOX: 1,
            AnnotationType.COMMENT: 1,
            AnnotationType.ERROR_UNDERLINE: 2,
            AnnotationType.CHECKMARK: 3
        }
        normalized.sort(key=lambda a: priority.get(a.type, 99))

        total_limit = 10
        type_limits = {
            AnnotationType.ERROR_UNDERLINE: 4,
            AnnotationType.HIGHLIGHT_BOX: 2,
            AnnotationType.COMMENT: 3,
            AnnotationType.CROSS_MARK: 3,
            AnnotationType.CHECKMARK: 3
        }
        counts: Dict[str, int] = {}
        limited: List[AnnotationData] = []
        for ann in normalized:
            ann_type = ann.type
            if ann_type in type_limits:
                if counts.get(ann_type, 0) >= type_limits[ann_type]:
                    continue
            if len(limited) >= total_limit:
                break
            counts[ann_type] = counts.get(ann_type, 0) + 1
            limited.append(ann)

        return limited


    # Prepare question details
    questions_text = ""
    for q in questions:
        q_text = f"Q{q['question_number']}: Max marks = {q['max_marks']}"
        if q.get('rubric'):
            q_text += f", Rubric: {q['rubric']}"
        if q.get('sub_questions'):
            for sq in q['sub_questions']:
                q_text += f"\n  - Part {sq['sub_id']}: Max marks = {sq['max_marks']}"
                if sq.get('rubric'):
                    q_text += f", Rubric: {sq['rubric']}"
        questions_text += q_text + "\n"

    def build_line_id_context(
        chunk_imgs: List[str],
        start_page_num: int,
        questions: List[dict],
        left_strip_ratio: float = 0.32,
        right_strip_ratio: float = 0.18,
        min_confidence: float = 0.50,
    ) -> str:
        """Build OCR line IDs per question for the current chunk using hybrid OCR."""
        ocr_provider = get_ocr_provider()

        question_numbers = sorted({
            int(q.get("question_number"))
            for q in questions
            if q.get("question_number") is not None and str(q.get("question_number")).isdigit()
        })
        q_num_set = set(question_numbers)

        def _extract_question_number_from_line(
            left_text: str,
            right_text: str,
            page_num: int,
        ) -> Optional[int]:
            """
            Parse question number from margin label text.
            """
            candidate_text = " ".join(filter(None, [left_text, right_text])).strip()
            if not candidate_text:
                return None
            t = re.sub(r"\s+", " ", candidate_text).strip()
            if not t:
                return None

            # Ignore pure page-number/header noise.
            t_lower = t.lower()
            if t.isdigit() and len(t) <= 2 and int(t) == page_num:
                return None
            if "space for writing" in t_lower or "question number" in t_lower:
                return None

            # Filter out clearly non-label lines
            if len(t) > 32:
                return None
            if "," in t or "₹" in t or "$" in t or "." in t:
                return None
            if len(re.findall(r"\d", t)) >= 4:
                return None

            # 1) Strong explicit markers at start: Q12, Q.12, Question 12
            explicit = re.match(r"^\s*(?:q(?:uestion)?\.?\s*)0*(\d{1,3})\b", t, re.IGNORECASE)
            if explicit:
                n = int(explicit.group(1))
                return n if n in q_num_set else None

            # 2) Numeric label at start: 24], (24), 24:, 024]
            lead = re.match(r"^\s*[\(\[]?\s*0*([0-9]{1,3})\s*[\)\]\.:-]?\b", t)
            if lead:
                raw = lead.group(1)
                n: Optional[int] = None
                if len(raw) <= 2:
                    n = int(raw)
                elif len(raw) == 3 and raw.startswith("0"):
                    n = int(raw[-2:])
                elif len(raw) == 3 and raw.startswith("9"):
                    # OCR artifact seen in notebooks: "Q26" -> "926"
                    n = int(raw[-2:])
                if n is not None and n in q_num_set:
                    return n
            # 3) Numeric token anywhere in margin text (fallback) - only when short text
            tokens = t.split()
            if 1 <= len(tokens) <= 3:
                any_num = re.findall(r"(\d{1,3})", t)
                for raw in any_num:
                    try:
                        val = int(raw)
                    except Exception:
                        continue
                    if val > 200:
                        continue
                    if val in q_num_set:
                        return val
            return None

        def _group_words_into_lines(words: List[dict], y_threshold: float, img_width: float) -> List[dict]:
            items = []
            for w in words:
                try:
                    x1, y1, x2, y2 = w.get("x1"), w.get("y1"), w.get("x2"), w.get("y2")
                    if x1 is None or y1 is None or x2 is None or y2 is None:
                        continue
                    items.append({
                        "text": w.get("text", ""),
                        "x1": x1, "x2": x2,
                        "y1": y1, "y2": y2,
                        "yc": (y1 + y2) / 2
                    })
                except Exception:
                    continue
            items.sort(key=lambda i: (i["yc"], i["x1"]))
            lines = []
            for item in items:
                if not lines:
                    lines.append([item])
                    continue
                last = lines[-1]
                if abs(item["yc"] - last[-1]["yc"]) <= y_threshold:
                    last.append(item)
                else:
                    lines.append([item])
            line_boxes = []
            left_strip_x = float(img_width) * left_strip_ratio
            right_strip_x = float(img_width) * (1 - right_strip_ratio)
            for line in lines:
                xs = [i["x1"] for i in line] + [i["x2"] for i in line]
                ys = [i["y1"] for i in line] + [i["y2"] for i in line]
                text = " ".join(i["text"] for i in line).strip()
                left_items = [i for i in line if float(i["x1"]) <= left_strip_x]
                right_items = [i for i in line if float(i["x2"]) >= right_strip_x]
                left_text = " ".join(i["text"] for i in left_items).strip()
                right_text = " ".join(i["text"] for i in right_items).strip()
                line_boxes.append({
                    "text": text,
                    "left_text": left_text,
                    "right_text": right_text,
                    "x1": min(xs), "y1": min(ys),
                    "x2": max(xs), "y2": max(ys)
                })
            return line_boxes

        output_lines = []
        # Persist active question across pages only when an entire page has no new label.
        carry_q = 0
        for page_offset, img in enumerate(chunk_imgs):
            page_num = start_page_num + page_offset + 1
            try:
                image_data = base64.b64decode(img)
                with Image.open(io.BytesIO(image_data)) as pil_img:
                    img_height = pil_img.size[1]
                    img_width = pil_img.size[0]
            except Exception:
                img_height = 1400
                img_width = 1000

            ocr_result = ocr_provider.detect(img, min_conf=min_confidence)
            words = ocr_result.get("words", [])

            if not words:
                continue

            y_threshold = max(10, int(img_height * 0.012))
            line_boxes = _group_words_into_lines(words, y_threshold, img_width)
            if not line_boxes:
                continue

            output_lines.append(f"Page {page_num}:")

            detected_by_line: List[Optional[int]] = []
            for line in line_boxes:
                detected_by_line.append(
                    _extract_question_number_from_line(
                        left_text=str(line.get("left_text", "") or ""),
                        right_text=str(line.get("right_text", "") or ""),
                        page_num=page_num,
                    )
                )

            has_anchor = any(v is not None for v in detected_by_line)
            current_q = 0 if has_anchor else carry_q
            counters: Dict[int, int] = {}
            for line, detected_q in zip(line_boxes, detected_by_line):
                text = line.get("text", "").strip()
                if detected_q is not None:
                    current_q = detected_q
                    carry_q = detected_q

                if current_q <= 0:
                    # Keep unknown lines grouped separately; they are ignored for chunk question inference.
                    continue

                counters[current_q] = counters.get(current_q, 0) + 1
                line_id = f"Q{current_q}-L{counters[current_q]}"
                safe_text = re.sub(r"\s+", " ", text)
                if "space for writing" in safe_text.lower() or "question number" in safe_text.lower():
                    continue
                if len(safe_text) > 140:
                    safe_text = safe_text[:137] + "..."
                output_lines.append(f"  {line_id}: {safe_text}")

        return "\n".join(output_lines)

    def parse_line_id_context(line_id_context: str) -> Dict[int, List[str]]:
        """
        Parse LINE ID MAP text into a stable question->lines map across pages.
        Output example:
          {6: ["[Page 20] Q6-L1: ...", "[Page 21] Q6-L3: ..."], ...}
        """
        q_map: Dict[int, List[str]] = {}
        if not line_id_context:
            return q_map

        current_page: Optional[int] = None
        for raw_line in line_id_context.splitlines():
            line = (raw_line or "").strip()
            if not line:
                continue

            page_match = re.match(r"^Page\s+(\d+):$", line, re.IGNORECASE)
            if page_match:
                try:
                    current_page = int(page_match.group(1))
                except Exception:
                    current_page = None
                continue

            qline_match = re.match(r"^Q(\d+)-L(\d+):\s*(.*)$", line)
            if not qline_match:
                continue

            q_num = int(qline_match.group(1))
            line_no = qline_match.group(2)
            text = (qline_match.group(3) or "").strip()
            if not text:
                continue

            page_prefix = f"[Page {current_page}] " if current_page is not None else ""
            formatted = f"{page_prefix}Q{q_num}-L{line_no}: {text}"
            q_map.setdefault(q_num, []).append(formatted)

        return q_map

    blueprint_enrichment = build_blueprint_enrichment(questions)
    grade_with_ai.last_blueprint_enrichment = blueprint_enrichment
    for qn, enriched in sorted(blueprint_enrichment.items(), key=lambda item: item[0]):
        contract = (enriched or {}).get("grading_contract", {})
        logger.info(
            "CONTRACT_CREATED exam_id=%s question=%s type=%s rule=%s total=%s subparts=%s",
            exam_id or "unknown",
            qn,
            contract.get("question_type"),
            contract.get("aggregation_rule"),
            contract.get("total_marks"),
            len(contract.get("subparts") or []),
        )

    def build_answer_segments(
        paper_images: List[str],
        questions: List[dict],
        question_paper_pdf_bytes: Optional[bytes] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """
        Build hierarchical structured OCR mapping:
          question -> subquestion -> answer segments (+tables/page refs/extracted text)
        """
        if universal_v2_active:
            try:
                pipeline_result, mapped = run_universal_pipeline_v2(
                    exam_id=exam_id or "unknown_exam",
                    exam_questions=questions,
                    answer_images=paper_images,
                    question_paper_pdf_bytes=question_paper_pdf_bytes,
                    failed_chunks=exam_blueprint_failed_chunks,
                )
                meta = (mapped.get("_meta", {}) or {}).copy()
                meta["pipeline"] = "universal_v2"
                meta["blueprint_health"] = (pipeline_result or {}).get("blueprint_health", {})
                meta["phase_timings"] = (pipeline_result or {}).get("phase_timings", {})
                mapped["_meta"] = meta
                grade_with_ai.last_college_pipeline = pipeline_result
                return mapped
            except Exception as e:
                logger.error("Universal V2 pipeline failed for exam %s: %s", exam_id, e)
                return {
                    "_meta": {
                        "pipeline": "universal_v2",
                        "mapping_status": "failed",
                        "mapping_fail_reasons": [f"universal_v2_pipeline_exception:{e}"],
                        "mapping_coverage": 0.0,
                        "mapped_question_ratio": 0.0,
                        "unresolved_questions": [
                            int(q.get("question_number"))
                            for q in questions
                            if str(q.get("question_number", "")).isdigit()
                        ],
                        "packets_generated": 0,
                        "subpacket_count": 0,
                        "low_confidence_questions": [],
                        "consistency_flags": ["universal_v2_pipeline_failed"],
                    }
                }

        if aws_pipeline_active:
            try:
                pipeline_result, mapped = run_aws_pipeline_v3(
                    exam_id=exam_id or "unknown_exam",
                    exam_questions=questions,
                    answer_images=paper_images,
                )
                meta = (mapped.get("_meta", {}) or {}).copy()
                meta["pipeline"] = "aws_textract_v3"
                meta["phase_timings"] = (pipeline_result or {}).get("phase_timings", {})
                mapped["_meta"] = meta
                grade_with_ai.last_college_pipeline = pipeline_result
                return mapped
            except Exception as e:
                logger.error("AWS pipeline failed for exam %s: %s", exam_id, e)
                return {
                    "_meta": {
                        "pipeline": "aws_textract_v3",
                        "mapping_status": "failed",
                        "mapping_fail_reasons": [f"aws_pipeline_exception:{e}"],
                        "mapping_coverage": 0.0,
                        "mapped_question_ratio": 0.0,
                        "unresolved_questions": [
                            int(q.get("question_number"))
                            for q in questions
                            if str(q.get("question_number", "")).isdigit()
                        ],
                        "packets_generated": 0,
                        "subpacket_count": 0,
                        "low_confidence_questions": [],
                        "consistency_flags": ["aws_pipeline_failed"],
                    }
                }

        if college_v2_active:
            try:
                pipeline_result, mapped = run_college_pipeline_v3(
                    exam_id=exam_id or "unknown_exam",
                    exam_questions=questions,
                    answer_images=paper_images,
                    question_paper_pdf_bytes=question_paper_pdf_bytes,
                    failed_chunks=exam_blueprint_failed_chunks,
                )
                meta = (mapped.get("_meta", {}) or {}).copy()
                meta["pipeline"] = "college_v3"
                meta["blueprint_health"] = (pipeline_result or {}).get("blueprint_health", {})
                meta["phase_timings"] = (pipeline_result or {}).get("phase_timings", {})
                mapped["_meta"] = meta
                grade_with_ai.last_college_pipeline = pipeline_result
                return mapped
            except Exception as e:
                logger.error("College V3 pipeline failed for exam %s: %s", exam_id, e)
                return {
                    "_meta": {
                        "pipeline": "college_v3",
                        "mapping_status": "failed",
                        "mapping_fail_reasons": [f"college_v3_pipeline_exception:{e}"],
                        "mapping_coverage": 0.0,
                        "mapped_question_ratio": 0.0,
                        "unresolved_questions": [
                            int(q.get("question_number"))
                            for q in questions
                            if str(q.get("question_number", "")).isdigit()
                        ],
                        "packets_generated": 0,
                        "subpacket_count": 0,
                        "low_confidence_questions": [],
                        "consistency_flags": ["college_v3_pipeline_failed"],
                    }
                }

        use_packet_pipeline = os.getenv("ANSWER_PACKET_PIPELINE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        if ANSWER_PACKET_PIPELINE_ENABLED and use_packet_pipeline:
            try:
                pipeline_result = run_answer_packet_pipeline(
                    answer_images=paper_images,
                    questions=questions,
                    question_paper_pdf_bytes=question_paper_pdf_bytes or None,
                )
                mapped = pipeline_result_to_question_map(pipeline_result)
                meta = (mapped.get("_meta", {}) or {}).copy()
                meta["pipeline"] = "answer_sheet_packet_pipeline"
                expected_questions = sorted({
                    int(q.get("question_number"))
                    for q in questions
                    if q.get("question_number") is not None and str(q.get("question_number")).isdigit()
                })
                detected_questions = sorted(
                    [
                        int(k)
                        for k, payload in mapped.items()
                        if isinstance(k, int) and isinstance(payload, dict) and (payload.get("segments") or [])
                    ]
                )
                pipeline_coverage = float(meta.get("mapping_coverage", 0.0) or 0.0)
                pipeline_ratio = (
                    len(detected_questions) / float(len(expected_questions))
                    if expected_questions
                    else 0.0
                )
                min_pipeline_coverage = float(os.getenv("ANSWER_PACKET_PIPELINE_MIN_COVERAGE", "0.55"))
                min_pipeline_ratio = float(os.getenv("ANSWER_PACKET_PIPELINE_MIN_Q_RATIO", "0.55"))
                min_pipeline_packets = int(os.getenv("ANSWER_PACKET_PIPELINE_MIN_PACKETS", "4"))
                required_packets = min(len(expected_questions), max(1, min_pipeline_packets)) if expected_questions else 0

                meta["expected_questions"] = expected_questions
                meta["detected_questions"] = detected_questions
                meta["pipeline_coverage"] = round(pipeline_coverage, 4)
                meta["pipeline_mapped_question_ratio"] = round(pipeline_ratio, 4)

                should_fallback_to_legacy = False
                if expected_questions:
                    if pipeline_coverage < min_pipeline_coverage:
                        should_fallback_to_legacy = True
                    if pipeline_ratio < min_pipeline_ratio:
                        should_fallback_to_legacy = True
                    if len(detected_questions) < required_packets:
                        should_fallback_to_legacy = True

                if not should_fallback_to_legacy:
                    mapped["_meta"] = meta
                    return mapped

                logger.warning(
                    "Packet pipeline mapping quality too low; using legacy mapper instead. "
                    "coverage=%.3f ratio=%.3f detected=%s expected=%s",
                    pipeline_coverage,
                    pipeline_ratio,
                    len(detected_questions),
                    len(expected_questions),
                )
            except Exception as e:
                logger.warning("Answer packet pipeline failed; falling back to legacy mapper. err=%s", e)

        ocr = get_ocr_provider()
        force_fallback_on_sparse = os.getenv("OCR_FORCE_FALLBACK_ON_SPARSE", "false").lower() in ("1", "true", "yes", "on")
        expected_qs = sorted({
            int(q.get("question_number"))
            for q in questions
            if q.get("question_number") is not None and str(q.get("question_number")).isdigit()
        })

        segments_by_page: List[List[dict]] = []
        words_by_page: List[List[dict]] = []
        widths: List[float] = []
        page_metrics: List[dict] = []

        for page_idx, img in enumerate(paper_images):
            res = ocr.detect(img)
            words = res.get("words", []) or []
            lines = res.get("lines", []) or []
            tables = res.get("tables", []) or []
            width = float(res.get("width", 1000))
            fallback_used = bool(res.get("fallback_used", False))

            # Retry once with lower thresholds when OCR is sparse.
            if not words or (len(words) < 8 and len(lines) < 3):
                retry = ocr.detect(
                    img,
                    min_conf=0.35,
                    min_words=8,
                    min_lines=2,
                    force_fallback=force_fallback_on_sparse,
                )
                if len(retry.get("words", []) or []) > len(words):
                    res = retry
                    words = res.get("words", []) or []
                    lines = res.get("lines", []) or []
                    tables = res.get("tables", []) or []
                    width = float(res.get("width", width))
                    fallback_used = True

            page_segments = build_page_segments(words=words, tables=tables, page=page_idx + 1)
            segments_by_page.append(page_segments)
            words_by_page.append(words)
            widths.append(width)
            page_metrics.append({
                "page": page_idx + 1,
                "provider": res.get("provider", "unknown"),
                "fallback_used": fallback_used,
                "words": len(words),
                "lines": len(lines),
                "segments": len(page_segments),
                "tables": len(tables),
            })

        mapped = map_segments_to_questions(
            segments_by_page=segments_by_page,
            words_by_page=words_by_page,
            expected_questions=expected_qs,
            page_widths=widths,
        )

        mapper_meta = mapped.get("_meta", {}) if isinstance(mapped, dict) else {}
        mapper_page_metrics = {
            int(item.get("page")): item
            for item in (mapper_meta.get("per_page", []) or [])
            if isinstance(item, dict) and str(item.get("page", "")).isdigit()
        }
        for pm in page_metrics:
            enrich = mapper_page_metrics.get(int(pm.get("page", 0)))
            if not enrich:
                continue
            pm["labels_detected"] = int(enrich.get("labels_detected", 0))
            pm["questions_assigned"] = enrich.get("questions_assigned", [])
            pm["questions_assigned_count"] = int(enrich.get("questions_assigned_count", 0))
            pm["sparse"] = bool(enrich.get("sparse", False))

        page_segment_index = []
        for page_segments in segments_by_page:
            for s in page_segments:
                page_segment_index.append({
                    "segment_id": s.get("segment_id"),
                    "page": int(s.get("page", 1) or 1),
                    "text": (s.get("text", "") or "")[:600],
                    "x1": s.get("x1"),
                    "y1": s.get("y1"),
                    "x2": s.get("x2"),
                    "y2": s.get("y2"),
                })

        mapped["_meta"] = {
            **mapper_meta,
            "expected_questions": expected_qs,
            "detected_questions": sorted([int(k) for k in mapped.keys() if isinstance(k, int)]),
            "per_page": page_metrics,
            "page_segment_index": page_segment_index,
        }
        return mapped
    # Process chunk helper
    async def process_chunk(
        chunk_imgs,
        chunk_idx,
        total_chunks,
        start_page_num,
        forced_question_nums: Optional[List[int]] = None,
        forced_page_set: Optional[set] = None,
    ):
        print(f"\n{'='*70}")
        print(f"[CHUNK-{chunk_idx+1}] === STARTING CHUNK PROCESSING ===")
        if forced_page_set:
            forced_pages = sorted(int(p) for p in forced_page_set)
            print(f"[CHUNK-{chunk_idx+1}] Pages: {forced_pages}")
        else:
            print(f"[CHUNK-{chunk_idx+1}] Pages: {start_page_num+1} to {start_page_num+len(chunk_imgs)}")
        print(f"[CHUNK-{chunk_idx+1}] Total images in chunk: {len(chunk_imgs)}")
        print(f"{'='*70}")
        
        chunk_chat = LlmChat(
            api_key=api_key,
            session_id=f"grading_{content_hash}_{chunk_idx}",
            system_message=master_system_prompt
        ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)

        chunk_all_images = []
        
        if use_text_based_grading:
            for img in chunk_imgs:
                chunk_all_images.append(ImageContent(image_base64=img))
            model_images_included = 0
            logger.info(f"Chunk {chunk_idx+1}: TEXT-BASED grading with {len(chunk_imgs)} student images")
        else:
            if model_answer_images:
                for img in model_answer_images:
                    chunk_all_images.append(ImageContent(image_base64=img))
            for img in chunk_imgs:
                chunk_all_images.append(ImageContent(image_base64=img))
            model_images_included = len(model_answer_images) if model_answer_images else 0
            logger.info(f"Chunk {chunk_idx+1}: IMAGE-BASED grading with {model_images_included} model + {len(chunk_imgs)} student images")
        
        # Build prompt
        partial_instruction = ""
        if forced_question_nums:
            partial_instruction = (
                f"\n**QUESTION-CENTRIC PACKET**: Grade only Q{forced_question_nums[0]} from this packet. "
                "If unrelated content appears, ignore it."
            )
        elif total_chunks > 1:
            partial_instruction = f"""
**PARTIAL SUBMISSION NOTICE**:
This is PART {chunk_idx+1} of {total_chunks} of the student's answer (Pages {start_page_num+1} to {start_page_num+len(chunk_imgs)}).
- Grade ONLY the questions visible in this part.
- If a listed question is not visible here, you may omit it or mark status=not_found; do NOT fabricate marks or blanket -1 for all questions.
- Do not downscore unseen questions; focus on those with evidence in this part.
"""

        # Build learned patterns section
        learned_patterns_section = ""
        if learned_patterns:
            learned_patterns_section = "\n\n## 🧠 YOUR PREVIOUS GRADING GUIDELINES (LEARNED PATTERNS)\n\n"
            learned_patterns_section += "Based on your past corrections, apply these grading standards:\n\n"
            for idx, pattern in enumerate(learned_patterns[:10], 1):
                q_num = pattern.get("question_number", "N/A")
                topic = pattern.get("question_topic", "similar questions")
                correction = pattern.get("teacher_correction", "")
                expected = pattern.get("teacher_expected_grade", "")
                ai_gave = pattern.get("ai_grade", "")
                learned_patterns_section += f"{idx}. **Q{q_num} ({topic})**: {correction}\n"
                if expected and ai_gave:
                    learned_patterns_section += f"   - You adjusted: AI gave {ai_gave} → You expected {expected}\n"
            learned_patterns_section += "\n**Apply these learned standards consistently.**\n"

        chunk_page_set = set(forced_page_set or set(range(start_page_num + 1, start_page_num + len(chunk_imgs) + 1)))
        all_q_nums = [int(q["question_number"]) for q in questions if str(q.get("question_number", "")).isdigit()]
        if forced_question_nums:
            chunk_question_nums = sorted(set(int(qn) for qn in forced_question_nums if int(qn) in all_q_nums))
        else:
            chunk_question_nums = []
            for qn in all_q_nums:
                q_data = whole_paper_answer_segments.get(int(qn), {})
                visible_segments = [
                    s
                    for s in (q_data.get("segments") or [])
                    if int(s.get("page", 0) or 0) in chunk_page_set and str(s.get("text", "")).strip()
                ]
                visible_chars = sum(len(str(s.get("text", "")).strip()) for s in visible_segments)
                mapping_conf = float(q_data.get("mapping_confidence", 0.0) or 0.0)
                has_evidence = bool(visible_segments) and (visible_chars >= 6 or len(visible_segments) >= 1)
                if mapping_conf < 0.45 and visible_chars < 15 and len(visible_segments) < 2:
                    has_evidence = False
                if has_evidence:
                    chunk_question_nums.append(int(qn))
            chunk_question_nums = sorted(set(chunk_question_nums))

        min_detected_threshold = max(2, min(6, len(questions) // 5)) if questions else 0
        include_neighbors = (
            not (college_v2_active or universal_v2_active)
            and os.getenv("OCR_CHUNK_INCLUDE_NEIGHBORS", "false").lower() in ("1", "true", "yes", "on")
        )
        if not forced_question_nums and include_neighbors and chunk_question_nums and len(chunk_question_nums) < min_detected_threshold:
            lowest = min(chunk_question_nums)
            highest = max(chunk_question_nums)
            neighbors = [n for n in all_q_nums if lowest - 1 <= n <= highest + 1]
            chunk_question_nums = sorted(set(chunk_question_nums + neighbors))

        chunk_question_num_set = set(chunk_question_nums)
        if chunk_question_nums:
            logger.info(
                "Chunk %s mapped question numbers: %s",
                chunk_idx + 1,
                chunk_question_nums,
            )

        chunk_questions = [
            q for q in questions
            if str(q.get("question_number", "")).isdigit() and int(q.get("question_number")) in chunk_question_num_set
        ]

        if not chunk_questions:
            if college_v2_active or universal_v2_active:
                logger.info(
                    "Chunk %s has no OCR-backed questions for pages %s-%s in strict layer; skipping without heuristic fallback",
                    chunk_idx + 1,
                    start_page_num + 1,
                    start_page_num + len(chunk_imgs),
                )
                return []
            fallback_questions = []
            for q in questions:
                qn = int(q.get("question_number")) if str(q.get("question_number", "")).isdigit() else None
                if qn is None:
                    continue
                q_data = whole_paper_answer_segments.get(qn, {})
                if any(int(p) in chunk_page_set for p in (q_data.get("page_refs") or [])):
                    fallback_questions.append(q)
            if not forced_question_nums and fallback_questions:
                chunk_questions = fallback_questions
                logger.info(
                    "Chunk %s had no direct OCR-backed questions; using page-ref fallback with %s questions",
                    chunk_idx + 1,
                    len(chunk_questions),
                )
            else:
                logger.info(
                    "Chunk %s has no OCR-backed questions for pages %s-%s; skipping LLM grading for this chunk",
                    chunk_idx + 1,
                    start_page_num + 1,
                    start_page_num + len(chunk_imgs),
                )
                return []

        chunk_questions_text = ""
        for q in chunk_questions:
            q_text = f"Q{q['question_number']}: Max marks = {q['max_marks']}"
            if q.get("sub_questions"):
                q_text += f" [{len(q['sub_questions'])} parts]"
                for sq in q["sub_questions"]:
                    q_text += f"\n  - ({sq['sub_id']}) {sq.get('max_marks', 0)} marks"
            q_text += f"\n  Rubric: {q.get('rubric', q.get('question_text', 'N/A'))}"
            chunk_questions_text += q_text + "\n\n"

        chunk_contract_payload = []
        for q in chunk_questions:
            try:
                qn = int(q.get("question_number"))
            except Exception:
                continue
            enriched = blueprint_enrichment.get(qn, {})
            if not enriched:
                continue
            chunk_contract_payload.append(
                {
                    "question_number": qn,
                    "question_type": enriched.get("question_type"),
                    "grading_contract": enriched.get("grading_contract"),
                }
            )

        structured_payload = []
        for qn in chunk_question_nums:
            q_data = whole_paper_answer_segments.get(int(qn), {})
            if not q_data:
                continue
            segs = [
                {
                    "segment_id": s.get("segment_id"),
                    "page": s.get("page"),
                    "bbox": [s.get("x1"), s.get("y1"), s.get("x2"), s.get("y2")],
                    "text": (s.get("text", "") or "")[:240],
                    "line_refs": s.get("line_refs", []),
                    "confidence": s.get("confidence", 0.0),
                    "tables": s.get("tables", []),
                }
                for s in (q_data.get("segments") or [])
                if int(s.get("page", 0) or 0) in chunk_page_set
            ]
            seg_ids = [s.get("segment_id") for s in segs if s.get("segment_id")]
            combined_text = " ".join((s.get("text", "") or "").strip() for s in segs).strip()
            seg_map = {str(s.get("segment_id")): s for s in segs if s.get("segment_id")}
            sub_map = {}
            sub_packets = []
            for sub in (q_data.get("subanswers") or []):
                sub_id = str(sub.get("sub_id") or "").strip().lower()
                if not sub_id or sub_id == "__full__":
                    continue
                sub_seg_ids = [
                    sid for sid in (sub.get("segment_ids") or [])
                    if sid in seg_map
                ]
                if not sub_seg_ids:
                    continue
                sub_segments = [seg_map[sid] for sid in sub_seg_ids]
                sub_combined = " ".join((s.get("text", "") or "").strip() for s in sub_segments).strip()
                sub_map[sub_id] = sub_seg_ids
                sub_packets.append(
                    {
                        "question_number": qn,
                        "subquestion": sub_id,
                        "segment_ids": sub_seg_ids,
                        "combined_text": sub_combined[:1200],
                        "extracted_text": sub_combined[:1200],
                        "answer_segments": sub_segments[:20],
                        "tables": [t for s in sub_segments for t in (s.get("tables") or [])][:4],
                        "page_refs": sorted({s.get("page") for s in sub_segments if s.get("page")}),
                        "ocr_unreadable": len(sub_segments) == 0,
                        "mapping_confidence": float(sub.get("mapping_confidence", 0.0) or 0.0),
                    }
                )
            table_segment_ids = [
                sid for sid in (q_data.get("table_segments") or [])
                if sid in seg_map
            ]
            working_note_segment_ids = [
                sid for sid in (q_data.get("working_note_segments") or [])
                if sid in seg_map
            ]
            question_entry = {
                "question_number": qn,
                "subquestion": None,
                "segment_ids": seg_ids,
                "combined_text": combined_text[:2000],
                "extracted_text": combined_text[:2000],
                "answer_segments": segs[:30],
                "subquestion_map": sub_map,
                "tables": (q_data.get("tables") or [])[:6],
                "table_segments": table_segment_ids,
                "working_note_segments": working_note_segment_ids,
                "page_refs": [p for p in (q_data.get("page_refs") or []) if p in chunk_page_set],
                "ocr_unreadable": len(segs) == 0,
                "subquestion_count": int(q_data.get("subquestion_count", 0) or 0),
                "mapping_confidence": float(q_data.get("mapping_confidence", 0.0) or 0.0),
                "mapping_trace": q_data.get("mapping_trace", [])[:20],
                "start_anchor": q_data.get("start_anchor"),
                "end_anchor": q_data.get("end_anchor"),
            }
            structured_payload.append(question_entry)
            structured_payload.extend(sub_packets)
        structured_answer_section = (
            "\n\n## STRUCTURED ANSWER SEGMENTS\n"
            "Use only this structured OCR evidence for grading and annotations.\n"
            f"```json\n{json.dumps(structured_payload, ensure_ascii=True)}\n```\n"
        )
        contract_section = (
            "\n\n## BLUEPRINT ENRICHMENT CONTRACT (DETERMINISTIC)\n"
            "You MUST use this for interpretation only. Do NOT assign marks.\n"
            f"```json\n{json.dumps(chunk_contract_payload, ensure_ascii=True)}\n```\n"
        )
        
        # Build the actual prompt based on grading type
        if use_text_based_grading:
            prompt_text = f"""# GRADING TASK {f'(Part {chunk_idx+1}/{total_chunks})' if total_chunks > 1 else ''}

## MODEL ANSWER REFERENCE (Pre-Extracted Text)
--- MODEL ANSWER START ---
{model_answer_text}
--- MODEL ANSWER END ---

## STUDENT PAPER EVALUATION
**Questions to Grade (ONLY these):**
{chunk_questions_text}

**Images Provided:** {len(chunk_imgs)} pages of STUDENT'S ANSWER PAPER (Pages {start_page_num+1}-{start_page_num+len(chunk_imgs)})
{partial_instruction}
{learned_patterns_section}
{structured_answer_section}
{contract_section}

## GRADING MODE: {grading_mode.upper()}
{grading_instruction}

## CRITICAL REQUIREMENTS:
1. CONSISTENCY IS SACRED: Same answer = Same score ALWAYS
2. MODEL ANSWER IS REFERENCE
3. You are NOT allowed to assign marks. Return only quality_score per question/subpart.
4. quality_score must be in [0,1], or -1.0 for not_found.
5. CALCULATION VERIFICATION for mathematical problems
6. FEEDBACK QUALITY: Constructive, specific
7. Grade ONLY the listed questions for this chunk
8. If a listed question is not visible in this part, omit it or mark status=not_found; do NOT assign blanket -1.
9. SUB-QUESTION GRADING: Return quality_score per sub-part.
10. HANDLE ROTATION: Read sideways text

Return valid JSON only."""

        elif model_answer_images:
            prompt_text = f"""# GRADING TASK {f'(Part {chunk_idx+1}/{total_chunks})' if total_chunks > 1 else ''}

## PHASE 1: PRE-GRADING ANALYSIS
Analyze the MODEL ANSWER thoroughly first.

## PHASE 2: STUDENT PAPER EVALUATION
**Questions to Grade (ONLY these):**
{chunk_questions_text}

**Image Layout:**
- First {model_images_included} image(s): MODEL ANSWER
- Next {len(chunk_imgs)} images: STUDENT'S ANSWER PAPER
{partial_instruction}
{structured_answer_section}
{contract_section}

## GRADING MODE: {grading_mode.upper()}
{grading_instruction}

## CRITICAL REQUIREMENTS:
1. CONSISTENCY IS SACRED
2. MODEL ANSWER IS REFERENCE
3. You are NOT allowed to assign marks. Return only quality_score.
4. quality_score must be in [0,1], or -1.0 for not_found.
5. FEEDBACK QUALITY: Constructive, specific
6. Grade ONLY the listed questions for this chunk
7. If a listed question is not visible in this part, omit it or mark status=not_found; do NOT assign blanket -1.
8. SUB-QUESTION GRADING: Return quality_score per sub-part.
9. ANSWER CONTINUATION: Answers may continue on later pages
10. Output only the questions listed for this chunk

Return valid JSON only."""
        else:
            prompt_text = f"""# GRADING TASK (WITHOUT MODEL ANSWER) {f'(Part {chunk_idx+1}/{total_chunks})' if total_chunks > 1 else ''}

No Model Answer Provided. Grade based on rubrics and subject knowledge.

**Questions to Grade (ONLY these):**
{chunk_questions_text}

**Images:** STUDENT'S ANSWER PAPER (Pages {start_page_num+1}-{start_page_num+len(chunk_imgs)})
{partial_instruction}
{structured_answer_section}
{contract_section}

## GRADING MODE: {grading_mode.upper()}
{grading_instruction}

## CRITICAL REQUIREMENTS:
1. RUBRIC-BASED: Use provided rubrics as primary reference
2. You are NOT allowed to assign marks. Return only quality_score.
3. quality_score must be in [0,1], or -1.0 for not_found.
4. CONSERVATIVE FLAGGING: Flag uncertain gradings
5. If a listed question is not visible in this part, omit it or mark status=not_found; do NOT assign blanket -1.
6. SUB-QUESTION GRADING: Return quality_score per sub-part.
7. Output only the questions listed for this chunk

Return valid JSON only."""

        user_msg = UserMessage(text=prompt_text, file_contents=chunk_all_images)

        print(f"[CHUNK-{chunk_idx+1}] Total images: {len(chunk_all_images)}, Prompt: {len(prompt_text)} chars")
        
        # Retry logic
        max_retries = 3
        base_retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = base_retry_delay * (2 ** attempt)
                    logger.info(f"Waiting {wait_time}s before retry {attempt+1}")
                    await asyncio.sleep(wait_time)
                
                print(f"[CHUNK-{chunk_idx+1}] Sending to AI (attempt {attempt+1}/{max_retries})...")
                
                try:
                    ai_resp = await asyncio.wait_for(
                        chunk_chat.send_message(user_msg),
                        timeout=240.0
                    )
                except asyncio.TimeoutError:
                    logger.error(f"Timeout after 240s grading chunk {chunk_idx+1} attempt {attempt+1}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        raise TimeoutError(f"AI grading timed out after {max_retries} attempts")

                resp_text = ai_resp.strip()
                print(f"[CHUNK-{chunk_idx+1}] AI response received ({len(resp_text)} chars)")
               
                # DEBUG: Show raw response to check for line IDs
                print(f"\n{'='*70}")
                print(f"[DEBUG] Raw Gemini Response (first 1500 chars):")
                print(resp_text[:1500])
                print(f"{'='*70}\n")
                
                # Strategy 1: Direct parse
                def _filter_forced(scores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                    if not forced_question_nums:
                        return scores
                    forced_set = {int(qn) for qn in forced_question_nums}
                    out = []
                    for item in scores or []:
                        try:
                            qn = int(item.get("question_number"))
                        except Exception:
                            continue
                        if qn in forced_set:
                            out.append(item)
                    return out

                try:
                    res = json.loads(resp_text)
                    scores = _filter_forced(res.get("scores", []))
                    print(f"[CHUNK-{chunk_idx+1}] Parsed JSON - {len(scores)} questions graded")
                    return scores
                except json.JSONDecodeError:
                    pass
                
                # Strategy 2: Remove code blocks
                if resp_text.startswith("```"):
                    resp_text = resp_text.split("```")[1]
                    if resp_text.startswith("json"):
                        resp_text = resp_text[4:]
                    resp_text = resp_text.strip()
                    try:
                        res = json.loads(resp_text)
                        return _filter_forced(res.get("scores", []))
                    except json.JSONDecodeError:
                        pass
                
                # Strategy 3: Find JSON in response
                json_match = re.search(r'\{[^{}]*"scores"[^{}]*\[[^\]]*\][^{}]*\}', resp_text, re.DOTALL)
                if json_match:
                    try:
                        res = json.loads(json_match.group())
                        return _filter_forced(res.get("scores", []))
                    except json.JSONDecodeError:
                        pass
                
                logger.warning(f"Failed to parse grading JSON (attempt {attempt + 1})")
                if attempt < max_retries - 1:
                    continue
                else:
                    return []

            except Exception as e:
                error_msg = str(e).lower()
                if "502" in str(e) or "503" in str(e) or "timeout" in error_msg:
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return []
                if "429" in str(e) or "rate limit" in error_msg:
                    wait_time = 60 * (attempt + 1)
                    await asyncio.sleep(wait_time)
                    if attempt < max_retries - 1:
                        continue
                    else:
                        raise HTTPException(status_code=429, detail="API rate limit exceeded.")
                logger.error(f"Error grading chunk {chunk_idx+1}: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    raise e

        return []


    question_wise_packet_grading = os.getenv("QUESTION_WISE_PACKET_GRADING", "true").lower() in ("1", "true", "yes", "on")
    if college_v2_active or universal_v2_active or aws_pipeline_active:
        question_wise_packet_grading = True
    effective_mapping_hard_stop = (
        UNIVERSAL_HARD_STOP
        if universal_v2_active
        else (COLLEGE_V2_HARD_STOP if college_v2_active else MAPPING_HARD_STOP)
    )
    if effective_mapping_hard_stop and not question_wise_packet_grading:
        logger.warning(
            "QUESTION_WISE_PACKET_GRADING is disabled but MAPPING_HARD_STOP is enabled; forcing question-wise mode."
        )
        question_wise_packet_grading = True
    # CHUNKED PROCESSING LOGIC
    CHUNK_SIZE = 10
    OVERLAP = 1
    total_student_pages = len(corrected_images)
    
    chunks = []
    if not question_wise_packet_grading:
        if total_student_pages <= 10:
            chunks.append((0, corrected_images))
        else:
            for i in range(0, total_student_pages, CHUNK_SIZE):
                start_idx = max(0, i - OVERLAP) if i > 0 else 0
                end_idx = min(total_student_pages, i + CHUNK_SIZE)
                chunk = corrected_images[start_idx:end_idx]
                if chunk:
                    chunks.append((start_idx, chunk))
                if i + CHUNK_SIZE >= total_student_pages:
                    break
    
    logger.info(f"Processing student paper in {len(chunks) if chunks else len(questions)} chunk(s)")
    logger.info(f"Questions to grade: {[q['question_number'] for q in questions]}")

    question_paper_pdf_bytes: Optional[bytes] = None
    if exam_id:
        try:
            question_paper_pdf_bytes = await get_exam_question_paper_pdf_bytes(exam_id)
        except Exception as e:
            logger.warning("Could not load question-paper PDF bytes for exam %s: %s", exam_id, e)

    # Build a whole-paper structured OCR map so chunk grading uses stable
    # question/subquestion -> segment mappings instead of raw OCR dumps.
    whole_paper_answer_segments = build_answer_segments(
        corrected_images,
        questions,
        question_paper_pdf_bytes=question_paper_pdf_bytes,
    )
    grade_with_ai.last_answer_segments = whole_paper_answer_segments
    packet_meta = (whole_paper_answer_segments.get("_meta", {}) or {}).copy()
    packet_meta["grading_reference_mode"] = grading_reference_mode
    logger.info(
        "[PACKET-MAP] coverage=%.3f packets=%s subpackets=%s low_conf=%s flags=%s mode=%s",
        float(packet_meta.get("mapping_coverage", 0.0) or 0.0),
        int(packet_meta.get("packets_generated", 0) or 0),
        int(packet_meta.get("subpacket_count", 0) or 0),
        packet_meta.get("low_confidence_questions", []),
        packet_meta.get("consistency_flags", []),
        grading_reference_mode,
    )

    detected_q_nums = {
        int(k) for k, v in whole_paper_answer_segments.items()
        if isinstance(k, int) and isinstance(v, dict) and (v.get("segments") or [])
    }
    expected_q_nums = sorted({
        int(q.get("question_number"))
        for q in questions
        if q.get("question_number") is not None and str(q.get("question_number", "")).isdigit()
    })

    total_expected_questions = len(expected_q_nums)
    mapped_q_nums = sorted(detected_q_nums)
    mapped_question_ratio = (
        len(mapped_q_nums) / float(total_expected_questions)
        if total_expected_questions > 0 else 0.0
    )
    mapping_coverage = float(packet_meta.get("mapping_coverage", 0.0) or 0.0)
    unresolved_questions = sorted(set(expected_q_nums) - set(mapped_q_nums))
    unresolved_count = len(unresolved_questions)
    unresolved_limit = max(2, int(math.ceil(total_expected_questions * UNRESOLVED_RATIO_MAX))) if total_expected_questions else 0

    mapping_fail_reasons: List[str] = []
    if mapped_question_ratio < MAPPED_QUESTION_RATIO_MIN:
        mapping_fail_reasons.append(
            f"mapped_question_ratio_below_threshold:{mapped_question_ratio:.3f}<{MAPPED_QUESTION_RATIO_MIN:.3f}"
        )
    if mapping_coverage < MAPPING_COVERAGE_GATE_MIN:
        mapping_fail_reasons.append(
            f"mapping_coverage_below_threshold:{mapping_coverage:.3f}<{MAPPING_COVERAGE_GATE_MIN:.3f}"
        )
    if unresolved_count > unresolved_limit:
        mapping_fail_reasons.append(
            f"too_many_unresolved_questions:{unresolved_count}>{unresolved_limit}"
        )
    for reason in (packet_meta.get("mapping_fail_reasons") or []):
        if reason not in mapping_fail_reasons:
            mapping_fail_reasons.append(str(reason))
    packet_mapping_status = str(packet_meta.get("mapping_status", "") or "").lower()
    if packet_mapping_status in ("failed", "needs_review", "partial") and not mapping_fail_reasons:
        mapping_fail_reasons.append(f"pipeline_mapping_status:{packet_mapping_status}")

    resolved_mapping_status = "needs_review" if mapping_fail_reasons else "pass"
    if packet_mapping_status == "failed":
        resolved_mapping_status = "failed"

    packet_meta.update(
        {
            "mapped_question_ratio": round(mapped_question_ratio, 4),
            "mapping_coverage": round(mapping_coverage, 4),
            "unresolved_questions": unresolved_questions,
            "unresolved_questions_count": unresolved_count,
            "expected_questions_count": total_expected_questions,
            "mapped_questions_count": len(mapped_q_nums),
            "mapping_fail_reasons": mapping_fail_reasons,
            "mapping_status": resolved_mapping_status,
        }
    )

    def _question_max_marks(question_def: dict) -> float:
        try:
            qn = int(question_def.get("question_number"))
        except Exception:
            qn = None
        if qn is not None:
            contract = ((blueprint_enrichment.get(qn) or {}).get("grading_contract") or {})
            contract_total = float(contract.get("total_marks") or 0.0)
            if contract_total > 0:
                return contract_total
        value = float(question_def.get("max_marks") or 0.0)
        return value if value > 0 else 1.0

    def _build_needs_review_scores(fail_reasons: List[str]) -> List[QuestionScore]:
        reason_text = "; ".join(fail_reasons) if fail_reasons else "mapping_quality_failed"
        feedback = (
            "Auto-grading blocked because question mapping quality is below threshold. "
            f"Reasons: {reason_text}. Please run preflight mapping and review manually."
        )
        blocked_scores: List[QuestionScore] = []
        for q in sorted(
            [item for item in questions if str(item.get("question_number", "")).isdigit()],
            key=lambda item: int(item.get("question_number")),
        ):
            q_num = int(q.get("question_number"))
            blocked_scores.append(
                QuestionScore(
                    question_number=q_num,
                    max_marks=_question_max_marks(q),
                    obtained_marks=0.0,
                    ai_feedback=feedback,
                    question_text=q.get("question_text") or q.get("rubric"),
                    status="not_found",
                    annotations=[],
                )
            )
        return blocked_scores

    if effective_mapping_hard_stop and mapping_fail_reasons:
        logger.warning(
            "[MAPPING-HARD-STOP] exam_id=%s mapped_ratio=%.3f coverage=%.3f unresolved=%s/%s reasons=%s",
            exam_id or "unknown",
            mapped_question_ratio,
            mapping_coverage,
            unresolved_count,
            unresolved_limit,
            mapping_fail_reasons,
        )
        packet_meta["consistency_flags"] = sorted(set((packet_meta.get("consistency_flags") or []) + ["mapping_gate_failed"]))
        allow_partial = _allow_college_v2_partial_grading(
            college_v2_active=(college_v2_active and not universal_v2_active),
            mapped_questions_count=len(mapped_q_nums),
            mapping_coverage=mapping_coverage,
        )
        if allow_partial:
            logger.warning(
                "[MAPPING-PARTIAL-OVERRIDE] exam_id=%s proceeding with partial grading: mapped=%s/%s coverage=%.3f",
                exam_id or "unknown",
                len(mapped_q_nums),
                total_expected_questions,
                mapping_coverage,
            )
            packet_meta["partial_grading_override"] = True
            packet_meta["partial_grading_reason"] = "mapping_incomplete_but_usable"
        else:
            grade_with_ai.last_packet_meta = packet_meta
            grade_with_ai.last_grading_reference_mode = grading_reference_mode
            grade_with_ai.last_answer_segments = whole_paper_answer_segments
            return _build_needs_review_scores(mapping_fail_reasons)

    all_chunk_results = []
    if question_wise_packet_grading:
        question_list = [q for q in questions if str(q.get("question_number", "")).isdigit()]
        question_list.sort(key=lambda q: int(q["question_number"]))
        logger.info("Using question-wise packet grading for %s questions", len(question_list))
        for idx, q in enumerate(question_list):
            qn = int(q["question_number"])
            q_data = whole_paper_answer_segments.get(qn, {}) or {}
            page_refs = sorted({int(p) for p in (q_data.get("page_refs") or []) if str(p).isdigit()})
            page_refs = [p for p in page_refs if 1 <= p <= len(corrected_images)]
            if not page_refs:
                logger.info("Q%s has no mapped page refs; marking unresolved and skipping packet call", qn)
                all_chunk_results.append([])
                continue
            packet_imgs = [corrected_images[p - 1] for p in page_refs]
            print(f"\n[GRADING-PROGRESS] Processing question packet {idx+1}/{len(question_list)} (Q{qn})...")
            packet_scores_data = await process_chunk(
                packet_imgs,
                idx,
                len(question_list),
                page_refs[0] - 1,
                forced_question_nums=[qn],
                forced_page_set=set(page_refs),
            )
            print(f"[GRADING-PROGRESS] Q{qn} packet returned {len(packet_scores_data)} score(s)")
            all_chunk_results.append(packet_scores_data)
    else:
        for idx, (start_idx, chunk_imgs) in enumerate(chunks):
            print(f"\n[GRADING-PROGRESS] Processing chunk {idx+1}/{len(chunks)}...")
            chunk_scores_data = await process_chunk(chunk_imgs, idx, len(chunks), start_idx)
            print(f"[GRADING-PROGRESS] Chunk {idx+1} returned {len(chunk_scores_data)} question scores")
            all_chunk_results.append(chunk_scores_data)

    def _normalize_q_key(value) -> str:
        """Normalize question keys reliably.

        Accepts formats like: 1, '1.', 'Q1', 'Q1.', 'Question 1', 'question-1', etc.
        Returns only the numeric portion as a string (e.g. '1').
        """
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        # remove common prefixes like 'q', 'question'
        text = re.sub(r'^(?:q(?:uestion)?)[\s:\.\-]*', '', text, flags=re.IGNORECASE)
        # capture first integer token
        m = re.search(r"(\d+)", text)
        if m:
            return m.group(1)
        # fallback: strip punctuation and whitespace
        return re.sub(r"[^a-z0-9]", "", text.strip().lower())

    def _normalize_sub_key(value) -> str:
        if value is None:
            return ""
        s = str(value).strip().lower()
        # remove surrounding parentheses, dots and non-alphanumeric
        s = re.sub(r"^[\(\)\s\.\-]+|[\(\)\s\.\-]+$", "", s)
        s = re.sub(r"[^a-z0-9]", "", s)
        return s

    # Log any AI-returned question numbers that don't match the exam's question keys
    exam_q_keys = {_normalize_q_key(q.get("question_number")): q for q in questions}
    ai_reported_keys = set()
    for chunk_result in all_chunk_results:
        for s in chunk_result:
            ai_key = _normalize_q_key(s.get("question_number"))
            if ai_key:
                ai_reported_keys.add(ai_key)
    unmatched_ai_keys = [k for k in ai_reported_keys if k not in exam_q_keys]
    if unmatched_ai_keys:
        logger.warning(f"AI returned question identifiers not present in exam questions: {unmatched_ai_keys}. This may indicate OCR/question-order mismatch or AI labeling variability.")

    # Deterministic aggregation via blueprint contract: quality -> contract -> marks
    final_scores = []

    def _candidate_quality(score_data: dict, question_def: dict, q_max: float) -> tuple:
        if not score_data:
            return (-10**9, -10**9)

        quality_ratio = extract_quality_score(score_data, q_max)
        feedback = str(score_data.get("ai_feedback") or "").lower()
        status = str(score_data.get("status") or "").lower()
        annotations = score_data.get("annotations") or []
        sub_scores = score_data.get("sub_scores") or []
        expected_subs = (question_def.get("sub_questions") or [])

        rank = quality_ratio * 100.0
        if status in ("graded", "correct", "partial"):
            rank += 3.0
        if status == "not_found":
            rank -= 8.0
        if status == "not_attempted":
            rank -= 2.0
        if "not found" in feedback:
            rank -= 6.0
        elif feedback:
            rank += min(len(feedback), 120) / 120.0
        if annotations:
            rank += 1.5
        if expected_subs:
            expected_count = len(expected_subs)
            got_count = len([s for s in sub_scores if s.get("sub_id") is not None])
            if got_count >= expected_count and expected_count > 0:
                rank += 3.0
            elif got_count > 0:
                rank += 1.0

        return (rank, quality_ratio)

    def _aggregate_from_sub_marks(contract: dict, sub_mark_map: Dict[str, float]) -> float:
        rule = str(contract.get("aggregation_rule") or "sum")
        total_marks = float(contract.get("total_marks") or 0.0)
        ordered_values = sorted(sub_mark_map.items(), key=lambda kv: kv[1], reverse=True)
        if rule == "best_of":
            return float(ordered_values[0][1]) if ordered_values else 0.0
        if rule == "attempt_k_of_n":
            k = int(contract.get("attempt_k") or 1)
            k = max(1, min(k, len(ordered_values)))
            return float(sum(v for _, v in ordered_values[:k]))
        if rule == "binary":
            return total_marks if ordered_values and all(v > 0 for _, v in ordered_values) else 0.0
        total = float(sum(sub_mark_map.values()))
        return min(total, total_marks)

    for q in questions:
        if not str(q.get("question_number", "")).isdigit():
            continue
        q_num = int(q["question_number"])
        q_key = _normalize_q_key(q_num)
        contract = ((blueprint_enrichment.get(q_num) or {}).get("grading_contract") or {})
        safe_max = float(contract.get("total_marks") or q.get("max_marks") or 1.0)
        if safe_max <= 0:
            safe_max = 1.0
        if not contract:
            contract = {
                "question_number": q_num,
                "question_type": "descriptive",
                "total_marks": safe_max,
                "subparts": [],
                "aggregation_rule": "sum",
                "strictness": "rubric",
                "allow_fractional": True,
            }

        best_score_data = None
        best_rank = (-10**9, -10**9)
        for chunk_result in all_chunk_results:
            score_data = next(
                (s for s in chunk_result if _normalize_q_key(s.get("question_number")) == q_key),
                None
            )
            if not score_data:
                continue
            rank = _candidate_quality(score_data, q, safe_max)
            if rank > best_rank:
                best_rank = rank
                best_score_data = score_data

        if not best_score_data:
            unreadable = int(q_num) not in detected_q_nums
            best_score_data = {
                "question_number": q_num,
                "quality_score": -1.0,
                "ai_feedback": (
                    "OCR could not reliably extract this question answer; manual review recommended."
                    if unreadable
                    else "Question not found in any page (or grading failed)"
                ),
                "status": "not_found",
                "sub_scores": [],
            }

        status = str(best_score_data.get("status") or "").strip().lower() or "graded"
        q_quality = extract_quality_score(best_score_data, safe_max)
        if q_quality < 0:
            status = "not_found"
        elif status == "not_found":
            status = "graded"

        sub_quality_map: Dict[str, float] = {}
        sub_status_map: Dict[str, str] = {}
        sub_feedback_map: Dict[str, str] = {}
        sub_annotation_map: Dict[str, List[dict]] = {}

        contract_subparts = contract.get("subparts") or []
        for sp in contract_subparts:
            sid = str(sp.get("id") or "").strip()
            sid_key = _normalize_sub_key(sid)
            if not sid_key:
                continue
            best_sq_data = None
            best_sq_rank = (-10**9, -10**9)
            sub_max = float(sp.get("marks") or 0.0)
            for chunk_result in all_chunk_results:
                q_score_in_chunk = next(
                    (s for s in chunk_result if _normalize_q_key(s.get("question_number")) == q_key),
                    None
                )
                if not q_score_in_chunk:
                    continue
                for sq_payload in (q_score_in_chunk.get("sub_scores") or []):
                    if _normalize_sub_key(sq_payload.get("sub_id")) != sid_key:
                        continue
                    sq_quality = extract_quality_score(sq_payload, sub_max)
                    sq_status = str(sq_payload.get("status") or "").lower()
                    sq_feedback = str(sq_payload.get("ai_feedback") or "").lower()
                    sq_rank = (sq_quality * 100.0, 0.0)
                    if sq_status in ("graded", "correct", "partial"):
                        sq_rank = (sq_rank[0] + 2.0, sq_rank[1])
                    if sq_status == "not_found" or "not found" in sq_feedback:
                        sq_rank = (sq_rank[0] - 4.0, sq_rank[1])
                    if sq_rank > best_sq_rank:
                        best_sq_rank = sq_rank
                        best_sq_data = sq_payload

            if best_sq_data:
                sub_quality_map[sid_key] = extract_quality_score(best_sq_data, sub_max)
                sub_status_map[sid_key] = str(best_sq_data.get("status") or "graded")
                sub_feedback_map[sid_key] = str(best_sq_data.get("ai_feedback") or "")
                sub_annotation_map[sid_key] = best_sq_data.get("annotations") or []
            else:
                sub_quality_map[sid_key] = -1.0 if status == "not_found" else 0.0
                sub_status_map[sid_key] = "not_found" if status == "not_found" else "not_attempted"
                sub_feedback_map[sid_key] = "Not attempted/found"
                sub_annotation_map[sid_key] = []

        contract_result = apply_grading_contract(
            contract=contract,
            question_quality=q_quality,
            sub_qualities=sub_quality_map,
            question_status=status,
            sub_status=sub_status_map,
        )

        if contract_result.get("cap_applied"):
            logger.info(
                "MARK_CAP_APPLIED exam_id=%s question=%s cap=%s",
                exam_id or "unknown",
                q_num,
                safe_max,
            )

        if contract.get("aggregation_rule") in {"best_of", "attempt_k_of_n"}:
            logger.info(
                "OR_SELECTION exam_id=%s question=%s rule=%s selected=%s",
                exam_id or "unknown",
                q_num,
                contract.get("aggregation_rule"),
                contract_result.get("selected_subparts", []),
            )

        logger.info(
            "CONTRACT_APPLIED exam_id=%s question=%s type=%s rule=%s quality=%.3f obtained=%.3f/%s",
            exam_id or "unknown",
            q_num,
            contract.get("question_type"),
            contract.get("aggregation_rule"),
            float(q_quality),
            float(contract_result.get("obtained_marks", 0.0)),
            safe_max,
        )

        final_sub_scores: List[SubQuestionScore] = []
        for sp in contract_subparts:
            sid = str(sp.get("id") or "").strip()
            sid_key = _normalize_sub_key(sid)
            sub_max = float(sp.get("marks") or 0.0)
            if sub_max <= 0:
                sub_max = 1.0
            sub_obtained = float((contract_result.get("subpart_marks") or {}).get(sid_key, 0.0))
            sq_annotations = normalize_ai_annotations(sub_annotation_map.get(sid_key, []))
            final_sub_scores.append(
                SubQuestionScore(
                    sub_id=sid,
                    max_marks=sub_max,
                    obtained_marks=min(max(0.0, sub_obtained), sub_max),
                    ai_feedback=sub_feedback_map.get(sid_key) or "Not attempted/found",
                    annotations=sq_annotations,
                )
            )

        # Extract question-level annotations from all chunks for multi-page coverage
        all_q_annotations = []
        for chunk_result in all_chunk_results:
            chunk_q_data = next(
                (s for s in chunk_result if _normalize_q_key(s.get("question_number")) == q_key),
                None
            )
            if chunk_q_data:
                all_q_annotations.extend(chunk_q_data.get("annotations", []))
        annotations_list = normalize_ai_annotations(all_q_annotations)
        if not annotations_list and status == "graded":
            annotations_list = [
                AnnotationData(
                    type=AnnotationType.COMMENT,
                    x=0,
                    y=0,
                    text="Revise",
                    color="red",
                    size=18,
                    page_index=-1,
                )
            ]

        question_obtained = float(contract_result.get("obtained_marks") or 0.0)
        question_obtained = min(max(0.0, question_obtained), safe_max)

        qs_obj = QuestionScore(
            question_number=q_num,
            max_marks=safe_max,
            obtained_marks=question_obtained,
            ai_feedback=str(best_score_data.get("ai_feedback") or ""),
            sub_scores=[s.model_dump() for s in final_sub_scores],
            question_text=q.get("question_text") or q.get("rubric"),
            status=status,
            annotations=annotations_list,
        )
        final_scores.append(qs_obj)
    
    # Deduplicate
    seen_q_nums = set()
    deduplicated = []
    for qs in final_scores:
        if qs.question_number not in seen_q_nums:
            seen_q_nums.add(qs.question_number)
            deduplicated.append(qs)
    final_scores = deduplicated

    # Enforce UPSC caps
    final_scores = enforce_upsc_strict_caps(
        scores=final_scores,
        questions=questions,
        grading_mode=grading_mode,
        is_upsc=is_upsc,
    )

    # Post-grading contract validation and deterministic auto-recalc.
    validation_adjustments = 0
    total_obtained = 0.0
    total_max = 0.0
    for qs in final_scores:
        qn = int(qs.question_number)
        contract = ((blueprint_enrichment.get(qn) or {}).get("grading_contract") or {})
        if not contract:
            total_obtained += float(qs.obtained_marks or 0.0)
            total_max += float(qs.max_marks or 0.0)
            continue

        allow_fractional = bool(contract.get("allow_fractional", True))
        contract_total = float(contract.get("total_marks") or qs.max_marks or 0.0)
        if contract_total <= 0:
            contract_total = float(qs.max_marks or 1.0)
        if abs(float(qs.max_marks or 0.0) - contract_total) > 1e-6:
            qs.max_marks = contract_total
            validation_adjustments += 1

        if qs.sub_scores:
            sub_mark_map = {}
            sub_max_map = {}
            for sub in qs.sub_scores:
                sub_id_value = sub.get("sub_id") if isinstance(sub, dict) else getattr(sub, "sub_id", None)
                sid = _normalize_sub_key(sub_id_value)
                sub_max_value = sub.get("max_marks") if isinstance(sub, dict) else getattr(sub, "max_marks", 0.0)
                sub_obt_value = sub.get("obtained_marks") if isinstance(sub, dict) else getattr(sub, "obtained_marks", 0.0)
                sub_max = float(sub_max_value or 0.0)
                sub_obt = float(sub_obt_value or 0.0)
                if sub_max <= 0:
                    sub_max = 1.0
                    if isinstance(sub, dict):
                        sub["max_marks"] = sub_max
                    else:
                        sub.max_marks = sub_max
                    validation_adjustments += 1
                if sub_obt > sub_max + 1e-6:
                    if isinstance(sub, dict):
                        sub["obtained_marks"] = sub_max
                    else:
                        sub.obtained_marks = sub_max
                    sub_obt = sub_max
                    validation_adjustments += 1
                if sub_obt < 0:
                    if isinstance(sub, dict):
                        sub["obtained_marks"] = 0.0
                    else:
                        sub.obtained_marks = 0.0
                    sub_obt = 0.0
                    validation_adjustments += 1
                sub_mark_map[sid] = sub_obt
                sub_max_map[sid] = sub_max

            recomputed = _aggregate_from_sub_marks(contract, sub_mark_map)
            if recomputed > contract_total + 1e-6:
                recomputed = contract_total
                logger.info(
                    "MARK_CAP_APPLIED exam_id=%s question=%s cap=%s",
                    exam_id or "unknown",
                    qn,
                    contract_total,
                )
            if not allow_fractional:
                step = min([v for v in sub_max_map.values() if v > 0], default=contract_total)
                if step > 0:
                    recomputed = round(round(recomputed / step) * step, 4)
            if abs(float(qs.obtained_marks or 0.0) - float(recomputed)) > 1e-6:
                qs.obtained_marks = float(recomputed)
                validation_adjustments += 1
        else:
            q_obt = float(qs.obtained_marks or 0.0)
            if q_obt > contract_total + 1e-6:
                qs.obtained_marks = contract_total
                q_obt = contract_total
                validation_adjustments += 1
                logger.info(
                    "MARK_CAP_APPLIED exam_id=%s question=%s cap=%s",
                    exam_id or "unknown",
                    qn,
                    contract_total,
                )
            if q_obt < 0:
                qs.obtained_marks = 0.0
                validation_adjustments += 1
            if not allow_fractional:
                step = contract_total if contract_total > 0 else 1.0
                quantized = round(round(float(qs.obtained_marks or 0.0) / step) * step, 4)
                if abs(float(qs.obtained_marks or 0.0) - quantized) > 1e-6:
                    qs.obtained_marks = quantized
                    validation_adjustments += 1

        total_obtained += float(qs.obtained_marks or 0.0)
        total_max += float(qs.max_marks or 0.0)

    logger.info(
        "TOTAL_VALIDATED exam_id=%s obtained=%.3f max=%.3f adjustments=%s",
        exam_id or "unknown",
        total_obtained,
        total_max,
        validation_adjustments,
    )

    # Store in Cache and DB
    try:
        if not effective_skip_cache:
            grading_cache[paper_hash] = final_scores
            grading_cache_meta[paper_hash] = packet_meta
            results_json = json.dumps([s.model_dump() for s in final_scores])
            await db.grading_results.update_one(
                {"paper_hash": paper_hash},
                {"$set": {
                    "paper_hash": paper_hash,
                    "results": results_json,
                    "mapping_meta": packet_meta,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }},
                upsert=True
            )
    except Exception as e:
        logger.error(f"Error saving grading cache: {e}")

    grade_with_ai.last_packet_meta = packet_meta
    grade_with_ai.last_grading_reference_mode = grading_reference_mode
    grade_with_ai.last_answer_segments = whole_paper_answer_segments
    return final_scores


# ============== BACKGROUND GRADING JOB ==============

async def process_grading_job_in_background(job_id: str, exam_id: str, files_data: List[dict], exam: dict, teacher_id: str):
    """Background task to process papers one by one."""
    # Lazy imports to avoid circular dependencies
    from app.services.gridfs_helpers import get_exam_model_answer_images
    from app.services.extraction import (
        auto_extract_questions,
        get_exam_model_answer_text,
        get_exam_model_answer_map,
    )
    from app.services.student_detection import extract_student_info_from_paper, parse_student_from_filename, get_or_create_student
    from app.services.answer_sheet_pipeline import pdf_to_clean_images
    from app.services.file_processing import pdf_to_images
    from app.services.notifications import create_notification
    from app.database import fs
    from app.utils.concurrency import conversion_semaphore
    import base64
    import pickle

    lock_owner = f"grading_job:{job_id}"
    lock_acquired = False
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        stale_before = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        locked_exam = await db.exams.find_one_and_update(
            {
                "exam_id": exam_id,
                "$or": [
                    {"processing_state": {"$exists": False}},
                    {"processing_state": "idle"},
                    {"processing_lock_at": {"$lt": stale_before}},
                    {"processing_lock_owner": lock_owner},
                ],
            },
            {
                "$set": {
                    "processing_state": "grading",
                    "processing_lock_at": now_iso,
                    "processing_lock_owner": lock_owner,
                }
            },
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )
        if not locked_exam:
            raise RuntimeError("processing_lock_busy")
        lock_acquired = True

        await db.grading_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        
        submissions = []
        errors = []
        
        logger.info(f"=== BATCH GRADING START === Processing {len(files_data)} files for exam {exam_id} (Job: {job_id})")

        async def _refresh_exam_state() -> dict:
            latest = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
            return latest or exam

        async def _wait_for_question_paper_extraction(current_exam: dict) -> dict:
            if not current_exam:
                return exam
            extraction_processing = bool(current_exam.get("question_paper_processing")) or (
                str(current_exam.get("question_extraction_status", "")).lower() == "processing"
            )
            if not extraction_processing:
                return current_exam

            logger.info(
                "Question extraction still processing for exam %s; waiting up to %ss before grading.",
                exam_id,
                QUESTION_EXTRACTION_WAIT_SECONDS,
            )
            waited = 0
            poll_interval = 3
            latest_exam = current_exam
            while waited < QUESTION_EXTRACTION_WAIT_SECONDS:
                await asyncio.sleep(poll_interval)
                waited += poll_interval
                latest_exam = await _refresh_exam_state()
                still_processing = bool(latest_exam.get("question_paper_processing")) or (
                    str(latest_exam.get("question_extraction_status", "")).lower() == "processing"
                )
                if not still_processing:
                    logger.info("Question extraction finished after %ss; resuming grading.", waited)
                    return latest_exam

            logger.warning(
                "Question extraction still processing after %ss for exam %s; proceeding with current state.",
                QUESTION_EXTRACTION_WAIT_SECONDS,
                exam_id,
            )
            return latest_exam
        
        for idx, file_data in enumerate(files_data):
            filename = file_data["filename"]
            pdf_bytes = file_data["content"]
            
            logger.info(f"[File {idx + 1}/{len(files_data)}] START processing: {filename}")
            try:
                file_size_mb = len(pdf_bytes) / (1024 * 1024)
                if len(pdf_bytes) > 30 * 1024 * 1024:
                    errors.append({"filename": filename, "error": f"File too large ({file_size_mb:.1f}MB). Maximum size is 30MB."})
                    await db.grading_jobs.update_one(
                        {"job_id": job_id},
                        {"$set": {"processed_papers": idx + 1, "failed": len(errors), "errors": errors, "updated_at": datetime.now(timezone.utc).isoformat()}}
                    )
                    continue
                
                try:
                    async with conversion_semaphore:
                        images = await asyncio.to_thread(pdf_to_clean_images, pdf_bytes, 300)
                except Exception as clean_err:
                    logger.warning("300-DPI clean conversion failed, falling back to default converter: %s", clean_err)
                    async with conversion_semaphore:
                        images = await asyncio.to_thread(pdf_to_images, pdf_bytes)
                
                if not images:
                    errors.append({"filename": filename, "error": "Failed to extract images from PDF"})
                    await db.grading_jobs.update_one(
                        {"job_id": job_id},
                        {"$set": {"processed_papers": idx + 1, "failed": len(errors), "errors": errors, "updated_at": datetime.now(timezone.utc).isoformat()}}
                    )
                    continue
                
                # Extract student info
                student_id, student_name = await extract_student_info_from_paper(images, filename)
                
                if not student_id or not student_name:
                    filename_id, filename_name = parse_student_from_filename(filename)
                    if not student_id and filename_id:
                        student_id = filename_id
                    if not student_name and filename_name:
                        student_name = filename_name
                
                if not student_id and not student_name:
                    errors.append({"filename": filename, "error": "Could not extract student ID/name from paper or filename."})
                    continue
                
                if not student_id:
                    student_id = f"AUTO_{uuid.uuid4().hex[:6]}"
                if not student_name:
                    student_name = f"Student {student_id}"

                exam = await _wait_for_question_paper_extraction(await _refresh_exam_state())
                bp_status = str(exam.get("blueprint_status", "pending")).lower()
                if not bool(exam.get("blueprint_locked")) and bp_status != "ready_locked":
                    logger.info("GRADING_BLOCKED_NOT_EXTRACTION exam_id=%s status=%s", exam_id, bp_status)
                    errors.append(
                        {
                            "filename": filename,
                            "student": student_name,
                            "error": "Blueprint is not locked. Lock blueprint before grading papers.",
                        }
                    )
                    await db.grading_jobs.update_one(
                        {"job_id": job_id},
                        {"$set": {"processed_papers": idx + 1, "failed": len(errors), "errors": errors, "updated_at": datetime.now(timezone.utc).isoformat()}}
                    )
                    continue
            
                user_id, error = await get_or_create_student(
                    student_id=student_id, student_name=student_name,
                    batch_id=exam["batch_id"], teacher_id=teacher_id
                )
                
                if error:
                    errors.append({"filename": filename, "student_id": student_id, "error": error})
                    continue
                
                # Get model answer images
                model_answer_imgs = await get_exam_model_answer_images(exam_id)
                
                # Get questions
                questions_from_collection = await db.questions.find({"exam_id": exam_id}, {"_id": 0}).to_list(1000)
                questions_to_grade = questions_from_collection if questions_from_collection else exam.get("questions", [])

                # Guardrail: if the exam has a question paper but only 0/1 extracted questions,
                # force a fresh extraction before grading to avoid single-question grading artifacts.
                if (
                    len(questions_to_grade) <= 1
                    and exam.get("has_question_paper")
                    and not bool(exam.get("blueprint_locked"))
                ):
                    try:
                        logger.warning(
                            "Exam %s currently has %s question(s) despite question paper upload; forcing re-extraction.",
                            exam_id,
                            len(questions_to_grade),
                        )
                        reextract = await auto_extract_questions(
                            exam_id,
                            force=True,
                            use_model_answer_fallback=False,
                        )
                        if reextract.get("success"):
                            exam = await _refresh_exam_state()
                            questions_from_collection = await db.questions.find({"exam_id": exam_id}, {"_id": 0}).to_list(1000)
                            questions_to_grade = questions_from_collection if questions_from_collection else exam.get("questions", [])
                    except Exception as reextract_err:
                        logger.warning("Forced question-paper re-extraction failed for exam %s: %s", exam_id, reextract_err)
                
                if not questions_to_grade:
                    fallback_hint = "No questions available for grading. Upload/extract question paper, then lock blueprint."
                    errors.append({"filename": filename, "student": student_name, "error": fallback_hint})
                    await db.grading_jobs.update_one(
                        {"job_id": job_id},
                        {"$set": {"processed_papers": idx + 1, "failed": len(errors), "errors": errors, "updated_at": datetime.now(timezone.utc).isoformat()}}
                    )
                    continue
                
                # Compute total marks
                derived_total_marks = 0.0
                for q in questions_to_grade:
                    q_max = float(q.get("max_marks") or 0.0)
                    if q_max > 0:
                        derived_total_marks += q_max
                        continue
                    # Fallback only when parent marks are missing.
                    derived_total_marks += sum(float(sq.get("max_marks") or 0.0) for sq in (q.get("sub_questions") or []))
                if derived_total_marks > 0:
                    await db.exams.update_one({"exam_id": exam_id}, {"$set": {"total_marks": derived_total_marks}})

                model_answer_text = await get_exam_model_answer_text(exam_id)
                model_answer_map = await get_exam_model_answer_map(exam_id)
                
                # Fetch subject name for UPSC detection
                subject_name = None
                if exam.get("subject_id"):
                    subject_doc = await db.subjects.find_one({"subject_id": exam["subject_id"]}, {"_id": 0, "name": 1})
                    subject_name = subject_doc.get("name") if subject_doc else None

                scores = await grade_with_ai(
                    images=images, model_answer_images=model_answer_imgs,
                    questions=questions_to_grade,
                    grading_mode=exam.get("grading_mode", "balanced"),
                    total_marks=derived_total_marks if derived_total_marks > 0 else exam.get("total_marks", 100),
                    model_answer_text=model_answer_text,
                    model_answer_map=model_answer_map,
                    subject_name=subject_name,
                    exam_id=exam_id,
                    exam_name=exam.get("exam_name"),
                    exam_type=exam.get("exam_type"),
                )
                packet_meta = getattr(grade_with_ai, "last_packet_meta", {}) or {}
                grading_reference_mode = getattr(grade_with_ai, "last_grading_reference_mode", "rubric_only")
                mapping_status = str(packet_meta.get("mapping_status", "pass") or "pass")
                mapping_needs_review = mapping_status != "pass"
                
                # Generate annotated images (can be globally disabled)
                if DISABLE_ANNOTATIONS:
                    annotated_images = images
                else:
                    try:
                        from app.services.annotation import generate_annotated_images_with_vision_ocr, generate_annotated_images
                        annotated_images = await generate_annotated_images_with_vision_ocr(images, scores, use_vision_ocr=True, dense_red_pen=False)
                    except Exception as ann_error:
                        logger.warning(f"Vision OCR annotation failed, falling back to basic: {ann_error}")
                        try:
                            from app.services.annotation import generate_annotated_images
                            annotated_images = generate_annotated_images(images, scores)
                        except Exception:
                            annotated_images = images  # Fallback to original images
                
                total_score = sum((s.obtained_marks or 0) for s in scores)
                effective_total = derived_total_marks if derived_total_marks > 0 else exam.get("total_marks", 100)
                percentage = (total_score / effective_total) * 100 if effective_total > 0 else 0
                
                submission_id = f"sub_{uuid.uuid4().hex[:8]}"
                score_payload = [s.model_dump() for s in scores]
                normalized = normalize_submission_scores(
                    {
                        "submission_id": submission_id,
                        "question_scores": score_payload,
                        "total_score": total_score,
                        "percentage": round(percentage, 2),
                    },
                    {
                        "questions": questions_to_grade,
                        "total_marks": effective_total,
                    },
                    source="grading_insert",
                )
                # Attach stable question UUIDs when available (AWS pipeline).
                q_uuid_map = {}
                answer_segments = getattr(grade_with_ai, "last_answer_segments", {}) or {}
                for qn, payload in answer_segments.items():
                    if isinstance(qn, int) and isinstance(payload, dict) and payload.get("question_uuid"):
                        q_uuid_map[qn] = payload.get("question_uuid")
                if not q_uuid_map:
                    for q in questions_to_grade:
                        qn = q.get("question_number")
                        q_uuid = q.get("question_uuid")
                        if str(qn).isdigit() and q_uuid:
                            q_uuid_map[int(qn)] = str(q_uuid)
                for qscore in normalized.get("question_scores", []) or []:
                    try:
                        qnum = int(qscore.get("question_number"))
                    except Exception:
                        continue
                    if qnum in q_uuid_map:
                        qscore["question_uuid"] = q_uuid_map[qnum]
                
                # Store in GridFS
                pdf_gridfs_id = None
                images_gridfs_id = None
                annotated_images_gridfs_id = None
                
                try:
                    pdf_gridfs_id = fs.put(pdf_bytes, filename=f"{submission_id}.pdf", submission_id=submission_id)
                    images_data = pickle.dumps(images)
                    images_gridfs_id = fs.put(images_data, filename=f"{submission_id}_images.pkl", submission_id=submission_id)
                    annotated_data = pickle.dumps(annotated_images)
                    annotated_images_gridfs_id = fs.put(annotated_data, filename=f"{submission_id}_annotated.pkl", submission_id=submission_id)
                except Exception as gridfs_err:
                    logger.error(f"GridFS storage error: {gridfs_err}")
                
                submission = {
                    "submission_id": submission_id,
                    "exam_id": exam_id,
                    "student_id": user_id,
                    "student_name": student_name,
                    "file_data": "" if pdf_gridfs_id else base64.b64encode(pdf_bytes).decode(),
                    "pdf_gridfs_id": str(pdf_gridfs_id) if pdf_gridfs_id else None,
                    "images_gridfs_id": str(images_gridfs_id) if images_gridfs_id else None,
                    "annotated_images_gridfs_id": str(annotated_images_gridfs_id) if annotated_images_gridfs_id else None,
                    "file_images": images if not images_gridfs_id else [],
                    "annotated_images": annotated_images if not annotated_images_gridfs_id else [],
                    "total_score": normalized["total_score"],
                    "total_marks": effective_total,
                    "percentage": normalized["percentage"],
                    "question_scores": normalized["question_scores"],
                    "grading_state": "done" if not mapping_needs_review else "blocked",
                    "blueprint_version_used": int(packet_meta.get("blueprint_version_used", exam.get("blueprint_version", 0) or 0) or 0),
                    "grading_contract_version": packet_meta.get("grading_contract_version"),
                    "structure_confidence": float(packet_meta.get("structure_confidence", 0.0) or 0.0),
                    "alignment_confidence": float(packet_meta.get("alignment_confidence", 0.0) or 0.0),
                    "grading_confidence": float(packet_meta.get("grading_confidence", 0.0) or 0.0),
                    "overall_confidence": float(packet_meta.get("overall_confidence", 0.0) or 0.0),
                    "alignment_status": "pass" if not mapping_needs_review else "needs_review",
                    "alignment_coverage": float(packet_meta.get("mapping_coverage", 0.0) or 0.0),
                    "question_coverage_map": packet_meta.get("question_coverage_map", {}),
                    "unmapped_answers": packet_meta.get("unmapped_answers", []),
                    "duplicate_answers": packet_meta.get("duplicate_answers", []),
                    "realign_required": False,
                    "objective_key_flags": packet_meta.get("objective_key_flags", {}),
                    "model_name": packet_meta.get("model_name"),
                    "prompt_version": packet_meta.get("prompt_version"),
                    "pipeline_version": packet_meta.get("pipeline_version"),
                    "grading_reference_mode": grading_reference_mode,
                    "mapping_status": mapping_status,
                    "mapping_confidence": float(packet_meta.get("mapping_confidence", 0.0) or 0.0),
                    "continuity_confidence": float(packet_meta.get("continuity_confidence", 0.0) or 0.0),
                    "mapped_question_ratio": float(packet_meta.get("mapped_question_ratio", 0.0) or 0.0),
                    "mapping_coverage": float(packet_meta.get("mapping_coverage", 0.0) or 0.0),
                    "unresolved_questions": packet_meta.get("unresolved_questions", []),
                    "mapping_fail_reasons": packet_meta.get("mapping_fail_reasons", []),
                    "answer_pages": packet_meta.get("answer_pages", []),
                    "question_page_buckets": packet_meta.get("question_page_buckets", {}),
                    "continuation_merges": packet_meta.get("continuation_merges", []),
                    "anchor_confidence_summary": packet_meta.get("anchor_confidence_summary", {}),
                    "table_confidence_summary": packet_meta.get("table_confidence_summary", {}),
                    "alignment_confidence_summary": packet_meta.get("alignment_confidence_summary", {}),
                    "continuity_confidence_summary": packet_meta.get("continuity_confidence_summary", {}),
                    "orphan_block_count": int(packet_meta.get("orphan_block_count", 0) or 0),
                    "orphan_block_ratio": float(packet_meta.get("orphan_block_ratio", 0.0) or 0.0),
                    "orphan_pages": packet_meta.get("orphan_pages", []),
                    "packets_generated": int(packet_meta.get("packets_generated", 0) or 0),
                    "subpacket_count": int(packet_meta.get("subpacket_count", 0) or 0),
                    "low_confidence_questions": packet_meta.get("low_confidence_questions", []),
                    "consistency_flags": packet_meta.get("consistency_flags", []),
                    "grading_report": packet_meta.get("grading_report", {}),
                    "packet_trace_ref": packet_meta.get("pipeline"),
                    "status": "needs_review" if mapping_needs_review else "ai_graded",
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                
                await db.submissions.insert_one(submission)
                submissions.append({
                    "submission_id": submission_id, "student_id": student_id,
                    "student_name": student_name,
                    "total_score": normalized["total_score"],
                    "percentage": normalized["percentage"],
                })
            
            except Exception as e:
                logger.error(f"Error processing {filename}: {e}")
                errors.append({"filename": filename, "error": str(e)})
            
            # Update progress after each file
            await db.grading_jobs.update_one(
                {"job_id": job_id},
                {"$set": {"processed_papers": idx + 1, "successful": len(submissions), "failed": len(errors), "errors": errors, "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
        
        # Final update
        await db.exams.update_one({"exam_id": exam_id}, {"$set": {"status": "completed"}})
        
        await db.grading_jobs.update_one(
            {"job_id": job_id},
            {"$set": {
                "status": "completed", "processed_papers": len(files_data),
                "successful": len(submissions), "failed": len(errors),
                "submissions": submissions, "errors": errors,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        await create_notification(
            user_id=teacher_id, notification_type="grading_complete",
            title="Grading Complete",
            message=f"Successfully graded {len(submissions)} papers for {exam['exam_name']}",
            link=f"/teacher/review?exam={exam_id}"
        )

    except Exception as e:
        logger.error(f"Critical error in background job {job_id}: {e}")
        await db.grading_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "failed", "error": str(e), "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
    finally:
        if lock_acquired:
            await db.exams.update_one(
                {"exam_id": exam_id, "processing_lock_owner": lock_owner},
                {
                    "$set": {
                        "processing_state": "idle",
                        "processing_lock_at": datetime.now(timezone.utc).isoformat(),
                    },
                    "$unset": {"processing_lock_owner": ""},
                },
            )
