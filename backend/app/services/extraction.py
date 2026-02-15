"""
Question extraction and model answer processing services.
Migrated from server.py extraction functions (lines ~202-397, 4266-5296).
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import asyncio
import json
import re
import uuid
import inspect

import google.generativeai as genai

from app.database import db
from app.config import logger, get_llm_api_key
from app.services.gridfs_helpers import get_exam_model_answer_images, get_exam_question_paper_images
from app.utils.hashing import get_model_answer_hash
from app.services.llm import LlmChat, UserMessage, ImageContent

# In-memory cache for model answer extraction results
model_answer_cache = {}


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
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=system_message if system_message else None
    )
    return model.start_chat(history=[])


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


async def extract_model_answer_content(
    model_answer_images: List[str],
    questions: List[dict]
) -> str:
    """
    Extract detailed answer content from model answer images as structured text.
    This is done ONCE during upload and stored for use during grading.
    """
    api_key = get_llm_api_key()
    if not api_key:
        logger.error("No API key for model answer content extraction")
        return ""
    
    if not model_answer_images:
        return ""
    
    try:
        # Build questions context
        questions_context = ""
        for q in questions:
            q_num = q.get("question_number", "?")
            q_marks = q.get("total_marks", 0)
            questions_context += f"- Question {q_num} ({q_marks} marks)\n"
            for sq in q.get("sub_questions", []):
                sq_id = sq.get("sub_id", "?")
                sq_marks = sq.get("marks", 0)
                questions_context += f"  - Part {sq_id} ({sq_marks} marks)\n"
        
        # Process in chunks for large model answers
        CHUNK_SIZE = 15  # Process 15 pages at a time for stability
        all_extracted_content = []
        
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

Output Format:
---
QUESTION [number]:
[Complete model answer text]

KEY POINTS:
- [Key point 1]
- [Key point 2]
---

Be thorough - extract EVERY detail useful for grading."""
            ).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)
            
            image_contents = [ImageContent(image_base64=img) for img in chunk_images]
            
            prompt = f"""Extract ALL model answer content from pages {chunk_start + 1} to {chunk_end}.

Questions in this exam:
{questions_context}

Extract complete answers for ALL questions visible on these pages."""

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
                        # Extract text from Gemini response object
                        response_text = response.text if hasattr(response, 'text') else str(response)
                        logger.info(f"[EXTRACT-MA-CHUNK] Extracted {len(response_text)} chars from pages {chunk_start + 1}-{chunk_end}")
                        all_extracted_content.append(f"=== PAGES {chunk_start + 1}-{chunk_end} ===\n{response_text}")
                        break
                except Exception as e:
                    logger.error(f"Error extracting content chunk: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5 * (attempt + 1))
        
        full_content = "\n\n".join(all_extracted_content)
        logger.info(f"Extracted model answer content: {len(full_content)} chars from {len(model_answer_images)} pages")
        return full_content
        
    except Exception as e:
        logger.error(f"Error in extract_model_answer_content: {e}")
        return ""


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

    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"extract_struct_{uuid.uuid4().hex[:8]}",
            system_message=f"""You are an expert at analyzing exam {paper_type.replace('_', ' ')}s and extracting COMPLETE question structure.

**CRITICAL REQUIREMENTS - READ CAREFULLY:**
1. **EXTRACT EVERY SINGLE QUESTION** - Scan through ALL pages carefully
2. If the paper has 10 questions (Q1 through Q10), your JSON array MUST have 10 objects
3. Do NOT stop early - continue until you've processed all pages
4. Preserve EXACT question numbers from the paper (1, 2, 3, ..., 10, etc.)
5. Include ALL sub-questions with proper IDs (a, b, c OR i, ii, iii)
6. Extract marks accurately for each question/sub-question
7. For questions without sub-parts, put the full question text in "rubric"

**BEFORE RETURNING - VALIDATE:**
✓ Did I scan ALL pages provided?
✓ Did I extract EVERY question I saw?
✓ Are all question numbers present (no gaps like 1,2,3,5,6...)?
✓ Do I have the correct total count?

**ANSWER SHEET SPECIAL CASE (IMPORTANT):**
- If this is an **answer sheet**, questions may be embedded in the student's responses.
- **Infer question numbers and sub-parts** from headings like "Q1", "1(a)", "Q2 (b)", "Part (i)", etc.
- If full question text is missing, **use the student's answer context** as the rubric and keep the question number accurate.
- Still extract **ALL** questions you can identify by number—even if text is partial.

**COMMON MISTAKE TO AVOID:**
❌ Do NOT return just the first question
❌ Do NOT stop after a few questions
✓ Process the ENTIRE document

Return a JSON array where EACH question has this exact structure:
[
  {{
    "question_number": 1,
    "max_marks": 15,
    "rubric": "Full question text including all parts",
    "question_text": "Q1: Brief identifier",
    "is_optional": false,
    "optional_group": null,
    "required_count": null,
    "sub_questions": [
      {{
        "sub_id": "a",
        "max_marks": 2.5,
        "rubric": "Part (a) complete text here"
      }},
      {{
        "sub_id": "b",
        "max_marks": 2.5,
        "rubric": "Part (b) complete text here"
      }},
      {{
        "sub_id": "c",
        "max_marks": 3,
        "rubric": "Part (c) complete text here"
      }}
    ]
  }},
  {{
    "question_number": 2,
    "max_marks": 15,
    ...
  }},
  ... (continue for ALL questions)
]

**CRITICAL: Return ONLY valid JSON array. Every question must have all fields. Extract ALL questions, not just first one!**"""
).with_model("gemini", "gemini-2.5-flash").with_params(temperature=0)
        
        # Create image contents - CHUNK if too many pages
        CHUNK_SIZE = 15  # Process 15 pages at a time to avoid timeouts
        all_images = paper_images
        
        if len(all_images) > CHUNK_SIZE:
            logger.info(f"Large document ({len(all_images)} pages) - processing in chunks of {CHUNK_SIZE}")
            print(f"\n[EXTRACT-CHUNK] Large document with {len(all_images)} pages - will chunk into {CHUNK_SIZE}px per chunk")
            all_extracted_questions = []
            
            for chunk_start in range(0, len(all_images), CHUNK_SIZE):
                chunk_end = min(chunk_start + CHUNK_SIZE, len(all_images))
                chunk_images = all_images[chunk_start:chunk_end]
                
                logger.info(f"Processing pages {chunk_start+1}-{chunk_end} ({len(chunk_images)} pages)")
                print(f"[EXTRACT-CHUNK] Chunk {chunk_start//CHUNK_SIZE + 1}: Pages {chunk_start+1}-{chunk_end}")
                
                image_contents = [ImageContent(image_base64=img) for img in chunk_images]
                
                prompt = f"""Analyze this {paper_type.replace('_', ' ')} (Pages {chunk_start+1}-{chunk_end}) and extract the question structure.

Instructions:
- Identify ALL questions visible in these pages
- For each question, identify ALL sub-parts with their marks
- Detect the numbering style (a,b,c vs i,ii,iii)
- Extract marks for each part
- If a question spans multiple chunks, extract what's visible here
- **IMPORTANT: Include the full question number (e.g., "1", "2", "10", not just "Q1")**
- Return questions in order of their numbers

Return ONLY the JSON array of questions."""
        
                chunk_message = UserMessage(text=prompt, file_contents=image_contents)
                
                # Try to extract this chunk
                max_retries = 2  # Fewer retries per chunk
                retry_delay = 5
                chunk_questions = []
                
                for attempt in range(max_retries):
                    try:
                        logger.info(f"Chunk {chunk_start+1}-{chunk_end} extraction attempt {attempt + 1}/{max_retries}")
                        ai_response = await chat.send_message(chunk_message)
                        
                        response_text = ai_response.strip()
                        
                        # Try parsing
                        try:
                            result = json.loads(response_text)
                            if isinstance(result, list):
                                chunk_questions = result
                                break
                            elif isinstance(result, dict) and "questions" in result:
                                chunk_questions = result["questions"]
                                break
                        except:
                            pass
                        
                        # Remove code blocks
                        if response_text.startswith("```"):
                            response_text = response_text.split("```")[1]
                            if response_text.startswith("json"):
                                response_text = response_text[4:]
                            response_text = response_text.strip()
                            try:
                                result = json.loads(response_text)
                                if isinstance(result, list):
                                    chunk_questions = result
                                    break
                                elif isinstance(result, dict) and "questions" in result:
                                    chunk_questions = result["questions"]
                                    break
                            except:
                                pass
                        
                        logger.warning(f"Failed to parse chunk {chunk_start+1}-{chunk_end} (attempt {attempt + 1})")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            
                    except Exception as e:
                        logger.error(f"Error extracting chunk {chunk_start+1}-{chunk_end} (attempt {attempt + 1}): {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                
                if chunk_questions:
                    q_nums = [q.get('question_number') for q in chunk_questions]
                    logger.info(f"✅ Extracted {len(chunk_questions)} questions from pages {chunk_start+1}-{chunk_end}: Q{q_nums}")
                    print(f"[EXTRACT-CHUNK] ✅ Got {len(chunk_questions)} questions from pages {chunk_start+1}-{chunk_end}: Q{q_nums}")
                    all_extracted_questions.extend(chunk_questions)
                else:
                    logger.warning(f"⚠️ Failed to extract questions from pages {chunk_start+1}-{chunk_end}")
                    print(f"[EXTRACT-CHUNK] ⚠️  No questions extracted from pages {chunk_start+1}-{chunk_end}")
            
            # After all chunks, verify we got all questions and remove duplicates
            print(f"\n[EXTRACT-FINAL] Processed all chunks - merging results...")
            logger.info(f"✅ Total: Extracted {len(all_extracted_questions)} questions from {len(all_images)} pages (chunked)")
            
            # Sort by question number and remove duplicates (keep first occurrence)
            seen_q_nums = set()
            unique_questions = []
            for q in all_extracted_questions:
                q_num = q.get('question_number')
                if q_num not in seen_q_nums:
                    unique_questions.append(q)
                    seen_q_nums.add(q_num)
                else:
                    logger.info(f"Skipping duplicate question {q_num}")
                    print(f"[EXTRACT-DEDUP] Removed duplicate Q{q_num}")
            
            final_q_nums = [q.get('question_number') for q in unique_questions]
            print(f"[EXTRACT-FINAL] Total {len(unique_questions)} unique questions after deduplication: Q{final_q_nums}")
            logger.info(f"Final questions after dedup: Q{final_q_nums}")
            
            # Validate: check for missing questions
            if final_q_nums and all(isinstance(q, (int, float)) or isinstance(q, str) for q in final_q_nums):
                try:
                    numeric_q_nums = [int(q) if isinstance(q, int) else int(str(q)) for q in final_q_nums if q]
                    max_q = max(numeric_q_nums) if numeric_q_nums else 0
                    expected_set = set(range(1, max_q + 1))
                    actual_set = set(numeric_q_nums)
                    missing = expected_set - actual_set
                    if missing:
                        print(f"[EXTRACT-FINAL] ⚠️ WARNING: Missing questions Q{sorted(missing)}")
                        logger.warning(f"Missing questions in extraction: Q{sorted(missing)}")
                    else:
                        print(f"[EXTRACT-FINAL] ✅ Complete: All questions Q1 to Q{max_q} present")
                except:
                    pass
            
            return normalize_extracted_questions(unique_questions)
        else:
            # Small document - process all at once
            image_contents = [ImageContent(image_base64=img) for img in paper_images]
            logger.info(f"Extracting complete question structure from {len(image_contents)} pages ({paper_type})")
        
            prompt = f"""Analyze this {paper_type.replace('_', ' ')} (ALL {len(paper_images)} pages) and extract the COMPLETE question structure.

**CRITICAL INSTRUCTIONS:**
- Scan through ALL {len(paper_images)} pages carefully
- Extract EVERY question you find (Q1, Q2, Q3, ... Q10, etc.)
- Do NOT stop early - process the ENTIRE document
- For each question, identify ALL sub-parts (a, b, c, etc.) with their marks
- Detect the numbering style (a,b,c vs i,ii,iii)
- Extract marks accurately for each part

**BEFORE RETURNING - SELF CHECK:**
✓ Did I look at all {len(paper_images)} pages?
✓ Did I extract EVERY question I saw?
✓ Are my question numbers sequential (no gaps)?

Return ONLY the JSON array of ALL questions (not just the first one!)."""
        
        user_message = UserMessage(text=prompt, file_contents=image_contents)
        
        # Retry logic
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Structure extraction attempt {attempt + 1}/{max_retries}")
                ai_response = await ai_call_with_timeout(
                    chat,
                    user_message,
                    timeout_seconds=90,
                    operation_name=f"Structure extraction attempt {attempt+1}"
                )
                
                # Robust JSON parsing
                # Extract text from Gemini response object
                response_text_raw = ai_response.text if hasattr(ai_response, 'text') else str(ai_response)
                response_text = response_text_raw.strip()
                
                # Strategy 1: Direct parse
                try:
                    result = json.loads(response_text)
                    if isinstance(result, list):
                        logger.info(f"✅ Extracted structure for {len(result)} questions")
                        return normalize_extracted_questions(result)
                    elif isinstance(result, dict) and "questions" in result:
                        logger.info(f"✅ Extracted structure for {len(result['questions'])} questions")
                        return normalize_extracted_questions(result["questions"])
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
                        if isinstance(result, list):
                            logger.info(f"✅ Extracted structure for {len(result)} questions (code block)")
                            return normalize_extracted_questions(result)
                        elif isinstance(result, dict) and "questions" in result:
                            return normalize_extracted_questions(result["questions"])
                    except json.JSONDecodeError:
                        pass
                
                # Strategy 3: Find JSON array in text
                json_match = re.search(r'\[\s*\{.*?\}\s*\]', response_text, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                        logger.info(f"✅ Extracted structure for {len(result)} questions (pattern match)")
                        return normalize_extracted_questions(result)
                    except json.JSONDecodeError:
                        pass
                
                # All strategies failed
                logger.warning(f"Failed to parse structure JSON (attempt {attempt + 1}). Response preview: {response_text[:200]}")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying structure extraction in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"All JSON parsing strategies failed after {max_retries} attempts")
                    return []
                
            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Error during structure extraction attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1 and ("502" in error_str or "503" in error_str or "timeout" in error_str or "rate limit" in error_str):
                    wait_time = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying structure extraction in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    if attempt >= max_retries - 1:
                        logger.error(f"Structure extraction failed after {max_retries} attempts")
                    raise e
        
        return []
        
    except Exception as e:
        logger.error(f"Error extracting question structure: {e}")
        return []


# ============== AUTO EXTRACT QUESTIONS ==============

async def auto_extract_questions(exam_id: str, force: bool = False) -> Dict[str, Any]:
    """
    Auto-extract COMPLETE question structure from question paper (priority) or model answer.
    
    Priority:
    1. Question Paper (if exists)
    2. Model Answer (if exists)

    If 'force' is True, re-extraction is performed even if already extracted from the target source.
    """
    try:
        # Get exam
        exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0})
        if not exam:
            logger.error(f"Auto-extraction failed: Exam {exam_id} not found")
            return {"success": False, "message": "Exam not found"}

        # Check available sources
        qp_imgs = await get_exam_question_paper_images(exam_id)
        ma_imgs = await get_exam_model_answer_images(exam_id)

        target_source = None
        images_to_use = []

        if qp_imgs:
            target_source = "question_paper"
            images_to_use = qp_imgs
        elif ma_imgs:
            target_source = "model_answer"
            images_to_use = ma_imgs
        else:
            return {"success": False, "message": "No documents available for extraction"}

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
        extracted_questions = await extract_question_structure_from_paper(
            images_to_use,
            paper_type=target_source
        )

        if not extracted_questions:
            logger.warning(f"Structure extraction returned no questions for {exam_id} from {target_source}")
            return {"success": False, "message": f"Failed to extract question structure from {target_source.replace('_', ' ')}"}

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

        # Update total marks dynamically based on extracted questions
        try:
            total_marks = 0.0
            for q in extracted_questions:
                if q.get("sub_questions"):
                    total_marks += sum(float(sq.get("max_marks") or 0) for sq in q.get("sub_questions", []))
                else:
                    total_marks += float(q.get("max_marks") or 0)
            if total_marks > 0:
                await db.exams.update_one(
                    {"exam_id": exam_id},
                    {"$set": {"total_marks": total_marks}}
                )
                logger.info(f"Updated exam total_marks to {total_marks}")
        except Exception as tm_err:
            logger.warning(f"Failed to update total_marks: {tm_err}")
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
            required_count = group_data["required_count"]
            
            if required_count > 0 and len(questions) > 0:
                marks_per_question = questions[0].get("max_marks", 0)
                group_effective_marks = marks_per_question * min(required_count, len(questions))
                total_marks += group_effective_marks
                logger.info(f"Optional group '{group_id}': {len(questions)} questions, need {required_count}, contributing {group_effective_marks} marks")
            else:
                for q in questions:
                    total_marks += q.get("max_marks", 0)

        logger.info(f"Calculated total marks from extraction: {total_marks} (including optional question handling)")

        # Preserve user's original total_marks if it was explicitly set during exam creation
        user_total_marks = exam.get("total_marks", 100)
        
        if user_total_marks and user_total_marks != 100:
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
                max_q_num = max([int(n) if isinstance(n, int) else int(n.replace('Q', '')) for n in q_nums if n])
                expected_q_nums = set(range(1, max_q_num + 1))
                actual_q_nums = set([int(n) if isinstance(n, int) else int(n.replace('Q', '')) for n in q_nums if n])
                missing_q_nums = expected_q_nums - actual_q_nums
                
                if missing_q_nums:
                    print(f"[EXTRACTION-WARNING] ⚠️ MISSING QUESTIONS: {sorted(missing_q_nums)}")
                    logger.warning(f"Missing questions: {sorted(missing_q_nums)}")
                else:
                    print(f"[EXTRACTION-OK] ✅ All questions Q1 to Q{max_q_num} present")
                    logger.info(f"✅ All questions Q1 to Q{max_q_num} extracted correctly")

        # STEP 4: Update exam document with questions array, metadata, and correct counts
        await db.exams.update_one(
            {"exam_id": exam_id},
            {"$set": {
                "questions": extracted_questions,
                "questions_count": len(extracted_questions),
                "extraction_source": target_source,
                "total_marks": final_total_marks
            }}
        )

        logger.info(f"✅ Successfully extracted and saved {len(extracted_questions)} questions with complete structure from {target_source}")
        print(f"[EXTRACTION-COMPLETE] Saved {len(extracted_questions)} questions to both db.questions and exam.questions")
        return {
            "success": True,
            "message": f"Successfully extracted {len(extracted_questions)} questions with structure from {target_source.replace('_', ' ')}",
            "count": len(extracted_questions),
            "total_marks": final_total_marks,
            "extracted_total_marks": total_marks,
            "source": target_source,
            "skipped": False
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

        # Force extraction from question paper
        print(f"[QP-ASYNC] Calling auto_extract_questions with force=True")
        result = await auto_extract_questions(exam_id, force=True)
        print(f"[QP-ASYNC] Extraction result: {result}")

        print(f"[QP-ASYNC] Extraction result: {result}")

        # Update extraction status
        update_data = {
            "question_extraction_status": "completed" if result.get("success") else "failed",
            "question_extraction_count": result.get("count", 0),
            "question_extraction_source": result.get("source", "question_paper"),
            "question_extraction_message": result.get("message", ""),
            "question_paper_processing": False,
            "question_extraction_completed_at": datetime.now(timezone.utc).isoformat()
        }
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
            model_answer_text = await extract_model_answer_content(
                model_answer_images=model_images,
                questions=exam_updated.get("questions", []) if exam_updated else []
            )
            print(f"[QP-ASYNC] Model answer text: {len(model_answer_text)} chars")
            if model_answer_text:
                await db.exam_files.update_one(
                    {"exam_id": exam_id, "file_type": "model_answer"},
                    {"$set": {
                        "model_answer_text": model_answer_text,
                        "text_extracted_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
                await db.exams.update_one(
                    {"exam_id": exam_id},
                    {"$set": {
                        "model_answer_text_status": "success",
                        "model_answer_text_chars": len(model_answer_text)
                    }}
                )
                logger.info(f"[QP-ASYNC] Updated model answer text ({len(model_answer_text)} chars) for exam {exam_id}")
                print(f"[QP-ASYNC] Saved model answer text successfully")
        else:
            print(f"[QP-ASYNC] No model answer images found")

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
                "question_extraction_message": str(e)
            }}
        )


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
        result = await auto_extract_questions(exam_id, force=force_extraction)
        print(f"[MA-ASYNC] Extraction result: {result}")

        update_data = {
            "question_extraction_status": "completed" if result.get("success") else "failed",
            "question_extraction_count": result.get("count", 0),
            "question_extraction_source": result.get("source", "model_answer"),
            "question_extraction_message": result.get("message", ""),
            "question_extraction_completed_at": datetime.now(timezone.utc).isoformat()
        }
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
        model_answer_text = await extract_model_answer_content(
            model_answer_images=model_images,
            questions=exam_updated.get("questions", []) if exam_updated else []
        )
        print(f"[MA-ASYNC] Extracted {len(model_answer_text) if model_answer_text else 0} chars")

        if model_answer_text:
            await db.exam_files.update_one(
                {"exam_id": exam_id, "file_type": "model_answer"},
                {"$set": {
                    "model_answer_text": model_answer_text,
                    "text_extracted_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            await db.exams.update_one(
                {"exam_id": exam_id},
                {"$set": {
                    "model_answer_text_status": "success",
                    "model_answer_text_chars": len(model_answer_text)
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
                "model_answer_processing_error": str(e)
            }}
        )
