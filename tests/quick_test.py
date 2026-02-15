#!/usr/bin/env python3

import requests
import json
from datetime import datetime
import subprocess

def test_infer_topics():
    base_url = "https://smartgrade-app-1.preview.emergentagent.com/api"
    
    # Create test user and session
    timestamp = int(datetime.now().timestamp())
    user_id = f"quick-test-user-{timestamp}"
    session_token = f"quick_test_session_{timestamp}"
    
    mongo_commands = f"""
use('test_database');
var userId = '{user_id}';
var sessionToken = '{session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert test user
db.users.insertOne({{
  user_id: userId,
  email: 'quick.test.{timestamp}@example.com',
  name: 'Quick Test Teacher',
  role: 'teacher',
  batches: [],
  created_at: new Date().toISOString()
}});

// Insert session
db.user_sessions.insertOne({{
  user_id: userId,
  session_token: sessionToken,
  expires_at: expiresAt.toISOString(),
  created_at: new Date().toISOString()
}});

print('Quick test user created');
"""
    
    with open('/tmp/mongo_quick_setup.js', 'w') as f:
        f.write(mongo_commands)
    
    result = subprocess.run([
        'mongosh', '--quiet', '--file', '/tmp/mongo_quick_setup.js'
    ], capture_output=True, text=True, timeout=30)
    
    if result.returncode != 0:
        print(f"❌ Failed to create test user: {result.stderr}")
        return
    
    print(f"✅ Created test user: {user_id}")
    
    # Create test data
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {session_token}'
    }
    
    # Create batch
    batch_data = {"name": f"Quick Test Batch {timestamp}"}
    batch_response = requests.post(f"{base_url}/batches", json=batch_data, headers=headers)
    if batch_response.status_code != 200:
        print(f"❌ Failed to create batch: {batch_response.text}")
        return
    batch_id = batch_response.json().get('batch_id')
    print(f"✅ Created batch: {batch_id}")
    
    # Create subject
    subject_data = {"name": f"Quick Test Subject {timestamp}"}
    subject_response = requests.post(f"{base_url}/subjects", json=subject_data, headers=headers)
    if subject_response.status_code != 200:
        print(f"❌ Failed to create subject: {subject_response.text}")
        return
    subject_id = subject_response.json().get('subject_id')
    print(f"✅ Created subject: {subject_id}")
    
    # Create exam
    exam_data = {
        "batch_id": batch_id,
        "subject_id": subject_id,
        "exam_type": "Quick Test",
        "exam_name": f"Quick Test Exam {timestamp}",
        "total_marks": 100.0,
        "exam_date": "2024-01-15",
        "grading_mode": "balanced",
        "questions": [
            {
                "question_number": 1,
                "max_marks": 50.0,
                "rubric": "Solve the quadratic equation x² - 5x + 6 = 0 using factoring method",
                "sub_questions": []
            },
            {
                "question_number": 2,
                "max_marks": 50.0,
                "rubric": "Find the derivative of f(x) = 3x² + 2x - 1 and evaluate at x = 2",
                "sub_questions": []
            }
        ]
    }
    exam_response = requests.post(f"{base_url}/exams", json=exam_data, headers=headers)
    if exam_response.status_code != 200:
        print(f"❌ Failed to create exam: {exam_response.text}")
        return
    exam_id = exam_response.json().get('exam_id')
    print(f"✅ Created exam: {exam_id}")
    
    # Test infer topics
    print("\n🏷️  Testing infer topics endpoint...")
    infer_response = requests.post(f"{base_url}/exams/{exam_id}/infer-topics", headers=headers)
    print(f"Status: {infer_response.status_code}")
    
    if infer_response.status_code == 200:
        result = infer_response.json()
        print(f"✅ Infer topics successful!")
        print(f"Response: {json.dumps(result, indent=2)}")
    else:
        print(f"❌ Infer topics failed: {infer_response.text}")
    
    # Cleanup
    cleanup_commands = f"""
use('test_database');
db.users.deleteMany({{email: /quick\\.test\\./}});
db.user_sessions.deleteMany({{session_token: /quick_test_session/}});
db.batches.deleteMany({{name: /Quick Test Batch/}});
db.subjects.deleteMany({{name: /Quick Test Subject/}});
db.exams.deleteMany({{exam_name: /Quick Test Exam/}});
print('Quick test data cleaned up');
"""
    
    with open('/tmp/mongo_quick_cleanup.js', 'w') as f:
        f.write(cleanup_commands)
    
    subprocess.run([
        'mongosh', '--quiet', '--file', '/tmp/mongo_quick_cleanup.js'
    ], capture_output=True, text=True, timeout=30)
    
    print("✅ Cleanup completed")

if __name__ == "__main__":
    test_infer_topics()