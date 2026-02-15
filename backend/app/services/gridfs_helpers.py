"""
GridFS helpers for retrieving exam files (model answers, question papers).
"""

import pickle
from typing import List

from bson import ObjectId

from app.database import db, fs
from app.config import logger


async def get_exam_model_answer_images(exam_id: str) -> List[str]:
    """Get model answer images from GridFS or fallback to old storage"""
    # First try GridFS storage (new method)
    file_doc = await db.exam_files.find_one(
        {"exam_id": exam_id, "file_type": "model_answer"},
        {"_id": 0, "gridfs_id": 1, "images": 1}
    )
    
    if file_doc:
        # Try GridFS first (new storage)
        if file_doc.get("gridfs_id"):
            try:
                from bson import ObjectId
                gridfs_file = fs.get(ObjectId(file_doc["gridfs_id"]))
                images = pickle.loads(gridfs_file.read())
                return images
            except Exception as e:
                logger.error(f"Error retrieving from GridFS: {e}")
        
        # Fallback to direct images storage (old method, still supported)
        if file_doc.get("images"):
            return file_doc["images"]
    
    # Fallback to very old storage in exam document
    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "model_answer_images": 1})
    if exam and exam.get("model_answer_images"):
        return exam["model_answer_images"]
    
    return []

async def get_exam_question_paper_images(exam_id: str) -> List[str]:
    """Get question paper images from GridFS or fallback to old storage"""
    # First try GridFS storage (new method)
    file_doc = await db.exam_files.find_one(
        {"exam_id": exam_id, "file_type": "question_paper"},
        {"_id": 0, "gridfs_id": 1, "images": 1}
    )
    
    if file_doc:
        # Try GridFS first (new storage)
        if file_doc.get("gridfs_id"):
            try:
                from bson import ObjectId
                gridfs_file = fs.get(ObjectId(file_doc["gridfs_id"]))
                images = pickle.loads(gridfs_file.read())
                return images
            except Exception as e:
                logger.error(f"Error retrieving from GridFS: {e}")
        
        # Fallback to direct images storage (old method, still supported)
        if file_doc.get("images"):
            return file_doc["images"]
    
    # Fallback to very old storage in exam document
    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "question_paper_images": 1})
    if exam and exam.get("question_paper_images"):
        return exam["question_paper_images"]
    
    return []

async def exam_has_model_answer(exam_id: str) -> bool:
    """Check if exam has model answer uploaded"""
    # Check new collection first
    file_doc = await db.exam_files.find_one(
        {"exam_id": exam_id, "file_type": "model_answer"},
        {"_id": 0}
    )
    if file_doc:
        return True
    
    # Fallback check
    exam = await db.exams.find_one({"exam_id": exam_id}, {"_id": 0, "model_answer_images": 1, "has_model_answer": 1})
    return bool(exam and (exam.get("has_model_answer") or exam.get("model_answer_images")))
