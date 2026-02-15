"""
Grading service - AI-powered answer paper evaluation.
Migrated from server.py grade_with_ai and related functions (lines ~5297-6828, 9157-9205).
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import asyncio
import base64
import io
import json
import re
import hashlib
import uuid

from fastapi import HTTPException
from PIL import Image

from app.database import db
from app.config import logger, get_llm_api_key
from app.models.submission import QuestionScore, SubQuestionScore, AnnotationData
from app.utils.validation import infer_upsc_paper
from app.services.file_processing import correct_all_images_rotation
from app.services.llm import LlmChat, UserMessage, ImageContent
from app.utils.annotation_utils import Annotation, AnnotationType
from app.utils.vision_ocr_service import get_vision_service

# In-memory grading cache
grading_cache = {}


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
    teacher_id: str = None,
    subject_id: str = None,
    exam_id: str = None,
    subject_name: str = None,
    exam_name: str = None,
    exam_type: str = None,
    skip_cache: bool = False
) -> List[QuestionScore]:
    """Grade answer paper using Gemini with GradeSense Master Instruction Set + Teacher's Learned Patterns."""
    
    api_key = get_llm_api_key()
    
    if not api_key:
        raise HTTPException(status_code=500, detail="AI service not configured (Missing API Key)")
    
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
    use_text_based_grading = bool(model_answer_text and len(model_answer_text) > 100)
    
    print(f"\n{'='*70}")
    print(f"[GRADING-START]")
    print(f"  Images: {len(images)} student pages")
    print(f"  Model answer: {len(model_answer_images)} images, {len(model_answer_text)} text chars")
    print(f"  Questions: {len(questions)}")
    print(f"  Use text-based: {use_text_based_grading}")
    print(f"{'='*70}\n")
    
    if use_text_based_grading:
        logger.info(f"Using TEXT-BASED grading (model answer: {len(model_answer_text)} chars)")
        print(f"[GRADING] TEXT-BASED mode - Model answer preview: {model_answer_text[:200]}...")
    else:
        logger.info(f"Using IMAGE-BASED grading (model answer: {len(model_answer_images)} images)")
        print(f"[GRADING] IMAGE-BASED mode - {len(model_answer_images)} model images + {len(images)} student images")
    
    # Create content hash for deterministic grading
    hash_content = "".join(corrected_images).encode() + str(questions).encode() + grading_mode.encode()
    if use_text_based_grading:
        hash_content += model_answer_text.encode()
    else:
        hash_content += "".join(model_answer_images).encode()
    paper_hash = hashlib.sha256(hash_content).hexdigest()
    content_hash = paper_hash[:16]

    # Check cache (Memory)
    if not skip_cache and paper_hash in grading_cache:
        logger.info(f"Cache hit (memory) for paper {paper_hash}")
        return grading_cache[paper_hash]

    # Check cache (Database)
    if not skip_cache:
        try:
            cached_result = await db.grading_results.find_one({"paper_hash": paper_hash})
            if cached_result and "results" in cached_result:
                logger.info(f"Cache hit (db) for paper {paper_hash}")
                results_data = json.loads(cached_result["results"])
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

    
    # UPSC system prompts
    upsc_system_prompt = """# ROLE: Senior UPSC Mains Evaluator (GS & Essay)

## MISSION
You are a veteran evaluator for the UPSC Civil Services Examination. Your task is to grade the student's answer script with uncompromising strictness.

## 1. SCORING CEILING & CALIBRATION
* For 10-Marker Questions: Average: 3.0-4.0, Good: 4.5-5.5, Topper: 6.0-7.0
* For 15-Marker Questions: Average: 4.0-6.0, Good: 6.5-8.0, Topper: 8.5-10.5
* For 20-Marker Case Studies: Average: 8.0-10.0, Topper: 11.0-13.5

## 2. THE "ARC" GRADING FRAMEWORK
* A - ACCURACY (20%): Did the candidate answer the specific directive?
* R - REPRESENTATION (30%): Structural Visibility, Visuals, Format
* C - CONTENT SUBSTANTIATION (50%): Data, Articles, Acts, Committees

## 4. OUTPUT FORMAT (STRICT JSON)
Output ONLY this JSON structure. No preamble.
"""

    gs4_system_prompt = """# ROLE: Senior UPSC Mains Evaluator (Strict Administrative Standard)

## 1. THE "VALUE-ADD" SCORING MATRIX
| Indicator Type | Action |
| Constitutional Basis | +0.5 to +1 Mark |
| Substantiation | +1 Mark (Guaranteed) |
| Real-Life Examples | +1 Mark (Guaranteed) |
| Visual Representation | +0.5 Mark |

## 2. STRICT MARKING BANDS
* Floor (Minimum for Attempt): 1.5 to 2.0 marks
* 10-Marker Max: 6.5-7.0
* 20-Marker Max: 12.0-13.5
"""

    college_system_prompt = """# ROLE: College Exam Evaluator (University Standard)

## MISSION
You are an experienced university evaluator grading exam scripts. Grade fairly based on conceptual accuracy, completeness, and clarity.

## 1. SCORING PRINCIPLES
* Accuracy and relevance are primary
* Partial credit for correct concepts even if incomplete
* Penalize factual errors or misconceptions
* Reward clear structure: definition → explanation → example → conclusion
"""

    # Detect UPSC context
    upsc_paper = infer_upsc_paper(exam_name, subject_name)
    is_upsc = False
    exam_type_norm = str(exam_type or "").lower()
    if exam_type_norm == "upsc":
        is_upsc = True
    elif exam_type_norm == "college":
        is_upsc = False
    else:
        if upsc_paper:
            is_upsc = True
        if subject_name and "upsc" in subject_name.lower():
            is_upsc = True
        if exam_name and "upsc" in exam_name.lower():
            is_upsc = True

    selected_upsc_prompt = upsc_system_prompt
    if is_upsc and upsc_paper != "GS-4":
        selected_upsc_prompt = gs4_system_prompt

    base_prompt = selected_upsc_prompt if is_upsc else college_system_prompt

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
- **QUESTION NOT FOUND**: Use obtained_marks = -1.0

