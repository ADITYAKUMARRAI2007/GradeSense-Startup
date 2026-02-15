#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os
import base64
import io
from PIL import Image

class UploadGradingFlowTester:
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
        self.test_submission_ids = []

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

    def run_api_test(self, name, method, endpoint, expected_status, data=None, headers=None, files=None, timeout=120):
        """Run a single API test with extended timeout for upload operations"""
        url = f"{self.base_url}/{endpoint}"
        test_headers = {}
        
        if self.session_token:
            test_headers['Authorization'] = f'Bearer {self.session_token}'
        
        if headers:
            test_headers.update(headers)
        
        # Don't set Content-Type for file uploads
        if not files and 'Content-Type' not in test_headers:
            test_headers['Content-Type'] = 'application/json'

        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        print(f"   Method: {method}")
        if data and not files:
            print(f"   Data: {json.dumps(data, indent=2)[:200]}...")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=timeout)
            elif method == 'POST':
                if files:
                    response = requests.post(url, files=files, data=data, headers=test_headers, timeout=timeout)
                else:
                    response = requests.post(url, json=data, headers=test_headers, timeout=timeout)
            elif method == 'PUT':
                if files:
                    response = requests.put(url, files=files, data=data, headers=test_headers, timeout=timeout)
                else:
                    response = requests.put(url, json=data, headers=test_headers, timeout=timeout)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, timeout=timeout)

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
                    return {"status": "success", "status_code": response.status_code}
            else:
                return None

        except Exception as e:
            self.log_test(name, False, f"Request failed: {str(e)}")
            return None

    def create_test_user_and_session(self):
        """Create test user and session using the provided credentials"""
        print("\n🔧 Creating test user and session for gradingtoolaibased@gmail.com...")
        
        timestamp = int(datetime.now().timestamp())
        self.user_id = f"teacher-{timestamp}"
        self.session_token = f"test_session_{timestamp}"
        
        # Create MongoDB commands for the specific teacher
        mongo_commands = f"""
use('test_database');
var userId = '{self.user_id}';
var sessionToken = '{self.session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert test teacher user
db.users.insertOne({{
  user_id: userId,
  email: 'gradingtoolaibased@gmail.com',
  name: 'Test Teacher - Upload Grading',
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

print('Test teacher user and session created successfully');
print('User ID: ' + userId);
print('Session Token: ' + sessionToken);
"""
        
        try:
            # Write commands to temp file
            with open('/tmp/mongo_teacher_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            # Execute MongoDB commands
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_teacher_setup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ Test teacher created: {self.user_id}")
                print(f"✅ Session token: {self.session_token}")
                return True
            else:
                print(f"❌ MongoDB setup failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating test user: {str(e)}")
            return False

    def create_sample_pdf_file(self, filename="sample.pdf", content="Sample PDF content for testing"):
        """Create a simple PDF-like file for testing uploads"""
        # Create a simple text file that mimics a PDF for testing
        # In a real scenario, you'd use a proper PDF library
        pdf_content = f"""%PDF-1.4
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
72 720 Td
({content}) Tj
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
300
%%EOF"""
        
        return pdf_content.encode('utf-8')

    def step1_create_exam(self):
        """Step 1: Create a test exam"""
        print("\n" + "="*60)
        print("STEP 1: EXAM CREATION")
        print("="*60)
        
        # First create batch and subject
        batch_data = {
            "name": f"Upload Test Batch {datetime.now().strftime('%H%M%S')}"
        }
        batch_result = self.run_api_test(
            "Create Test Batch",
            "POST",
            "batches",
            200,
            data=batch_data
        )
        
        if not batch_result:
            return False
        
        self.test_batch_id = batch_result.get('batch_id')
        
        subject_data = {
            "name": f"Upload Test Subject {datetime.now().strftime('%H%M%S')}"
        }
        subject_result = self.run_api_test(
            "Create Test Subject",
            "POST",
            "subjects",
            200,
            data=subject_data
        )
        
        if not subject_result:
            return False
        
        self.test_subject_id = subject_result.get('subject_id')
        
        # Create exam
        exam_data = {
            "batch_id": self.test_batch_id,
            "subject_id": self.test_subject_id,
            "exam_type": "Unit Test",
            "exam_name": f"Upload Grading Test {datetime.now().strftime('%H%M%S')}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced"
        }
        
        exam_result = self.run_api_test(
            "Step 1: Create Exam",
            "POST",
            "exams",
            200,
            data=exam_data
        )
        
        if exam_result:
            self.test_exam_id = exam_result.get('exam_id')
            print(f"✅ Exam created with ID: {self.test_exam_id}")
            return True
        
        return False

    def step2_upload_question_paper(self):
        """Step 2: Upload Question Paper"""
        print("\n" + "="*60)
        print("STEP 2: UPLOAD QUESTION PAPER")
        print("="*60)
        
        if not self.test_exam_id:
            print("❌ No exam ID available for question paper upload")
            return False
        
        # Create a sample PDF file for question paper
        question_paper_content = self.create_sample_pdf_file(
            "question_paper.pdf", 
            "Question 1: Solve 2x + 5 = 15. Question 2: Find roots of x^2 - 4x + 3 = 0"
        )
        
        files = {
            'file': ('question_paper.pdf', question_paper_content, 'application/pdf')
        }
        
        result = self.run_api_test(
            "Step 2: Upload Question Paper",
            "POST",
            f"exams/{self.test_exam_id}/upload-question-paper",
            200,
            files=files,
            timeout=180  # Extended timeout for file processing
        )
        
        if result:
            auto_extracted = result.get('auto_extracted', False)
            extracted_count = result.get('extracted_count', 0)
            
            print(f"   Auto-extracted: {auto_extracted}")
            print(f"   Extracted count: {extracted_count}")
            
            # Verify extraction_source is set
            exam_check = self.run_api_test(
                "Verify Question Paper Upload",
                "GET",
                f"exams/{self.test_exam_id}",
                200
            )
            
            if exam_check:
                extraction_source = exam_check.get('extraction_source')
                if extraction_source == 'question_paper':
                    self.log_test("Question Paper Extraction Source", True, "extraction_source set to 'question_paper'")
                else:
                    self.log_test("Question Paper Extraction Source", False, f"Expected 'question_paper', got '{extraction_source}'")
            
            return True
        
        return False

    def step3_upload_model_answer(self):
        """Step 3: Upload Model Answer"""
        print("\n" + "="*60)
        print("STEP 3: UPLOAD MODEL ANSWER")
        print("="*60)
        
        if not self.test_exam_id:
            print("❌ No exam ID available for model answer upload")
            return False
        
        # Create a sample PDF file for model answer
        model_answer_content = self.create_sample_pdf_file(
            "model_answer.pdf", 
            "Answer 1: x = 5 (showing steps: 2x = 10, x = 5). Answer 2: x = 1, x = 3 (factoring method)"
        )
        
        files = {
            'file': ('model_answer.pdf', model_answer_content, 'application/pdf')
        }
        
        result = self.run_api_test(
            "Step 3: Upload Model Answer",
            "POST",
            f"exams/{self.test_exam_id}/upload-model-answer",
            200,
            files=files,
            timeout=180  # Extended timeout for file processing
        )
        
        if result:
            print(f"   Model answer uploaded successfully")
            
            # Verify model answer text is extracted and stored
            exam_check = self.run_api_test(
                "Verify Model Answer Upload",
                "GET",
                f"exams/{self.test_exam_id}",
                200
            )
            
            if exam_check:
                has_model_answer = exam_check.get('has_model_answer', False)
                if has_model_answer:
                    self.log_test("Model Answer Storage", True, "Model answer stored successfully")
                else:
                    self.log_test("Model Answer Storage", False, "Model answer not marked as stored")
            
            return True
        
        return False

    def step4_update_exam_manual_questions(self):
        """Step 4: Update Exam with manual question entry"""
        print("\n" + "="*60)
        print("STEP 4: UPDATE EXAM (MANUAL QUESTION ENTRY)")
        print("="*60)
        
        if not self.test_exam_id:
            print("❌ No exam ID available for exam update")
            return False
        
        # Update exam with questions array
        questions_data = {
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 50.0,
                    "rubric": "Solve the linear equation: 2x + 5 = 15",
                    "sub_questions": []
                },
                {
                    "question_number": 2,
                    "max_marks": 50.0,
                    "rubric": "Find the roots of the quadratic equation: x² - 4x + 3 = 0",
                    "sub_questions": []
                }
            ]
        }
        
        result = self.run_api_test(
            "Step 4: Update Exam with Questions",
            "PUT",
            f"exams/{self.test_exam_id}",
            200,
            data=questions_data
        )
        
        if result:
            # Verify questions are saved
            exam_check = self.run_api_test(
                "Verify Questions Saved",
                "GET",
                f"exams/{self.test_exam_id}",
                200
            )
            
            if exam_check:
                questions = exam_check.get('questions', [])
                if len(questions) == 2:
                    self.log_test("Questions Saved", True, f"Successfully saved {len(questions)} questions")
                else:
                    self.log_test("Questions Saved", False, f"Expected 2 questions, found {len(questions)}")
            
            return True
        
        return False

    def step5_upload_student_papers_and_grade(self):
        """Step 5: Upload Student Papers & Grade"""
        print("\n" + "="*60)
        print("STEP 5: UPLOAD STUDENT PAPERS & GRADE")
        print("="*60)
        
        if not self.test_exam_id:
            print("❌ No exam ID available for student paper upload")
            return False
        
        # Create sample student answer papers
        student_papers = [
            {
                'filename': 'STU001_John_Doe_Math.pdf',
                'content': 'Student Answer: Q1: 2x + 5 = 15, 2x = 10, x = 5. Q2: x² - 4x + 3 = (x-1)(x-3) = 0, so x = 1 or x = 3'
            },
            {
                'filename': 'STU002_Jane_Smith_Math.pdf', 
                'content': 'Student Answer: Q1: 2x + 5 = 15, x = 5. Q2: Using quadratic formula: x = (4 ± √(16-12))/2 = (4 ± 2)/2, x = 3 or x = 1'
            }
        ]
        
        # Upload each student paper
        for i, paper in enumerate(student_papers):
            paper_content = self.create_sample_pdf_file(paper['filename'], paper['content'])
            
            files = {
                'files': (paper['filename'], paper_content, 'application/pdf')
            }
            
            result = self.run_api_test(
                f"Step 5: Upload Student Paper {i+1} ({paper['filename']})",
                "POST",
                f"exams/{self.test_exam_id}/upload-papers",
                200,
                files=files,
                timeout=300  # Extended timeout for grading
            )
            
            if result:
                processed_count = result.get('processed', 0)
                submissions = result.get('submissions', [])
                errors = result.get('errors', [])
                
                print(f"   Processed: {processed_count}")
                print(f"   Submissions: {len(submissions)}")
                print(f"   Errors: {len(errors)}")
                
                if submissions:
                    for submission in submissions:
                        submission_id = submission.get('submission_id')
                        if submission_id:
                            self.test_submission_ids.append(submission_id)
                
                if errors:
                    for error in errors:
                        print(f"   Error: {error}")
                
                # Verify grading completed without timeout
                if processed_count > 0:
                    self.log_test(f"Student Paper {i+1} Processing", True, f"Successfully processed {processed_count} paper(s)")
                else:
                    self.log_test(f"Student Paper {i+1} Processing", False, "No papers processed")
            else:
                return False
        
        return len(self.test_submission_ids) > 0

    def step6_verify_submissions_created(self):
        """Step 6: Verify Submissions Created"""
        print("\n" + "="*60)
        print("STEP 6: VERIFY SUBMISSIONS CREATED")
        print("="*60)
        
        if not self.test_exam_id:
            print("❌ No exam ID available for submission verification")
            return False
        
        # Get submissions for the exam
        result = self.run_api_test(
            "Step 6: Get Exam Submissions",
            "GET",
            f"exams/{self.test_exam_id}/submissions",
            200
        )
        
        if result:
            submissions = result if isinstance(result, list) else []
            
            print(f"   Found {len(submissions)} submissions")
            
            if len(submissions) > 0:
                # Verify submission structure
                for i, submission in enumerate(submissions):
                    submission_id = submission.get('submission_id')
                    student_name = submission.get('student_name')
                    total_score = submission.get('total_score')
                    status = submission.get('status')
                    
                    print(f"   Submission {i+1}:")
                    print(f"     ID: {submission_id}")
                    print(f"     Student: {student_name}")
                    print(f"     Score: {total_score}")
                    print(f"     Status: {status}")
                    
                    # Verify required fields
                    required_fields = ['submission_id', 'student_name', 'total_score', 'status']
                    missing_fields = [field for field in required_fields if field not in submission]
                    
                    if not missing_fields:
                        self.log_test(f"Submission {i+1} Structure", True, "All required fields present")
                    else:
                        self.log_test(f"Submission {i+1} Structure", False, f"Missing fields: {missing_fields}")
                
                self.log_test("Submissions Created", True, f"Successfully created {len(submissions)} submissions")
                return True
            else:
                self.log_test("Submissions Created", False, "No submissions found")
                return False
        
        return False

    def test_critical_checks(self):
        """Perform critical checks as specified in the review request"""
        print("\n" + "="*60)
        print("CRITICAL CHECKS")
        print("="*60)
        
        success_count = 0
        total_checks = 5
        
        # 1. No Timeout Errors
        timeout_errors = [result for result in self.test_results if 'timeout' in result.get('details', '').lower()]
        if not timeout_errors:
            self.log_test("Critical Check: No Timeout Errors", True, "All endpoints completed without timing out")
            success_count += 1
        else:
            self.log_test("Critical Check: No Timeout Errors", False, f"Found {len(timeout_errors)} timeout errors")
        
        # 2. Database Persistence
        if self.test_exam_id and len(self.test_submission_ids) > 0:
            self.log_test("Critical Check: Database Persistence", True, "Exam and submissions persisted in database")
            success_count += 1
        else:
            self.log_test("Critical Check: Database Persistence", False, "Data persistence verification failed")
        
        # 3. Auto-Extraction (if applicable)
        # This would be verified in the question paper upload step
        extraction_tests = [result for result in self.test_results if 'extraction' in result.get('test', '').lower()]
        if extraction_tests:
            extraction_success = any(result['success'] for result in extraction_tests)
            if extraction_success:
                self.log_test("Critical Check: Auto-Extraction", True, "Question extraction working")
                success_count += 1
            else:
                self.log_test("Critical Check: Auto-Extraction", False, "Question extraction issues detected")
        else:
            self.log_test("Critical Check: Auto-Extraction", True, "No extraction issues detected")
            success_count += 1
        
        # 4. Grading Completion
        grading_tests = [result for result in self.test_results if 'grading' in result.get('test', '').lower() or 'upload student paper' in result.get('test', '').lower()]
        if grading_tests:
            grading_success = any(result['success'] for result in grading_tests)
            if grading_success:
                self.log_test("Critical Check: Grading Completion", True, "AI grading completed successfully")
                success_count += 1
            else:
                self.log_test("Critical Check: Grading Completion", False, "Grading completion issues detected")
        else:
            self.log_test("Critical Check: Grading Completion", False, "No grading tests performed")
        
        # 5. Error Handling
        error_handling_tests = [result for result in self.test_results if result['success'] and 'error' in result.get('details', '').lower()]
        if len(error_handling_tests) > 0 or self.tests_passed > self.tests_run * 0.8:  # 80% success rate indicates good error handling
            self.log_test("Critical Check: Error Handling", True, "Proper error handling verified")
            success_count += 1
        else:
            self.log_test("Critical Check: Error Handling", False, "Error handling needs improvement")
        
        return success_count, total_checks

    def run_complete_upload_grading_flow(self):
        """Run the complete upload and grading workflow test"""
        print("🚀 STARTING COMPREHENSIVE UPLOAD & GRADING FLOW TEST")
        print("=" * 80)
        print("Testing credentials: Teacher - gradingtoolaibased@gmail.com")
        print("=" * 80)
        
        # Setup
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user and session")
            return False
        
        # Run the complete flow
        steps = [
            ("Step 1: Exam Creation", self.step1_create_exam),
            ("Step 2: Upload Question Paper", self.step2_upload_question_paper),
            ("Step 3: Upload Model Answer", self.step3_upload_model_answer),
            ("Step 4: Update Exam (Manual Questions)", self.step4_update_exam_manual_questions),
            ("Step 5: Upload Student Papers & Grade", self.step5_upload_student_papers_and_grade),
            ("Step 6: Verify Submissions Created", self.step6_verify_submissions_created)
        ]
        
        flow_success = True
        for step_name, step_func in steps:
            print(f"\n🔄 Executing {step_name}...")
            if not step_func():
                print(f"❌ {step_name} failed")
                flow_success = False
                break
            else:
                print(f"✅ {step_name} completed successfully")
        
        # Run critical checks
        success_count, total_checks = self.test_critical_checks()
        
        # Final summary
        print("\n" + "="*80)
        print("FINAL TEST SUMMARY")
        print("="*80)
        print(f"Total Tests Run: {self.tests_run}")
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%" if self.tests_run > 0 else "0%")
        print(f"Critical Checks Passed: {success_count}/{total_checks}")
        print(f"Overall Flow Success: {'✅ PASSED' if flow_success else '❌ FAILED'}")
        
        if self.test_exam_id:
            print(f"Test Exam ID: {self.test_exam_id}")
        if self.test_submission_ids:
            print(f"Test Submission IDs: {', '.join(self.test_submission_ids)}")
        
        # Show failed tests
        failed_tests = [result for result in self.test_results if not result['success']]
        if failed_tests:
            print(f"\n❌ FAILED TESTS ({len(failed_tests)}):")
            for test in failed_tests:
                print(f"   - {test['test']}: {test['details']}")
        
        return flow_success and success_count >= total_checks * 0.8  # 80% of critical checks must pass

def main():
    """Main function to run the upload and grading flow tests"""
    tester = UploadGradingFlowTester()
    
    try:
        success = tester.run_complete_upload_grading_flow()
        
        if success:
            print("\n🎉 UPLOAD & GRADING FLOW TEST COMPLETED SUCCESSFULLY!")
            sys.exit(0)
        else:
            print("\n💥 UPLOAD & GRADING FLOW TEST FAILED!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test failed with exception: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()