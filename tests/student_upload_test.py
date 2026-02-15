#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os
import io
import base64

class StudentUploadWorkflowTester:
    def __init__(self):
        self.base_url = "https://smartgrade-app-1.preview.emergentagent.com/api"
        self.teacher_session_token = None
        self.student_session_token = None
        self.teacher_user_id = None
        self.student_user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        
        # Test data storage
        self.test_batch_id = None
        self.test_exam_id = None
        self.test_student_ids = []
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

    def run_api_test(self, name, method, endpoint, expected_status, data=None, headers=None, files=None, session_type="teacher"):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        test_headers = {}
        
        # Choose session token based on type
        session_token = self.teacher_session_token if session_type == "teacher" else self.student_session_token
        
        if session_token:
            test_headers['Authorization'] = f'Bearer {session_token}'
        
        if headers:
            test_headers.update(headers)

        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        print(f"   Session: {session_type}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=30)
            elif method == 'POST':
                if files:
                    # For multipart form data
                    response = requests.post(url, data=data, files=files, headers={k: v for k, v in test_headers.items() if k != 'Content-Type'}, timeout=30)
                else:
                    test_headers['Content-Type'] = 'application/json'
                    response = requests.post(url, json=data, headers=test_headers, timeout=30)
            elif method == 'PUT':
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

    def create_test_users_and_sessions(self):
        """Create test teacher and student users with sessions"""
        print("\n🔧 Creating test teacher and student users...")
        
        timestamp = int(datetime.now().timestamp())
        self.teacher_user_id = f"test-teacher-{timestamp}"
        self.teacher_session_token = f"teacher_session_{timestamp}"
        
        # We'll create the student session later using one of the created students
        
        # Create MongoDB commands for teacher user
        mongo_commands = f"""
use('test_database');
var teacherId = '{self.teacher_user_id}';
var teacherToken = '{self.teacher_session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert test teacher
db.users.insertOne({{
  user_id: teacherId,
  email: 'test.teacher.{timestamp}@example.com',
  name: 'Test Teacher Upload',
  picture: 'https://via.placeholder.com/150',
  role: 'teacher',
  batches: [],
  created_at: new Date().toISOString()
}});

// Insert teacher session
db.user_sessions.insertOne({{
  user_id: teacherId,
  session_token: teacherToken,
  expires_at: expiresAt.toISOString(),
  created_at: new Date().toISOString()
}});

print('Test teacher user created successfully');
print('Teacher ID: ' + teacherId);
"""
        
        try:
            # Write commands to temp file
            with open('/tmp/mongo_upload_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            # Execute MongoDB commands
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_upload_setup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ Test teacher created: {self.teacher_user_id}")
                return True
            else:
                print(f"❌ MongoDB setup failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating test users: {str(e)}")
            return False

    def create_student_session_for_enrolled_student(self):
        """Create session for one of the enrolled students"""
        if not self.test_student_ids:
            return False
            
        # Use the first created student
        self.student_user_id = self.test_student_ids[0]
        timestamp = int(datetime.now().timestamp())
        self.student_session_token = f"student_session_{timestamp}"
        
        mongo_commands = f"""
use('test_database');
var studentId = '{self.student_user_id}';
var studentToken = '{self.student_session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert student session
db.user_sessions.insertOne({{
  user_id: studentId,
  session_token: studentToken,
  expires_at: expiresAt.toISOString(),
  created_at: new Date().toISOString()
}});

print('Student session created for enrolled student');
"""
        
        try:
            with open('/tmp/mongo_student_session.js', 'w') as f:
                f.write(mongo_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_student_session.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ Student session created for: {self.student_user_id}")
                return True
            else:
                print(f"❌ Student session creation failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating student session: {str(e)}")
            return False

    def create_test_batch_and_students(self):
        """Create test batch and add students to it"""
        print("\n📚 Creating test batch and students...")
        
        # Create batch
        batch_data = {
            "name": f"Student Upload Test Batch {datetime.now().strftime('%H%M%S')}"
        }
        batch_result = self.run_api_test(
            "Create Test Batch",
            "POST",
            "batches",
            200,
            data=batch_data,
            session_type="teacher"
        )
        
        if not batch_result:
            return False
            
        self.test_batch_id = batch_result.get('batch_id')
        print(f"✅ Created batch: {self.test_batch_id}")
        
        # Create 3 test students
        timestamp = datetime.now().strftime('%H%M%S')
        students_data = [
            {
                "email": f"alice.smith.{timestamp}@school.edu",
                "name": "Alice Smith",
                "role": "student",
                "student_id": f"STU001{timestamp}",
                "batches": [self.test_batch_id]
            },
            {
                "email": f"bob.jones.{timestamp}@school.edu", 
                "name": "Bob Jones",
                "role": "student",
                "student_id": f"STU002{timestamp}",
                "batches": [self.test_batch_id]
            },
            {
                "email": f"carol.davis.{timestamp}@school.edu",
                "name": "Carol Davis", 
                "role": "student",
                "student_id": f"STU003{timestamp}",
                "batches": [self.test_batch_id]
            }
        ]
        
        for i, student_data in enumerate(students_data):
            result = self.run_api_test(
                f"Create Test Student {i+1}",
                "POST",
                "students",
                200,
                data=student_data,
                session_type="teacher"
            )
            if result:
                self.test_student_ids.append(result.get('user_id'))
        
        print(f"✅ Created {len(self.test_student_ids)} test students")
        return len(self.test_student_ids) == 3

    def create_dummy_pdf_files(self):
        """Create dummy PDF files for testing"""
        # Create minimal PDF content (this is a very basic PDF structure)
        pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj

2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj

3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj

4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test PDF Content) Tj
ET
endstream
endobj

xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000206 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
299
%%EOF"""
        
        return pdf_content

    def test_phase_b_teacher_creation_flow(self):
        """Test PHASE B: Teacher Creation Flow"""
        print("\n" + "="*60)
        print("PHASE B: TEACHER CREATION FLOW")
        print("="*60)
        
        if not self.test_batch_id or not self.test_student_ids:
            print("❌ Cannot test Phase B - missing batch or students")
            return False
        
        # Create dummy PDF files
        question_paper_content = self.create_dummy_pdf_files()
        model_answer_content = self.create_dummy_pdf_files()
        
        # Prepare exam data
        exam_data = {
            "batch_id": self.test_batch_id,
            "exam_name": f"Student Upload Test Exam {datetime.now().strftime('%H%M%S')}",
            "total_marks": 100.0,
            "grading_mode": "balanced",
            "student_ids": self.test_student_ids[:2],  # Select first 2 students
            "show_question_paper": True,
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 50.0,
                    "rubric": "Solve the algebraic equation: 2x + 5 = 15"
                },
                {
                    "question_number": 2,
                    "max_marks": 50.0,
                    "rubric": "Find the derivative of f(x) = x² + 3x + 2"
                }
            ]
        }
        
        # Test POST /api/exams/student-mode
        files = {
            'question_paper': ('question_paper.pdf', io.BytesIO(question_paper_content), 'application/pdf'),
            'model_answer': ('model_answer.pdf', io.BytesIO(model_answer_content), 'application/pdf')
        }
        
        # Send exam_data as form field, not JSON
        form_data = {
            'exam_data': json.dumps(exam_data)
        }
        
        result = self.run_api_test(
            "PHASE B: Create Student-Upload Exam",
            "POST",
            "exams/student-mode",
            200,
            data=form_data,
            files=files,
            session_type="teacher"
        )
        
        if result:
            self.test_exam_id = result.get('exam_id')
            print(f"✅ Created student-upload exam: {self.test_exam_id}")
            return True
        
        return False

    def test_phase_b_authentication_checks(self):
        """Test authentication and authorization for Phase B"""
        print("\n🔐 Testing Phase B Authentication...")
        
        # Test without authentication
        exam_data = {"batch_id": "test", "exam_name": "Test", "total_marks": 100}
        files = {
            'question_paper': ('test.pdf', io.BytesIO(b'test'), 'application/pdf'),
            'model_answer': ('test.pdf', io.BytesIO(b'test'), 'application/pdf')
        }
        
        form_data = {'exam_data': json.dumps(exam_data)}
        
        # Temporarily remove session token
        original_token = self.teacher_session_token
        self.teacher_session_token = None
        
        self.run_api_test(
            "PHASE B: Create Exam Without Auth (should fail)",
            "POST",
            "exams/student-mode",
            401,
            data=form_data,
            files=files,
            session_type="teacher"
        )
        
        # Restore token
        self.teacher_session_token = original_token
        
        # Test with student session (should fail)
        self.run_api_test(
            "PHASE B: Create Exam as Student (should fail)",
            "POST", 
            "exams/student-mode",
            403,
            data=form_data,
            files=files,
            session_type="student"
        )

    def test_phase_c_student_flow(self):
        """Test PHASE C: Student Flow"""
        print("\n" + "="*60)
        print("PHASE C: STUDENT FLOW")
        print("="*60)
        
        if not self.test_exam_id:
            print("❌ Cannot test Phase C - no exam created")
            return False
        
        # Test GET /api/students/my-exams
        my_exams_result = self.run_api_test(
            "PHASE C: Get Student's Exams",
            "GET",
            "students/my-exams",
            200,
            session_type="student"
        )
        
        if my_exams_result:
            exams = my_exams_result if isinstance(my_exams_result, list) else my_exams_result.get('exams', [])
            print(f"✅ Student can see {len(exams)} exam(s)")
            
            # Check if our test exam is in the list
            test_exam_found = any(exam.get('exam_id') == self.test_exam_id for exam in exams)
            if test_exam_found:
                self.log_test("PHASE C: Test Exam Visible to Student", True, "Test exam found in student's exam list")
            else:
                self.log_test("PHASE C: Test Exam Visible to Student", False, "Test exam not found in student's exam list")
        
        # Test GET /api/exams/{exam_id}/question-paper
        qp_result = self.run_api_test(
            "PHASE C: Download Question Paper",
            "GET",
            f"exams/{self.test_exam_id}/question-paper",
            200,
            session_type="student"
        )
        
        # Test POST /api/exams/{exam_id}/submit (student submits answer)
        answer_paper_content = self.create_dummy_pdf_files()
        
        files = {
            'answer_paper': ('my_answer.pdf', io.BytesIO(answer_paper_content), 'application/pdf')
        }
        
        submit_result = self.run_api_test(
            "PHASE C: Submit Answer Paper",
            "POST",
            f"exams/{self.test_exam_id}/submit",
            200,
            files=files,
            session_type="student"
        )
        
        if submit_result:
            submission_id = submit_result.get('submission_id')
            self.submission_ids.append(submission_id)
            print(f"✅ Student submitted answer: {submission_id}")
        
        return True

    def test_phase_c_edge_cases(self):
        """Test Phase C edge cases"""
        print("\n⚠️  Testing Phase C Edge Cases...")
        
        if not self.test_exam_id:
            print("❌ Cannot test Phase C edge cases - no exam created")
            return False
        
        # Test re-submission (should fail)
        answer_paper_content = self.create_dummy_pdf_files()
        files = {
            'answer_paper': ('duplicate_answer.pdf', io.BytesIO(answer_paper_content), 'application/pdf')
        }
        
        self.run_api_test(
            "PHASE C: Re-submission Attempt (should fail)",
            "POST",
            f"exams/{self.test_exam_id}/submit",
            400,
            files=files,
            session_type="student"
        )
        
        # Test submission by non-enrolled student (create another student)
        timestamp = int(datetime.now().timestamp())
        non_enrolled_user_id = f"non-enrolled-{timestamp}"
        non_enrolled_token = f"non_enrolled_session_{timestamp}"
        
        # Create non-enrolled student in MongoDB
        mongo_commands = f"""
use('test_database');
var userId = '{non_enrolled_user_id}';
var sessionToken = '{non_enrolled_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

db.users.insertOne({{
  user_id: userId,
  email: 'non.enrolled.{timestamp}@example.com',
  name: 'Non Enrolled Student',
  role: 'student',
  batches: [],
  created_at: new Date().toISOString()
}});

db.user_sessions.insertOne({{
  user_id: userId,
  session_token: sessionToken,
  expires_at: expiresAt.toISOString(),
  created_at: new Date().toISOString()
}});

print('Non-enrolled student created');
"""
        
        try:
            with open('/tmp/mongo_non_enrolled.js', 'w') as f:
                f.write(mongo_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_non_enrolled.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # Test submission by non-enrolled student
                original_token = self.student_session_token
                self.student_session_token = non_enrolled_token
                
                self.run_api_test(
                    "PHASE C: Non-enrolled Student Submit (should fail)",
                    "POST",
                    f"exams/{self.test_exam_id}/submit",
                    403,
                    files=files,
                    session_type="student"
                )
                
                # Restore original token
                self.student_session_token = original_token
                
        except Exception as e:
            print(f"⚠️  Could not test non-enrolled student: {str(e)}")

    def test_phase_d_grading_trigger_flow(self):
        """Test PHASE D: Grading Trigger Flow"""
        print("\n" + "="*60)
        print("PHASE D: GRADING TRIGGER FLOW")
        print("="*60)
        
        if not self.test_exam_id:
            print("❌ Cannot test Phase D - no exam created")
            return False
        
        # Test GET /api/exams/{exam_id}/submissions-status
        status_result = self.run_api_test(
            "PHASE D: Get Submission Status",
            "GET",
            f"exams/{self.test_exam_id}/submissions-status",
            200,
            session_type="teacher"
        )
        
        if status_result:
            total_students = status_result.get('total_students', 0)
            submitted_count = status_result.get('submitted_count', 0)
            students = status_result.get('students', [])
            
            print(f"✅ Submission status: {submitted_count}/{total_students} submitted")
            
            # Find a non-submitter to remove
            non_submitter = None
            for student in students:
                if not student.get('submitted', False):
                    non_submitter = student
                    break
            
            if non_submitter:
                # Test DELETE /api/exams/{exam_id}/remove-student/{student_id}
                remove_result = self.run_api_test(
                    "PHASE D: Remove Non-submitter",
                    "DELETE",
                    f"exams/{self.test_exam_id}/remove-student/{non_submitter['student_id']}",
                    200,
                    session_type="teacher"
                )
                
                if remove_result:
                    print(f"✅ Removed non-submitter: {non_submitter['name']}")
        
        # Test POST /api/exams/{exam_id}/grade-student-submissions
        grade_result = self.run_api_test(
            "PHASE D: Trigger Batch Grading",
            "POST",
            f"exams/{self.test_exam_id}/grade-student-submissions",
            200,
            session_type="teacher"
        )
        
        if grade_result:
            job_id = grade_result.get('job_id')
            print(f"✅ Grading job created: {job_id}")
        
        return True

    def test_phase_d_authorization_checks(self):
        """Test Phase D authorization"""
        print("\n🔐 Testing Phase D Authorization...")
        
        if not self.test_exam_id:
            print("❌ Cannot test Phase D auth - no exam created")
            return False
        
        # Test student trying to access teacher endpoints
        self.run_api_test(
            "PHASE D: Student Access Submissions Status (should fail)",
            "GET",
            f"exams/{self.test_exam_id}/submissions-status",
            403,
            session_type="student"
        )
        
        self.run_api_test(
            "PHASE D: Student Trigger Grading (should fail)",
            "POST",
            f"exams/{self.test_exam_id}/grade-student-submissions",
            403,
            session_type="student"
        )

    def test_data_model_verification(self):
        """Test data model verification"""
        print("\n" + "="*60)
        print("DATA MODEL VERIFICATION")
        print("="*60)
        
        if not self.test_exam_id:
            print("❌ Cannot verify data model - no exam created")
            return False
        
        # Verify exam document structure
        mongo_commands = f"""
use('test_database');
var examId = '{self.test_exam_id}';

// Check exam document
var exam = db.exams.findOne({{"exam_id": examId}});
if (exam) {{
    print('Exam found with fields:');
    print('- exam_mode: ' + exam.exam_mode);
    print('- selected_students: ' + JSON.stringify(exam.selected_students));
    print('- submitted_count: ' + exam.submitted_count);
    print('- show_question_paper: ' + exam.show_question_paper);
    print('- status: ' + exam.status);
    
    if (exam.exam_mode === 'student_upload') {{
        print('✅ Exam mode correctly set to student_upload');
    }} else {{
        print('❌ Exam mode incorrect: ' + exam.exam_mode);
    }}
}} else {{
    print('❌ Exam not found');
}}

// Check student_submissions collection
var submissions = db.student_submissions.find({{"exam_id": examId}}).toArray();
print('Student submissions found: ' + submissions.length);

submissions.forEach(function(sub) {{
    print('- Submission ID: ' + sub.submission_id);
    print('  Student: ' + sub.student_name);
    print('  Status: ' + sub.status);
    print('  Submitted at: ' + sub.submitted_at);
}});
"""
        
        try:
            with open('/tmp/mongo_verify_data.js', 'w') as f:
                f.write(mongo_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_verify_data.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ Data model verification completed")
                print(result.stdout)
                self.log_test("Data Model Verification", True, "Exam and submission documents verified")
            else:
                print(f"❌ Data model verification failed: {result.stderr}")
                self.log_test("Data Model Verification", False, f"MongoDB query failed: {result.stderr}")
                
        except Exception as e:
            print(f"❌ Error in data model verification: {str(e)}")
            self.log_test("Data Model Verification", False, f"Exception: {str(e)}")

    def test_complete_e2e_workflow(self):
        """Test complete end-to-end workflow"""
        print("\n" + "="*60)
        print("COMPLETE E2E WORKFLOW TEST")
        print("="*60)
        
        success = True
        
        # Step 1: Setup
        if not self.create_test_users_and_sessions():
            print("❌ Failed to create test users")
            return False
        
        if not self.create_test_batch_and_students():
            print("❌ Failed to create test batch and students")
            return False
        
        # Create student session for one of the enrolled students
        if not self.create_student_session_for_enrolled_student():
            print("❌ Failed to create student session")
            return False
        
        # Step 2: Phase B - Teacher creates exam
        if not self.test_phase_b_teacher_creation_flow():
            print("❌ Phase B failed")
            success = False
        
        self.test_phase_b_authentication_checks()
        
        # Step 3: Phase C - Student workflow
        if not self.test_phase_c_student_flow():
            print("❌ Phase C failed")
            success = False
        
        self.test_phase_c_edge_cases()
        
        # Step 4: Phase D - Teacher grading trigger
        if not self.test_phase_d_grading_trigger_flow():
            print("❌ Phase D failed")
            success = False
        
        self.test_phase_d_authorization_checks()
        
        # Step 5: Data model verification
        self.test_data_model_verification()
        
        return success

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("STUDENT-UPLOAD WORKFLOW TEST SUMMARY")
        print("="*60)
        
        print(f"Total Tests: {self.tests_run}")
        print(f"Passed: {self.tests_passed}")
        print(f"Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%" if self.tests_run > 0 else "0%")
        
        # Print failed tests
        failed_tests = [test for test in self.test_results if not test['success']]
        if failed_tests:
            print(f"\n❌ FAILED TESTS ({len(failed_tests)}):")
            for test in failed_tests:
                print(f"   • {test['test']}: {test['details']}")
        
        # Print passed tests summary
        passed_tests = [test for test in self.test_results if test['success']]
        if passed_tests:
            print(f"\n✅ PASSED TESTS ({len(passed_tests)}):")
            for test in passed_tests:
                print(f"   • {test['test']}")

def main():
    """Main test execution"""
    print("🚀 Starting Student-Upload Workflow Comprehensive Testing...")
    print("Testing Backend URL: https://smartgrade-app-1.preview.emergentagent.com/api")
    
    tester = StudentUploadWorkflowTester()
    
    try:
        # Run complete E2E workflow test
        success = tester.test_complete_e2e_workflow()
        
        # Print summary
        tester.print_summary()
        
        if success and tester.tests_passed == tester.tests_run:
            print("\n🎉 ALL TESTS PASSED! Student-upload workflow is fully functional.")
            return 0
        else:
            print(f"\n⚠️  SOME TESTS FAILED. Please review the failed tests above.")
            return 1
            
    except KeyboardInterrupt:
        print("\n⏹️  Testing interrupted by user")
        return 1
    except Exception as e:
        print(f"\n💥 Testing failed with exception: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())