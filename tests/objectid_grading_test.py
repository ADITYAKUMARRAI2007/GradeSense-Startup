#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os
import time
import base64

class ObjectIdGradingTester:
    def __init__(self):
        self.base_url = "https://smartgrade-app-1.preview.emergentagent.com/api"
        self.session_token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        
        # Test data storage
        self.test_batch_id = None
        self.test_subject_id = None
        self.test_exam_id = None
        self.test_student_upload_exam_id = None
        self.grading_job_id = None
        self.submission_ids = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED")
        else:
            print(f"❌ {name} - FAILED: {details}")
        
        self.test_results.append({
            "test": name,
            "success": success,
            "details": details
        })

    def run_api_test(self, name, method, endpoint, expected_status, data=None, headers=None, files=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        test_headers = {}
        
        if self.session_token:
            test_headers['Authorization'] = f'Bearer {self.session_token}'
        
        if headers:
            test_headers.update(headers)

        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=30)
            elif method == 'POST':
                if files:
                    # For multipart/form-data requests
                    response = requests.post(url, data=data, files=files, headers=test_headers, timeout=30)
                else:
                    # For JSON requests
                    if 'Content-Type' not in test_headers:
                        test_headers['Content-Type'] = 'application/json'
                    response = requests.post(url, json=data, headers=test_headers, timeout=30)
            elif method == 'PUT':
                if 'Content-Type' not in test_headers:
                    test_headers['Content-Type'] = 'application/json'
                response = requests.put(url, json=data, headers=test_headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, timeout=30)

            print(f"   Status: {response.status_code}")
            
            success = response.status_code == expected_status
            details = ""
            
            if not success:
                details = f"Expected {expected_status}, got {response.status_code}"
                try:
                    error_data = response.json()
                    details += f" - {error_data.get('detail', 'No error details')}"
                except:
                    details += f" - Response: {response.text[:200]}"
            
            self.log_test(name, success, details)
            
            if success:
                try:
                    return response.json()
                except:
                    return {"status": "success"}
            else:
                return None

        except Exception as e:
            self.log_test(name, False, f"Request failed: {str(e)}")
            return None

    def create_test_user_and_session(self):
        """Create test user and session in MongoDB"""
        print("\n🔧 Creating test user and session in MongoDB...")
        
        timestamp = int(datetime.now().timestamp())
        self.user_id = f"test-grading-user-{timestamp}"
        self.session_token = f"test_grading_session_{timestamp}"
        
        # Create MongoDB commands
        mongo_commands = f"""
use('test_database');
var userId = '{self.user_id}';
var sessionToken = '{self.session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert test user
db.users.insertOne({{
  user_id: userId,
  email: 'test.grading.user.{timestamp}@example.com',
  name: 'Test Grading Teacher',
  picture: 'https://via.placeholder.com/150',
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

print('Test grading user and session created successfully');
print('User ID: ' + userId);
print('Session Token: ' + sessionToken);
"""
        
        try:
            # Write commands to temp file
            with open('/tmp/mongo_grading_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            # Execute MongoDB commands
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_grading_setup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ Test grading user created: {self.user_id}")
                print(f"✅ Session token: {self.session_token}")
                return True
            else:
                print(f"❌ MongoDB setup failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating test user: {str(e)}")
            return False

    def setup_test_data(self):
        """Create batch, subject, and students for testing"""
        print("\n🏗️  Setting up test data for grading tests...")
        
        # Create batch
        batch_data = {
            "name": f"ObjectId Test Batch {datetime.now().strftime('%H%M%S')}"
        }
        batch_result = self.run_api_test(
            "Setup: Create Test Batch",
            "POST",
            "batches",
            200,
            data=batch_data
        )
        if batch_result:
            self.test_batch_id = batch_result.get('batch_id')
        
        # Create subject
        subject_data = {
            "name": f"ObjectId Test Subject {datetime.now().strftime('%H%M%S')}"
        }
        subject_result = self.run_api_test(
            "Setup: Create Test Subject",
            "POST",
            "subjects",
            200,
            data=subject_data
        )
        if subject_result:
            self.test_subject_id = subject_result.get('subject_id')
        
        # Create test students
        timestamp = datetime.now().strftime('%H%M%S')
        students = [
            {"name": "Alice Johnson", "id": f"STU{timestamp}1"},
            {"name": "Bob Smith", "id": f"STU{timestamp}2"},
            {"name": "Carol Davis", "id": f"STU{timestamp}3"}
        ]
        
        self.test_student_ids = []
        for i, student in enumerate(students):
            student_data = {
                "email": f"objectid.test.student.{i}.{timestamp}@school.edu",
                "name": student["name"],
                "role": "student",
                "student_id": student["id"],
                "batches": [self.test_batch_id] if self.test_batch_id else []
            }
            
            student_result = self.run_api_test(
                f"Setup: Create Test Student {student['name']}",
                "POST",
                "students",
                200,
                data=student_data
            )
            if student_result:
                self.test_student_ids.append(student_result.get('user_id'))
        
        return bool(self.test_batch_id and self.test_subject_id and self.test_student_ids)

    def create_teacher_upload_exam(self):
        """Create exam for teacher-upload grading workflow"""
        print("\n📝 Creating Teacher-Upload Exam...")
        
        if not (self.test_batch_id and self.test_subject_id):
            print("❌ Missing batch or subject for exam creation")
            return False
        
        exam_data = {
            "batch_id": self.test_batch_id,
            "subject_id": self.test_subject_id,
            "exam_type": "ObjectId Test",
            "exam_name": f"ObjectId Serialization Test {datetime.now().strftime('%H%M%S')}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "exam_mode": "teacher_upload",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 50.0,
                    "rubric": "Solve the algebraic equation: 2x + 5 = 15"
                },
                {
                    "question_number": 2,
                    "max_marks": 30.0,
                    "rubric": "Find the derivative of f(x) = x² + 3x + 2"
                },
                {
                    "question_number": 3,
                    "max_marks": 20.0,
                    "rubric": "Explain the concept of photosynthesis"
                }
            ]
        }
        
        exam_result = self.run_api_test(
            "Phase 1: Create Teacher-Upload Exam",
            "POST",
            "exams",
            200,
            data=exam_data
        )
        
        if exam_result:
            self.test_exam_id = exam_result.get('exam_id')
            print(f"✅ Created teacher-upload exam: {self.test_exam_id}")
            return True
        
        return False

    def create_student_upload_exam(self):
        """Create exam for student-upload grading workflow"""
        print("\n📚 Creating Student-Upload Exam...")
        
        if not (self.test_batch_id and self.test_student_ids):
            print("❌ Missing batch or students for student-upload exam")
            return False
        
        # Create dummy PDF content for question paper and model answer
        dummy_pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000074 00000 n \n0000000120 00000 n \ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n179\n%%EOF"
        
        exam_data = {
            "batch_id": self.test_batch_id,
            "exam_name": f"Student Upload ObjectId Test {datetime.now().strftime('%H%M%S')}",
            "total_marks": 100.0,
            "grading_mode": "balanced",
            "student_ids": self.test_student_ids[:2],  # Select first 2 students
            "show_question_paper": True,
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 60.0,
                    "rubric": "Analyze the given mathematical problem"
                },
                {
                    "question_number": 2,
                    "max_marks": 40.0,
                    "rubric": "Provide detailed explanation with examples"
                }
            ]
        }
        
        files = {
            'question_paper': ('question_paper.pdf', dummy_pdf_content, 'application/pdf'),
            'model_answer': ('model_answer.pdf', dummy_pdf_content, 'application/pdf')
        }
        
        exam_result = self.run_api_test(
            "Phase 2: Create Student-Upload Exam",
            "POST",
            "exams/student-mode",
            200,
            data={"exam_data": json.dumps(exam_data)},
            files=files
        )
        
        if exam_result:
            self.test_student_upload_exam_id = exam_result.get('exam_id')
            print(f"✅ Created student-upload exam: {self.test_student_upload_exam_id}")
            return True
        
        return False

    def simulate_student_submissions(self):
        """Simulate student answer submissions for student-upload exam"""
        print("\n👥 Simulating Student Submissions...")
        
        if not self.test_student_upload_exam_id:
            print("❌ No student-upload exam to submit to")
            return False
        
        # Create student sessions and submit answers
        timestamp = int(datetime.now().timestamp())
        submitted_count = 0
        
        for i, student_id in enumerate(self.test_student_ids[:2]):  # First 2 students
            # Create student session
            student_session_token = f"student_session_{timestamp}_{i}"
            
            mongo_commands = f"""
use('test_database');
var studentId = '{student_id}';
var sessionToken = '{student_session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert student session
db.user_sessions.insertOne({{
  user_id: studentId,
  session_token: sessionToken,
  expires_at: expiresAt.toISOString(),
  created_at: new Date().toISOString()
}});

print('Student session created: ' + sessionToken);
"""
            
            try:
                with open(f'/tmp/mongo_student_session_{i}.js', 'w') as f:
                    f.write(mongo_commands)
                
                result = subprocess.run([
                    'mongosh', '--quiet', '--file', f'/tmp/mongo_student_session_{i}.js'
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    # Switch to student session and submit answer
                    original_token = self.session_token
                    self.session_token = student_session_token
                    
                    # Create dummy answer PDF
                    dummy_answer_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000074 00000 n \n0000000120 00000 n \ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n179\n%%EOF"
                    
                    files = {
                        'answer_paper': (f'student_{i}_answer.pdf', dummy_answer_content, 'application/pdf')
                    }
                    
                    submit_result = self.run_api_test(
                        f"Student {i+1}: Submit Answer Paper",
                        "POST",
                        f"exams/{self.test_student_upload_exam_id}/submit",
                        200,
                        files=files
                    )
                    
                    # Restore teacher session
                    self.session_token = original_token
                    
                    if submit_result:
                        submitted_count += 1
                        print(f"✅ Student {i+1} submitted successfully")
                    
            except Exception as e:
                print(f"❌ Error creating student session {i}: {str(e)}")
        
        return submitted_count > 0

    def upload_student_papers_teacher_mode(self):
        """Upload student papers for teacher-upload exam"""
        print("\n📄 Uploading Student Papers (Teacher Mode)...")
        
        if not self.test_exam_id:
            print("❌ No teacher-upload exam to upload papers to")
            return False
        
        # Create dummy PDF files for student papers
        dummy_pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000074 00000 n \n0000000120 00000 n \ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n179\n%%EOF"
        
        # Upload model answer first
        model_answer_files = {
            'model_answer': ('model_answer.pdf', dummy_pdf_content, 'application/pdf')
        }
        
        model_result = self.run_api_test(
            "Upload Model Answer",
            "POST",
            f"exams/{self.test_exam_id}/upload-model-answer",
            200,
            files=model_answer_files
        )
        
        if not model_result:
            print("❌ Failed to upload model answer")
            return False
        
        # Upload student papers
        timestamp = datetime.now().strftime('%H%M%S')
        student_files = {}
        
        for i in range(3):  # Upload 3 student papers
            student_files[f'student_papers'] = (
                f'STU{timestamp}{i+1}_Student_{i+1}_Math.pdf',
                dummy_pdf_content,
                'application/pdf'
            )
        
        upload_result = self.run_api_test(
            "Upload Student Papers",
            "POST",
            f"exams/{self.test_exam_id}/upload-papers",
            200,
            files=student_files
        )
        
        return upload_result is not None

    def trigger_grading_teacher_mode(self):
        """Trigger grading for teacher-upload exam"""
        print("\n⚡ Triggering Grading (Teacher Mode)...")
        
        if not self.test_exam_id:
            print("❌ No exam to grade")
            return False
        
        # Trigger background grading
        grading_result = self.run_api_test(
            "CRITICAL: Trigger Background Grading",
            "POST",
            f"exams/{self.test_exam_id}/grade-papers-bg",
            200
        )
        
        if grading_result:
            self.grading_job_id = grading_result.get('job_id')
            print(f"✅ Grading job started: {self.grading_job_id}")
            return True
        
        return False

    def trigger_grading_student_mode(self):
        """Trigger grading for student-upload exam"""
        print("\n⚡ Triggering Grading (Student Mode)...")
        
        if not self.test_student_upload_exam_id:
            print("❌ No student-upload exam to grade")
            return False
        
        # Trigger batch grading for student submissions
        grading_result = self.run_api_test(
            "CRITICAL: Trigger Student Submissions Grading",
            "POST",
            f"exams/{self.test_student_upload_exam_id}/grade-student-submissions",
            200
        )
        
        if grading_result:
            student_grading_job_id = grading_result.get('job_id')
            print(f"✅ Student grading job started: {student_grading_job_id}")
            return True
        
        return False

    def test_grading_job_status_objectid_fix(self):
        """CRITICAL TEST: Verify grading job status endpoint doesn't crash with ObjectId serialization"""
        print("\n🔥 CRITICAL TEST: Grading Job Status ObjectId Serialization...")
        
        if not self.grading_job_id:
            print("❌ No grading job ID to test")
            return False
        
        # This endpoint was crashing before the fix due to ObjectId serialization
        max_attempts = 10
        attempt = 0
        
        while attempt < max_attempts:
            attempt += 1
            print(f"   Attempt {attempt}/{max_attempts}: Polling grading job status...")
            
            job_result = self.run_api_test(
                f"CRITICAL: Get Grading Job Status (Attempt {attempt})",
                "GET",
                f"grading-jobs/{self.grading_job_id}",
                200
            )
            
            if job_result:
                status = job_result.get('status', 'unknown')
                print(f"   Job Status: {status}")
                
                # Check for ObjectId serialization issues
                if '_id' in str(job_result):
                    self.log_test("ObjectId Serialization Check", False, 
                        "Found _id field in response - serialization not working")
                    return False
                
                # Verify response structure
                required_fields = ['job_id', 'status', 'created_at']
                missing_fields = [field for field in required_fields if field not in job_result]
                
                if missing_fields:
                    self.log_test("Grading Job Response Structure", False, 
                        f"Missing fields: {missing_fields}")
                else:
                    self.log_test("Grading Job Response Structure", True, 
                        "All required fields present")
                
                # Check if job is completed
                if status in ['completed', 'failed']:
                    print(f"   Job finished with status: {status}")
                    
                    if status == 'completed':
                        # Get submissions from the job
                        submissions = job_result.get('submissions', [])
                        if submissions:
                            self.submission_ids = [sub.get('submission_id') for sub in submissions if sub.get('submission_id')]
                            print(f"   Found {len(self.submission_ids)} submissions")
                        
                        self.log_test("CRITICAL: Grading Job ObjectId Serialization", True, 
                            f"Job completed successfully without ObjectId errors. Status: {status}")
                        return True
                    else:
                        self.log_test("CRITICAL: Grading Job ObjectId Serialization", False, 
                            f"Job failed with status: {status}")
                        return False
                
                # Wait before next attempt
                time.sleep(5)
            else:
                print(f"   Failed to get job status on attempt {attempt}")
                time.sleep(2)
        
        self.log_test("CRITICAL: Grading Job ObjectId Serialization", False, 
            f"Job did not complete within {max_attempts} attempts")
        return False

    def test_submission_details_objectid_fix(self):
        """CRITICAL TEST: Verify submission details endpoint doesn't crash with ObjectId serialization"""
        print("\n🔥 CRITICAL TEST: Submission Details ObjectId Serialization...")
        
        if not self.submission_ids:
            print("❌ No submission IDs to test")
            return False
        
        success_count = 0
        
        for i, submission_id in enumerate(self.submission_ids[:3]):  # Test first 3 submissions
            print(f"   Testing submission {i+1}: {submission_id}")
            
            submission_result = self.run_api_test(
                f"CRITICAL: Get Submission Details {i+1}",
                "GET",
                f"submissions/{submission_id}",
                200
            )
            
            if submission_result:
                # Check for ObjectId serialization issues
                response_str = str(submission_result)
                if '_id' in response_str:
                    self.log_test(f"Submission {i+1} ObjectId Serialization", False, 
                        "Found _id field in response - serialization not working")
                    continue
                
                # Verify essential fields are present
                essential_fields = ['submission_id', 'exam_id', 'student_id', 'student_name', 
                                  'total_score', 'percentage', 'question_scores']
                missing_fields = [field for field in essential_fields if field not in submission_result]
                
                if missing_fields:
                    self.log_test(f"Submission {i+1} Response Structure", False, 
                        f"Missing fields: {missing_fields}")
                else:
                    self.log_test(f"Submission {i+1} Response Structure", True, 
                        "All essential fields present")
                    success_count += 1
                
                # Check question scores structure
                question_scores = submission_result.get('question_scores', [])
                if question_scores:
                    for q_score in question_scores:
                        if '_id' in str(q_score):
                            self.log_test(f"Submission {i+1} Question Scores ObjectId", False, 
                                "Found _id in question_scores - nested serialization issue")
                            break
                    else:
                        self.log_test(f"Submission {i+1} Question Scores ObjectId", True, 
                            "No _id fields found in question_scores")
        
        overall_success = success_count == len(self.submission_ids[:3])
        self.log_test("CRITICAL: All Submissions ObjectId Serialization", overall_success, 
            f"Successfully tested {success_count}/{len(self.submission_ids[:3])} submissions")
        
        return overall_success

    def test_bulk_grading_operations(self):
        """Test bulk grading operations with multiple papers"""
        print("\n📊 Testing Bulk Grading Operations...")
        
        # Create an exam with more papers for bulk testing
        if not (self.test_batch_id and self.test_subject_id):
            print("❌ Missing batch or subject for bulk test")
            return False
        
        bulk_exam_data = {
            "batch_id": self.test_batch_id,
            "subject_id": self.test_subject_id,
            "exam_type": "Bulk Test",
            "exam_name": f"Bulk ObjectId Test {datetime.now().strftime('%H%M%S')}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "exam_mode": "teacher_upload",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 50.0,
                    "rubric": "Mathematics problem solving"
                },
                {
                    "question_number": 2,
                    "max_marks": 50.0,
                    "rubric": "Science explanation"
                }
            ]
        }
        
        bulk_exam_result = self.run_api_test(
            "Bulk Test: Create Exam",
            "POST",
            "exams",
            200,
            data=bulk_exam_data
        )
        
        if not bulk_exam_result:
            return False
        
        bulk_exam_id = bulk_exam_result.get('exam_id')
        
        # Upload model answer
        dummy_pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000074 00000 n \n0000000120 00000 n \ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n179\n%%EOF"
        
        model_files = {
            'model_answer': ('bulk_model_answer.pdf', dummy_pdf_content, 'application/pdf')
        }
        
        model_result = self.run_api_test(
            "Bulk Test: Upload Model Answer",
            "POST",
            f"exams/{bulk_exam_id}/upload-model-answer",
            200,
            files=model_files
        )
        
        if not model_result:
            return False
        
        # Upload multiple student papers (5 papers)
        timestamp = datetime.now().strftime('%H%M%S')
        for i in range(5):
            student_files = {
                'student_papers': (
                    f'BULK{timestamp}{i+1}_Student_{i+1}_Test.pdf',
                    dummy_pdf_content,
                    'application/pdf'
                )
            }
            
            upload_result = self.run_api_test(
                f"Bulk Test: Upload Student Paper {i+1}",
                "POST",
                f"exams/{bulk_exam_id}/upload-papers",
                200,
                files=student_files
            )
            
            if not upload_result:
                print(f"❌ Failed to upload student paper {i+1}")
        
        # Trigger bulk grading
        bulk_grading_result = self.run_api_test(
            "Bulk Test: Trigger Grading",
            "POST",
            f"exams/{bulk_exam_id}/grade-papers-bg",
            200
        )
        
        if bulk_grading_result:
            bulk_job_id = bulk_grading_result.get('job_id')
            
            # Monitor bulk grading job
            max_attempts = 15
            attempt = 0
            
            while attempt < max_attempts:
                attempt += 1
                print(f"   Bulk grading attempt {attempt}/{max_attempts}...")
                
                job_result = self.run_api_test(
                    f"Bulk Test: Check Job Status (Attempt {attempt})",
                    "GET",
                    f"grading-jobs/{bulk_job_id}",
                    200
                )
                
                if job_result:
                    status = job_result.get('status', 'unknown')
                    
                    if status in ['completed', 'failed']:
                        if status == 'completed':
                            submissions = job_result.get('submissions', [])
                            self.log_test("Bulk Grading ObjectId Serialization", True, 
                                f"Bulk grading completed with {len(submissions)} submissions")
                            return True
                        else:
                            self.log_test("Bulk Grading ObjectId Serialization", False, 
                                f"Bulk grading failed with status: {status}")
                            return False
                
                time.sleep(3)
            
            self.log_test("Bulk Grading ObjectId Serialization", False, 
                "Bulk grading did not complete in time")
        
        return False

    def test_edge_cases_objectid_serialization(self):
        """Test edge cases for ObjectId serialization"""
        print("\n🧪 Testing Edge Cases for ObjectId Serialization...")
        
        # Test 1: Get non-existent grading job (should return 404, not crash)
        fake_job_id = "job_nonexistent123"
        self.run_api_test(
            "Edge Case: Non-existent Grading Job",
            "GET",
            f"grading-jobs/{fake_job_id}",
            404
        )
        
        # Test 2: Get non-existent submission (should return 404, not crash)
        fake_submission_id = "sub_nonexistent123"
        self.run_api_test(
            "Edge Case: Non-existent Submission",
            "GET",
            f"submissions/{fake_submission_id}",
            404
        )
        
        # Test 3: Get submissions list (should not contain _id fields)
        submissions_list = self.run_api_test(
            "Edge Case: Submissions List ObjectId Check",
            "GET",
            "submissions",
            200
        )
        
        if submissions_list:
            submissions_str = str(submissions_list)
            if '_id' in submissions_str:
                self.log_test("Submissions List ObjectId Serialization", False, 
                    "Found _id fields in submissions list")
            else:
                self.log_test("Submissions List ObjectId Serialization", True, 
                    "No _id fields found in submissions list")
        
        # Test 4: Get exams list (should not contain _id fields)
        exams_list = self.run_api_test(
            "Edge Case: Exams List ObjectId Check",
            "GET",
            "exams",
            200
        )
        
        if exams_list:
            exams_str = str(exams_list)
            if '_id' in exams_str:
                self.log_test("Exams List ObjectId Serialization", False, 
                    "Found _id fields in exams list")
            else:
                self.log_test("Exams List ObjectId Serialization", True, 
                    "No _id fields found in exams list")
        
        return True

    def run_comprehensive_objectid_tests(self):
        """Run comprehensive ObjectId serialization tests"""
        print("🚀 STARTING COMPREHENSIVE OBJECTID SERIALIZATION TESTS")
        print("=" * 80)
        
        # Setup
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user and session")
            return False
        
        if not self.setup_test_data():
            print("❌ Failed to setup test data")
            return False
        
        # Phase 1: Teacher-Upload Grading Flow
        print("\n" + "="*60)
        print("PHASE 1: TEACHER-UPLOAD GRADING FLOW")
        print("="*60)
        
        if self.create_teacher_upload_exam():
            if self.upload_student_papers_teacher_mode():
                if self.trigger_grading_teacher_mode():
                    self.test_grading_job_status_objectid_fix()
                    self.test_submission_details_objectid_fix()
        
        # Phase 2: Student-Upload Grading Flow
        print("\n" + "="*60)
        print("PHASE 2: STUDENT-UPLOAD GRADING FLOW")
        print("="*60)
        
        if self.create_student_upload_exam():
            if self.simulate_student_submissions():
                self.trigger_grading_student_mode()
        
        # Phase 3: Bulk Operations and Edge Cases
        print("\n" + "="*60)
        print("PHASE 3: BULK OPERATIONS AND EDGE CASES")
        print("="*60)
        
        self.test_bulk_grading_operations()
        self.test_edge_cases_objectid_serialization()
        
        # Final Results
        print("\n" + "="*80)
        print("OBJECTID SERIALIZATION TEST RESULTS")
        print("="*80)
        
        print(f"Total Tests Run: {self.tests_run}")
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%")
        
        # Show critical test results
        critical_tests = [result for result in self.test_results if "CRITICAL" in result["test"]]
        if critical_tests:
            print("\n🔥 CRITICAL TEST RESULTS:")
            for test in critical_tests:
                status = "✅ PASSED" if test["success"] else "❌ FAILED"
                print(f"   {status}: {test['test']}")
                if not test["success"] and test["details"]:
                    print(f"      Details: {test['details']}")
        
        # Show failed tests
        failed_tests = [result for result in self.test_results if not result["success"]]
        if failed_tests:
            print(f"\n❌ FAILED TESTS ({len(failed_tests)}):")
            for test in failed_tests:
                print(f"   • {test['test']}: {test['details']}")
        
        return self.tests_passed == self.tests_run

if __name__ == "__main__":
    tester = ObjectIdGradingTester()
    success = tester.run_comprehensive_objectid_tests()
    
    if success:
        print("\n🎉 ALL OBJECTID SERIALIZATION TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n💥 SOME OBJECTID SERIALIZATION TESTS FAILED!")
        sys.exit(1)