"""Hashing utilities for cache keys and content deduplication."""

import hashlib
import json
from typing import List


def get_paper_hash(student_images, model_answer_images, questions, grading_mode):
    """SHA256 hash for stable grading cache keys."""
    content = {
        "student": [hashlib.sha256(img.encode()).hexdigest() for img in student_images],
        "model": [hashlib.sha256(img.encode()).hexdigest() for img in model_answer_images],
        "questions": str(questions),
        "mode": grading_mode
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def get_model_answer_hash(images):
    """SHA256 hash for model answer images."""
    image_hashes = [hashlib.sha256(img.encode()).hexdigest() for img in images]
    return hashlib.sha256(json.dumps(image_hashes).encode()).hexdigest()