## OUTPUT FORMAT (STRICT)
Return ONLY valid JSON:
{{
  "scores": [
    {{
      "question_number": 1,
      "obtained_marks": 8.5,
      "ai_feedback": "Specific, constructive feedback (20-150 words)",
      "status": "graded|not_attempted|not_found",
      "confidence": 0.0,
      "annotations": [
        {{
          "page_number": 1,
                    "line_id_start": "Q1-L2",
                    "line_id_end": "Q1-L4",
          "annotation_type": "TICK|CROSS|UNDERLINE|COMMENT|BOX",
          "short_label": "2-4 word abbreviation (REQUIRED). Use terse examiner shorthand: 'Good pt', 'Correct defn', 'Wrong date', 'Vague', 'Incomplete', 'Key term missing', 'Nice eg', 'Irrelevant'",
          "sentiment": "positive|negative"
        }}
      ],
      "sub_scores": [
        {{
          "sub_id": "a",
          "obtained_marks": 4.5,
          "ai_feedback": "Feedback for part a",
          "annotations": []
        }}
      ]
    }}
  ],
  "grading_notes": "Overall observations"
}}

### CRITICAL FIELD RULES
1. obtained_marks = -1.0 → question not found
2. obtained_marks = 0.0 → question found but wrong/blank
3. sub_scores required for sub-questions; SUM(sub_scores) = main obtained_marks
4. ai_feedback must be improvement-focused and actionable
5. confidence must be between 0.0 and 1.0
6. **MAX 10 ANNOTATIONS PER PAGE**
7. **IGNORE PRINTED QUESTIONS** - Only annotate handwritten answers
8. **BOX COMMENTS**: 2-4 word abbreviated feedback
9. Use line_id_start/line_id_end from the provided LINE ID MAP (OCR). If single line, set both to the same value.
10. **short_label is REQUIRED for EVERY annotation** — use terse 2-4 word examiner shorthand. TICK: 'Good pt', 'Correct defn', 'Nice eg'. CROSS: 'Wrong', 'Factual error', 'Incorrect'. BOX: 'Incomplete', 'Vague', 'Needs detail'. NEVER repeat the same label on consecutive annotations — if multiple lines share the same reason, use ONE annotation with line_id_start/line_id_end spanning all of them.
11. **NO DUPLICATE ANNOTATIONS** — if the same reason applies to lines Q1-L3 through Q1-L6, create ONE annotation with line_id_start="Q1-L3" and line_id_end="Q1-L6". Do NOT create 4 separate annotations with the same label.

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
            has_line_ref = bool(line_id or line_id_start or line_id_end)
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
                if has_line_ref:
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
                    line_id_start=line_id_start, line_id_end=line_id_end
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
                if has_line_ref:
                    anchor_text = None
                elif _skip_anchor(anchor_text, mapped_type):
                    continue
                normalized.append(AnnotationData(
                    type=mapped_type, x=0, y=0, text=str(label), color=color,
                    size=26, page_index=page_index, anchor_text=anchor_text,
                    line_id=line_id, line_id_start=line_id_start,
                    line_id_end=line_id_end
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

    def build_line_id_context(chunk_imgs: List[str], start_page_num: int, questions: List[dict]) -> str:
        """Build OCR line IDs per question for the current chunk."""
        vision_service = get_vision_service()
        if not vision_service.is_available():
            return ""

        question_numbers = sorted({int(q.get("question_number")) for q in questions if q.get("question_number") is not None})
        patterns = {
            q_num: re.compile(rf"^\s*(?:Q\s*)?{q_num}\s*[\).:-]?\s*", re.IGNORECASE)
            for q_num in question_numbers
        }

        def _group_words_into_lines(words: List[dict], y_threshold: float) -> List[dict]:
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
            for line in lines:
                xs = [i["x1"] for i in line] + [i["x2"] for i in line]
                ys = [i["y1"] for i in line] + [i["y2"] for i in line]
                text = " ".join(i["text"] for i in line).strip()
                line_boxes.append({
                    "text": text,
                    "x1": min(xs), "y1": min(ys),
                    "x2": max(xs), "y2": max(ys)
                })
            return line_boxes

        output_lines = []
        for page_offset, img in enumerate(chunk_imgs):
            page_num = start_page_num + page_offset + 1
            try:
                image_data = base64.b64decode(img)
                with Image.open(io.BytesIO(image_data)) as pil_img:
                    img_height = pil_img.size[1]
            except Exception:
                img_height = 1400

            try:
                ocr_result = vision_service.detect_text_from_base64(img, ["en"])
                words = ocr_result.get("words", [])
            except Exception:
                words = []

            if not words:
                continue

            y_threshold = max(10, int(img_height * 0.012))
            line_boxes = _group_words_into_lines(words, y_threshold)
            if not line_boxes:
                continue

            output_lines.append(f"Page {page_num}:")

            current_q = question_numbers[0] if question_numbers else 0
            counters: Dict[int, int] = {}
            for line in line_boxes:
                text = line.get("text", "").strip()
                if text:
                    for q_num, pattern in patterns.items():
                        if pattern.match(text):
                            current_q = q_num
                            break

                counters[current_q] = counters.get(current_q, 0) + 1
                line_id = f"Q{current_q}-L{counters[current_q]}"
                safe_text = re.sub(r"\s+", " ", text)
                if len(safe_text) > 140:
                    safe_text = safe_text[:137] + "..."
                output_lines.append(f"  {line_id}: {safe_text}")

        return "\n".join(output_lines)

    # UPSC caps enforcement
    def enforce_upsc_caps(scores: List[QuestionScore]) -> List[QuestionScore]:
        if grading_mode != "strict":
            return scores
        q_max_map = {q.get("question_number"): float(q.get("max_marks") or 0) for q in questions}
        for s in scores:
            q_max = q_max_map.get(s.question_number, 0)
            obtained = s.obtained_marks if s.obtained_marks is not None else 0
            if q_max > 0:
                half = 0.5 * q_max
                cap = max(0.0, half - 1.0)
                if obtained > cap:
                    s.obtained_marks = cap
                elif s.obtained_marks is None:
                    s.obtained_marks = obtained
            if s.sub_scores:
                for sub in s.sub_scores:
                    sub_max = getattr(sub, "max_marks", None)
                    sub_obtained = getattr(sub, "obtained_marks", None)
                    sub_max_val = float(sub_max or 0)
                    sub_obtained_val = float(sub_obtained or 0)
                    if sub_max_val > 0:
                        sub_half = 0.5 * sub_max_val
                        sub_cap = max(0.0, sub_half - 1.0)
                        if sub_obtained_val > sub_cap:
                            setattr(sub, "obtained_marks", sub_cap)
                        elif sub_obtained is None:
                            setattr(sub, "obtained_marks", sub_obtained_val)
        return scores

    # Process chunk helper
    async def process_chunk(chunk_imgs, chunk_idx, total_chunks, start_page_num):
        print(f"\n{'='*70}")
        print(f"[CHUNK-{chunk_idx+1}] === STARTING CHUNK PROCESSING ===")
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
        if total_chunks > 1:
            partial_instruction = f"""
**PARTIAL SUBMISSION NOTICE**:
This is PART {chunk_idx+1} of {total_chunks} of the student's answer (Pages {start_page_num+1} to {start_page_num+len(chunk_imgs)}).
- Grade ONLY the questions visible in this part.
- If a question is completely missing, return -1.0 for 'obtained_marks'.
- You MUST still return a score entry for EVERY question; use -1.0 for questions not seen.
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

        line_id_context = build_line_id_context(chunk_imgs, start_page_num, questions)
        line_id_section = ""
        if line_id_context:
            line_id_section = f"\n\n## LINE ID MAP (OCR)\n{line_id_context}\n"
            print(f"\n{'='*70}")
            print(f"[LINE-ID-SYSTEM] Generated Line IDs for Chunk {chunk_idx+1}:")
            print(line_id_context)
            print(f"{'='*70}\n")
        
        # Build the actual prompt based on grading type
        if use_text_based_grading:
            prompt_text = f"""# GRADING TASK {f'(Part {chunk_idx+1}/{total_chunks})' if total_chunks > 1 else ''}

## MODEL ANSWER REFERENCE (Pre-Extracted Text)
--- MODEL ANSWER START ---
{model_answer_text}
--- MODEL ANSWER END ---

## STUDENT PAPER EVALUATION
**Questions to Grade:**
{questions_text}

**Images Provided:** {len(chunk_imgs)} pages of STUDENT'S ANSWER PAPER (Pages {start_page_num+1}-{start_page_num+len(chunk_imgs)})
{partial_instruction}
{learned_patterns_section}
{line_id_section}

## GRADING MODE: {grading_mode.upper()}
{grading_instruction}

## CRITICAL REQUIREMENTS:
1. CONSISTENCY IS SACRED: Same answer = Same score ALWAYS
2. MODEL ANSWER IS REFERENCE
3. PRECISE SCORING: Use decimals (e.g., 8.5, 7.25)
4. CALCULATION VERIFICATION for mathematical problems
5. Do NOT default to half marks
6. FEEDBACK QUALITY: Constructive, specific
7. COMPLETE EVALUATION: Grade ALL {len(questions)} questions
8. SUB-QUESTION GRADING: Grade each sub-part INDIVIDUALLY
9. HANDLE ROTATION: Read sideways text

Return valid JSON only."""

        elif model_answer_images:
            prompt_text = f"""# GRADING TASK {f'(Part {chunk_idx+1}/{total_chunks})' if total_chunks > 1 else ''}

## PHASE 1: PRE-GRADING ANALYSIS
Analyze the MODEL ANSWER thoroughly first.

## PHASE 2: STUDENT PAPER EVALUATION
**Questions to Grade:**
{questions_text}

**Image Layout:**
- First {model_images_included} image(s): MODEL ANSWER
- Next {len(chunk_imgs)} images: STUDENT'S ANSWER PAPER
{partial_instruction}
{line_id_section}

## GRADING MODE: {grading_mode.upper()}
{grading_instruction}

## CRITICAL REQUIREMENTS:
1. CONSISTENCY IS SACRED
2. MODEL ANSWER IS REFERENCE
3. PRECISE SCORING: Use decimals
4. Do NOT default to half marks
5. FEEDBACK QUALITY: Constructive, specific
6. COMPLETE EVALUATION: Grade ALL {len(questions)} questions
7. SUB-QUESTION GRADING: Grade each sub-part INDIVIDUALLY
8. ANSWER CONTINUATION: Answers may continue on later pages
9. MANDATORY OUTPUT: Return score for EVERY question

Return valid JSON only."""
        else:
            prompt_text = f"""# GRADING TASK (WITHOUT MODEL ANSWER) {f'(Part {chunk_idx+1}/{total_chunks})' if total_chunks > 1 else ''}

No Model Answer Provided. Grade based on rubrics and subject knowledge.

**Questions to Grade:**
{questions_text}

**Images:** STUDENT'S ANSWER PAPER (Pages {start_page_num+1}-{start_page_num+len(chunk_imgs)})
{partial_instruction}
{line_id_section}

## GRADING MODE: {grading_mode.upper()}
{grading_instruction}

## CRITICAL REQUIREMENTS:
1. RUBRIC-BASED: Use provided rubrics as primary reference
2. PRECISE SCORING: Use decimals
3. CONSERVATIVE FLAGGING: Flag uncertain gradings
4. SUB-QUESTION GRADING: Grade each sub-part INDIVIDUALLY

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
                try:
                    res = json.loads(resp_text)
                    scores = res.get("scores", [])
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
                        return res.get("scores", [])
                    except json.JSONDecodeError:
                        pass
                
                # Strategy 3: Find JSON in response
                json_match = re.search(r'\{[^{}]*"scores"[^{}]*\[[^\]]*\][^{}]*\}', resp_text, re.DOTALL)
                if json_match:
                    try:
                        res = json.loads(json_match.group())
                        return res.get("scores", [])
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


    # CHUNKED PROCESSING LOGIC
    CHUNK_SIZE = 10
    OVERLAP = 1
    total_student_pages = len(images)
    
    chunks = []
    if total_student_pages <= 10:
        chunks.append((0, images))
    else:
        for i in range(0, total_student_pages, CHUNK_SIZE):
            start_idx = max(0, i - OVERLAP) if i > 0 else 0
            end_idx = min(total_student_pages, i + CHUNK_SIZE)
            chunk = images[start_idx:end_idx]
            if chunk:
                chunks.append((start_idx, chunk))
            if i + CHUNK_SIZE >= total_student_pages:
                break
    
    logger.info(f"Processing student paper in {len(chunks)} chunk(s)")
    logger.info(f"Questions to grade: {[q['question_number'] for q in questions]}")

    # Process all chunks
    all_chunk_results = []
    for idx, (start_idx, chunk_imgs) in enumerate(chunks):
        print(f"\n[GRADING-PROGRESS] Processing chunk {idx+1}/{len(chunks)}...")
        chunk_scores_data = await process_chunk(chunk_imgs, idx, len(chunks), start_idx)
        print(f"[GRADING-PROGRESS] Chunk {idx+1} returned {len(chunk_scores_data)} question scores")
        all_chunk_results.append(chunk_scores_data)

    # Deterministic Aggregation - Use HIGHEST valid score from any chunk
    final_scores = []

    for q in questions:
        q_num = q["question_number"]
        best_score_data = None
        best_score_value = -1.0

        for chunk_result in all_chunk_results:
            score_data = next((s for s in chunk_result if s["question_number"] == q_num), None)
            if score_data:
                obtained = score_data.get("obtained_marks", -1.0)
                if (best_score_value < 0 and obtained >= 0) or (obtained > best_score_value):
                    best_score_data = score_data
                    best_score_value = obtained

        if not best_score_data or best_score_value < 0:
            best_score_data = {
                "question_number": q_num,
                "obtained_marks": -1.0,
                "ai_feedback": "Question not found in any page (or grading failed)",
                "sub_scores": []
            }

        # Process status
        status = "graded"
        obtained_for_status = best_score_data.get("obtained_marks")
        obtained_for_status = obtained_for_status if obtained_for_status is not None else -1.0
        if obtained_for_status < 0:
            status = "not_found"
            best_score_data["obtained_marks"] = 0.0
        elif best_score_data.get("obtained_marks") == 0 and "blank" in best_score_data.get("ai_feedback", "").lower():
            status = "not_attempted"
            
        # Handle sub-scores
        final_sub_scores = []
        if q.get("sub_questions"):
            current_subs = best_score_data.get("sub_scores", [])
            current_sub_map = {s["sub_id"]: s for s in current_subs}

            for sq in q["sub_questions"]:
                sq_id = sq["sub_id"]
                best_sq_data = current_sub_map.get(sq_id)
                best_sq_marks = best_sq_data.get("obtained_marks", -1.0) if best_sq_data else -1.0
                
                for chunk_result in all_chunk_results:
                    q_score_in_chunk = next((s for s in chunk_result if s["question_number"] == q_num), None)
                    if q_score_in_chunk:
                        chunk_subs = q_score_in_chunk.get("sub_scores", [])
                        sq_in_chunk = next((s for s in chunk_subs if s["sub_id"] == sq_id), None)
                        if sq_in_chunk:
                            sq_marks_in_chunk = sq_in_chunk.get("obtained_marks", -1.0)
                            if sq_marks_in_chunk > best_sq_marks:
                                best_sq_data = sq_in_chunk
                                best_sq_marks = sq_marks_in_chunk
                
                if best_sq_data and best_sq_marks >= 0:
                    sq_annotations = best_sq_data.get("annotations", [])
                    annotations_list = normalize_ai_annotations(sq_annotations)
                    safe_sq_marks = best_sq_marks if best_sq_marks is not None else 0.0
                    safe_sq_max = sq.get("max_marks") if sq.get("max_marks") is not None else 0.0
                    final_sub_scores.append(SubQuestionScore(
                        sub_id=sq["sub_id"], max_marks=safe_sq_max,
                        obtained_marks=min(safe_sq_marks, safe_sq_max),
                        ai_feedback=best_sq_data.get("ai_feedback", ""),
                        annotations=annotations_list
                    ))
                else:
                    final_sub_scores.append(SubQuestionScore(
                        sub_id=sq["sub_id"], max_marks=sq["max_marks"],
                        obtained_marks=0.0, ai_feedback="Not attempted/found"
                    ))
        
        # For questions with sub-questions, obtained_marks = sum of sub-scores
        if final_sub_scores:
            question_obtained_marks = sum(s.obtained_marks for s in final_sub_scores)
        else:
            question_obtained_marks = best_score_data.get("obtained_marks")
            if question_obtained_marks is None:
                question_obtained_marks = 0.0
        
        # Extract question-level annotations
        q_annotations = best_score_data.get("annotations", [])
        annotations_list = normalize_ai_annotations(q_annotations)
        if not annotations_list and status == "graded":
            annotations_list = [
                AnnotationData(
                    type=AnnotationType.COMMENT, x=0, y=0, text="Revise",
                    color="red", size=18, page_index=-1
                )
            ]

        qs_obj = QuestionScore(
            question_number=q_num,
            max_marks=q["max_marks"],
            obtained_marks=min(question_obtained_marks, q["max_marks"]),
            ai_feedback=best_score_data["ai_feedback"],
            sub_scores=[s.model_dump() for s in final_sub_scores],
            question_text=q.get("question_text") or q.get("rubric"),
            status=status,
            annotations=annotations_list
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
    final_scores = enforce_upsc_caps(final_scores)

    # Store in Cache and DB
    try:
        grading_cache[paper_hash] = final_scores
        results_json = json.dumps([s.model_dump() for s in final_scores])
        await db.grading_results.update_one(
            {"paper_hash": paper_hash},
            {"$set": {
                "paper_hash": paper_hash,
                "results": results_json,
                "created_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving grading cache: {e}")

    return final_scores


# ============== BACKGROUND GRADING JOB ==============

async def process_grading_job_in_background(job_id: str, exam_id: str, files_data: List[dict], exam: dict, teacher_id: str):
    """Background task to process papers one by one."""
    # Lazy imports to avoid circular dependencies
    from app.services.gridfs_helpers import get_exam_model_answer_images
    from app.services.extraction import extract_question_structure_from_paper, get_exam_model_answer_text
    from app.services.student_detection import extract_student_info_from_paper, parse_student_from_filename, get_or_create_student
    from app.services.file_processing import pdf_to_images
    from app.services.notifications import create_notification
    from app.database import fs
    from app.utils.concurrency import conversion_semaphore
    import base64
    import pickle

    try:
        await db.grading_jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": "processing", "updated_at": datetime.now(timezone.utc).isoformat()}}
        )
        
        submissions = []
        errors = []
        
        logger.info(f"=== BATCH GRADING START === Processing {len(files_data)} files for exam {exam_id} (Job: {job_id})")
        
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
                
                # Auto-extract if no questions
                if not questions_to_grade:
                    try:
                        extracted_questions = await extract_question_structure_from_paper(paper_images=images, paper_type="answer_sheet")
                        if extracted_questions:
                            for q in extracted_questions:
                                q["exam_id"] = exam_id
                                q["extracted_from"] = "student_answer_sheet"
                                q["extracted_at"] = datetime.now(timezone.utc).isoformat()
                            await db.questions.insert_many(extracted_questions)
                            await db.exams.update_one({"exam_id": exam_id}, {"$set": {"questions": extracted_questions, "extraction_source": "student_answer_sheet"}})
                            questions_to_grade = extracted_questions
                        else:
                            raise Exception("No questions could be extracted")
                    except Exception as extract_err:
                        errors.append({"filename": filename, "student": student_name, "error": f"Auto-extraction failed: {str(extract_err)}"})
                        await db.grading_jobs.update_one(
                            {"job_id": job_id},
                            {"$set": {"processed_papers": idx + 1, "failed": len(errors), "errors": errors, "updated_at": datetime.now(timezone.utc).isoformat()}}
                        )
                        continue

                # Re-extract if suspiciously low question count
                if len(questions_to_grade) <= 1 and len(images) >= 2:
                    try:
                        re_extracted = await extract_question_structure_from_paper(paper_images=images, paper_type="answer_sheet")
                        if re_extracted and len(re_extracted) > len(questions_to_grade):
                            for q in re_extracted:
                                q["exam_id"] = exam_id
                                q["extracted_from"] = "student_answer_sheet"
                                q["extracted_at"] = datetime.now(timezone.utc).isoformat()
                            await db.questions.delete_many({"exam_id": exam_id})
                            await db.questions.insert_many(re_extracted)
                            await db.exams.update_one({"exam_id": exam_id}, {"$set": {"questions": re_extracted, "extraction_source": "student_answer_sheet"}})
                            questions_to_grade = re_extracted
                    except Exception:
                        pass
                
                if not questions_to_grade:
                    errors.append({"filename": filename, "student": student_name, "error": "No questions available for grading"})
                    await db.grading_jobs.update_one(
                        {"job_id": job_id},
                        {"$set": {"processed_papers": idx + 1, "failed": len(errors), "errors": errors, "updated_at": datetime.now(timezone.utc).isoformat()}}
                    )
                    continue
                
                # Compute total marks
                derived_total_marks = 0.0
                for q in questions_to_grade:
                    if q.get("sub_questions"):
                        derived_total_marks += sum(float(sq.get("max_marks") or 0) for sq in q.get("sub_questions", []))
                    else:
                        derived_total_marks += float(q.get("max_marks") or 0)
                if derived_total_marks > 0:
                    await db.exams.update_one({"exam_id": exam_id}, {"$set": {"total_marks": derived_total_marks}})

                model_answer_text = await get_exam_model_answer_text(exam_id)
                
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
                    subject_name=subject_name, exam_name=exam.get("exam_name")
                )
                
                # Generate annotated images
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
                
                total_score = sum(s.obtained_marks for s in scores)
                effective_total = derived_total_marks if derived_total_marks > 0 else exam.get("total_marks", 100)
                percentage = (total_score / effective_total) * 100 if effective_total > 0 else 0
                
                submission_id = f"sub_{uuid.uuid4().hex[:8]}"
                
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
                    "total_score": total_score,
                    "total_marks": effective_total,
                    "percentage": round(percentage, 2),
                    "question_scores": [s.model_dump() for s in scores],
                    "status": "ai_graded",
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                
                await db.submissions.insert_one(submission)
                submissions.append({
                    "submission_id": submission_id, "student_id": student_id,
                    "student_name": student_name, "total_score": total_score, "percentage": percentage
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
