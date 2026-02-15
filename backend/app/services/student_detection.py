"""
Student info extraction from papers and filenames, student creation.
"""

import uuid
import asyncio
import base64
import json
from typing import List
from datetime import datetime, timezone

import google.generativeai as genai

from app.database import db
from app.config import logger, get_llm_api_key


async def extract_student_info_from_paper(file_images: List[str], filename: str) -> tuple:
    """
    Extract student ID/roll number and name from the answer paper using AI
    Returns: (student_id, student_name) or (None, None) if extraction fails
    """
    api_key = get_llm_api_key()
    if not api_key:
        return (None, None)
    
    try:
        # Create Gemini model with system prompt
        system_prompt = """You are an expert at reading handwritten and printed student information from exam papers.

Extract the student's Roll Number/ID and Name from the answer sheet.

Return ONLY a JSON object in this exact format:
{
  "student_id": "the roll number or student ID (can be numbers or alphanumeric)",
  "student_name": "the student's full name"
}

Important:
- Student ID can be just numbers (e.g., "123", "2024001") or alphanumeric (e.g., "STU001", "CS-2024-001")
- Look for labels like "Roll No", "Roll Number", "Student ID", "ID No", "Reg No", "ID", etc.
- Student name is usually written at the top of the page near ID
- If you cannot find either field, use null
- Do NOT include any explanation, ONLY return the JSON"""

        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_prompt
        )
        chat = model.start_chat(history=[])
        
        # Use first page only (usually has student info)
        prompt_text = "Extract the student ID/roll number and name from this answer sheet."
        
        # Create content with image
        # Decode base64 image for Gemini API
        image_data = base64.b64decode(file_images[0])
        
        # Create inline data format for Gemini (using dict format instead of deprecated PartContentType)
        content = [
            prompt_text,
            {"mime_type": "image/jpeg", "data": image_data}
        ]
        
        # Make API call with timeout
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: chat.send_message(content)),
            timeout=120.0
        )
        
        response_text = response.text.strip()
        
        # Parse JSON response
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        result = json.loads(response_text)
        
        student_id = result.get("student_id")
        student_name = result.get("student_name")
        
        # Basic validation
        if student_id and student_name:
            # Clean up
            student_id = str(student_id).strip()
            student_name = str(student_name).strip().title()
            
            # Validate student ID is not too short or too long
            if 1 <= len(student_id) <= 30 and len(student_name) >= 2:
                return (student_id, student_name)
        
        return (None, None)
        
    except Exception as e:
        logger.error(f"Error extracting student info from paper: {e}")
        return (None, None)

def parse_student_from_filename(filename: str) -> tuple:
    """
    Parse student ID and name from filename
    Expected formats: 
    - STU003_Sagar_Maths.pdf -> (STU003, Sagar)
    - 123_John_Doe.pdf -> (123, John Doe)
    - StudentName.pdf -> (None, StudentName)
    Returns: (student_id, student_name)
    """
    try:
        # Remove .pdf extension
        name_part = filename.replace(".pdf", "").replace(".PDF", "")
        
        # Common subject names to filter out
        subject_names = [
            'maths', 'math', 'mathematics', 'english', 'science', 'physics', 
            'chemistry', 'biology', 'history', 'geography', 'hindi', 'sanskrit',
            'social', 'economics', 'commerce', 'accounts', 'computer', 'it',
            'arts', 'music', 'pe', 'physical', 'education', 'exam', 'test'
        ]
        
        # Split by underscore or hyphen
        parts = name_part.replace("-", "_").split("_")
        
        if len(parts) >= 2:
            # First part is likely student ID
            potential_id = parts[0].strip()
            
            # Remaining parts form the name, excluding subject names
            name_parts = []
            for part in parts[1:]:
                if part.lower() not in subject_names:
                    name_parts.append(part)
            
            potential_name = " ".join(name_parts).strip().title()
            
            # Validate ID (should be alphanumeric, not too long)
            if potential_id and len(potential_id) <= 20:
                return (potential_id, potential_name if potential_name else None)
        
        # Fallback: try to clean up the filename as a name
        student_name = name_part.replace("_", " ").replace("-", " ").strip().title()
        
        if student_name and len(student_name) >= 2:
            return (None, student_name)
        
        return (None, None)
    except Exception as e:
        logger.error(f"Error parsing filename {filename}: {e}")
        return (None, None)
        return (None, None)

async def get_or_create_student(
    student_id: str,
    student_name: str,
    batch_id: str,
    teacher_id: str
) -> tuple:
    """
    Get existing student or create new one
    Returns: (user_id, error_message)
    """
    # Check if student ID already exists
    existing = await db.users.find_one({"student_id": student_id, "role": "student"}, {"_id": 0})
    
    if existing:
        # Student exists - use existing student (allow re-grading)
        user_id = existing["user_id"]
        
        # Optionally update name if different (use the new one)
        if existing["name"].lower() != student_name.lower():
            # Log the name difference but don't treat as error - just use existing student
            logger.info(f"Student ID {student_id}: name '{student_name}' differs from existing '{existing['name']}', using existing student")
        
        # Add to batch if not already there
        if batch_id not in existing.get("batches", []):
            await db.users.update_one(
                {"user_id": user_id},
                {"$addToSet": {"batches": batch_id}}
            )
            # Also add student to batch document
            await db.batches.update_one(
                {"batch_id": batch_id},
                {"$addToSet": {"students": user_id}}
            )
        
        return (user_id, None)
    
    # Create new student
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    new_student = {
        "user_id": user_id,
        "email": f"{student_id.lower()}@school.temp",  # Temporary email
        "name": student_name,
        "role": "student",
        "student_id": student_id,
        "batches": [batch_id],
        "teacher_id": teacher_id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.users.insert_one(new_student)
    
    # Add student to batch document
    await db.batches.update_one(
        {"batch_id": batch_id},
        {"$addToSet": {"students": user_id}}
    )
    
    return (user_id, None)
