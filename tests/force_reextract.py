#!/usr/bin/env python3
"""Force re-extraction of all 10 questions for the exam."""

import requests
import json
import time
import sys

BASE_URL = "http://127.0.0.1:8001"
EXAM_ID = "exam_6b33ee05"

# Wait for backend to be ready
print("Waiting for backend to be ready...")
time.sleep(8)

# Headers for API calls
headers = {
    "Authorization": "Bearer test",  # Assuming no auth required in dev
    "Content-Type": "application/json"
}

print(f"\n{'='*70}")
print(f"[FORCE-REEXTRACT] Starting force re-extraction for {EXAM_ID}")
print(f"{'='*70}\n")

# Step 1: Check current questions
print("[1] Checking current questions in database...")
try:
    response = requests.get(f"{BASE_URL}/debug/exam-questions/{EXAM_ID}", headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        print(f"  Database has: {data['database_count']} questions -> Q{data['database_questions']}")
        print(f"  Exam document has: {data['exam_count']} questions -> Q{data['exam_questions']}")
    else:
        print(f"  Error: {response.status_code} - {response.text[:200]}")
except Exception as e:
    print(f"  Error checking questions: {e}")

# Step 2: Force re-extraction
print(f"\n[2] Calling force re-extraction endpoint...")
try:
    response = requests.post(f"{BASE_URL}/debug/force-reextract/{EXAM_ID}", headers=headers, timeout=300)
    if response.status_code == 200:
        data = response.json()
        print(f"  Success: {data['message']}")
        print(f"  Deleted: {data.get('deleted_count', 0)} old questions")
        print(f"  Extracted: {data.get('extracted_count', 0)} new questions")
        print(f"  Response: {json.dumps(data, indent=2)}")
    else:
        print(f"  Error: {response.status_code} - {response.text[:500]}")
except Exception as e:
    print(f"  Error forcing reextraction: {e}")

# Step 3: Check questions again
print(f"\n[3] Checking questions after re-extraction...")
time.sleep(5)
try:
    response = requests.get(f"{BASE_URL}/debug/exam-questions/{EXAM_ID}", headers=headers, timeout=10)
    if response.status_code == 200:
        data = response.json()
        print(f"  Database now has: {data['database_count']} questions -> Q{data['database_questions']}")
        print(f"  Exam document now has: {data['exam_count']} questions -> Q{data['exam_questions']}")
        
        print(f"\n[RESULT] Questions successfully extracted:")
        for detail in data.get('database_details', [])[:10]:
            q_num = detail.get('question_number')
            max_marks = detail.get('max_marks', 0)
            sub_count = len(detail.get('sub_questions', []))
            print(f"  Q{q_num}: {max_marks} marks, {sub_count} parts")
    else:
        print(f"  Error: {response.status_code} - {response.text[:200]}")
except Exception as e:
    print(f"  Error checking after reextraction: {e}")

print(f"\n{'='*70}")
print(f"[COMPLETE] Force re-extraction process finished")
print(f"{'='*70}\n")
