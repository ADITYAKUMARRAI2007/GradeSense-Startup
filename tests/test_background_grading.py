#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os
import time

class BackgroundGradingTester:
    def __init__(self):
        self.base_url = "https://smartgrade-app-1.preview.emergentagent.com/api"
        self.session_token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []

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

    def run_api_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        test_headers = {'Content-Type': 'application/json'}
        
        if self.session_token:
            test_headers['Authorization'] = f'Bearer {self.session_token}'
        
        if headers:
            test_headers.update(headers)

        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers, timeout=10)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, timeout=10)

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
        self.user_id = f"test-user-{timestamp}"
        self.session_token = f"test_session_{timestamp}"
        
        # Create MongoDB commands
        mongo_commands = f"""
use('test_database');
var userId = '{self.user_id}';
var sessionToken = '{self.session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert test user
db.users.insertOne({{
  user_id: userId,
  email: 'test.user.{timestamp}@example.com',
  name: 'Test Teacher',
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

print('Test user and session created successfully');
print('User ID: ' + userId);
print('Session Token: ' + sessionToken);
"""
        
        try:
            # Write commands to temp file
            with open('/tmp/mongo_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            # Execute MongoDB commands
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_setup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ Test user created: {self.user_id}")
                print(f"✅ Session token: {self.session_token}")
                return True
            else:
                print(f"❌ MongoDB setup failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating test user: {str(e)}")
            return False

    def create_test_pdf_files(self):
        """Create simple test PDF files programmatically"""
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            import io
            
            test_files = []
            
            # Create 3 test PDF files with different student info
            students = [
                {"id": "STU001", "name": "TestStudent", "subject": "Maths"},
                {"id": "STU002", "name": "AnotherStudent", "subject": "Subject"},
                {"id": "123", "name": "John Doe", "subject": "Test"}
            ]
            
            for i, student in enumerate(students):
                # Create PDF in memory
                buffer = io.BytesIO()
                p = canvas.Canvas(buffer, pagesize=letter)
                
                # Add student info and some content
                p.drawString(100, 750, f"Student ID: {student['id']}")
                p.drawString(100, 730, f"Name: {student['name']}")
                p.drawString(100, 710, f"Subject: {student['subject']}")
                p.drawString(100, 680, "Answer Sheet")
                p.drawString(100, 650, "Question 1: This is my answer to question 1...")
                p.drawString(100, 620, "Question 2: This is my answer to question 2...")
                
                p.showPage()
                p.save()
                
                # Get PDF bytes
                pdf_bytes = buffer.getvalue()
                buffer.close()
                
                filename = f"{student['id']}_{student['name']}_{student['subject']}.pdf"
                test_files.append({
                    'filename': filename,
                    'content': pdf_bytes
                })
                
                print(f"   Created: {filename} ({len(pdf_bytes)} bytes)")
            
            return test_files
            
        except ImportError:
            print("⚠️  reportlab not available, creating mock PDF files...")
            # Create mock PDF files with minimal PDF structure
            test_files = []
            
            students = [
                {"id": "STU001", "name": "TestStudent", "subject": "Maths"},
                {"id": "STU002", "name": "AnotherStudent", "subject": "Subject"},
                {"id": "123", "name": "John Doe", "subject": "Test"}
            ]
            
            # Minimal PDF header and content
            pdf_template = b"""%PDF-1.4
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
300
%%EOF"""
            
            for student in students:
                filename = f"{student['id']}_{student['name']}_{student['subject']}.pdf"
                test_files.append({
                    'filename': filename,
                    'content': pdf_template
                })
                print(f"   Created mock: {filename} ({len(pdf_template)} bytes)")
            
            return test_files
        
        except Exception as e:
            print(f"❌ Error creating test PDF files: {str(e)}")
            return None

    def test_background_grading_system(self):
        """Test the critical P0 background grading system for 30+ papers"""
        print("\n🔥 CRITICAL P0 TESTING: Background Grading System for 30+ Papers")
        print("=" * 80)
        
        # Phase 1: Create batch and subject
        batch_data = {
            "name": f"BG Test Batch {datetime.now().strftime('%H%M%S')}"
        }
        batch_result = self.run_api_test(
            "Create Test Batch",
            "POST",
            "batches",
            200,
            data=batch_data
        )
        
        if not batch_result:
            print("❌ Failed to create test batch")
            return None
        
        batch_id = batch_result.get('batch_id')
        
        subject_data = {
            "name": f"BG Test Subject {datetime.now().strftime('%H%M%S')}"
        }
        subject_result = self.run_api_test(
            "Create Test Subject",
            "POST",
            "subjects",
            200,
            data=subject_data
        )
        
        if not subject_result:
            print("❌ Failed to create test subject")
            return None
        
        subject_id = subject_result.get('subject_id')
        
        # Phase 2: Create exam for background grading test
        timestamp = datetime.now().strftime('%H%M%S')
        bg_exam_data = {
            "batch_id": batch_id,
            "subject_id": subject_id,
            "exam_type": "Background Grading Test",
            "exam_name": f"BG Grading Test {timestamp}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 50.0,
                    "rubric": "Solve algebraic equations with proper working"
                },
                {
                    "question_number": 2,
                    "max_marks": 50.0,
                    "rubric": "Analyze quadratic functions and graph properties"
                }
            ]
        }
        
        exam_result = self.run_api_test(
            "Create Exam for Background Grading Test",
            "POST",
            "exams",
            200,
            data=bg_exam_data
        )
        
        if not exam_result:
            print("❌ Failed to create exam for background grading test")
            return None
        
        bg_exam_id = exam_result.get('exam_id')
        print(f"✅ Created background grading test exam: {bg_exam_id}")
        
        # Phase 3: Create test PDF files programmatically
        print("\n📄 Creating test PDF files...")
        test_files = self.create_test_pdf_files()
        
        if not test_files:
            print("❌ Failed to create test PDF files")
            return None
        
        print(f"✅ Created {len(test_files)} test PDF files")
        
        # Phase 4: Test background grading endpoint
        print("\n🚀 Testing background grading endpoint...")
        
        # Prepare multipart form data
        files_for_upload = []
        for file_data in test_files:
            files_for_upload.append(
                ('files', (file_data['filename'], file_data['content'], 'application/pdf'))
            )
        
        # Make request to background grading endpoint
        url = f"{self.base_url}/exams/{bg_exam_id}/grade-papers-bg"
        headers = {'Authorization': f'Bearer {self.session_token}'}
        
        try:
            response = requests.post(url, files=files_for_upload, headers=headers, timeout=30)
            
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                bg_result = response.json()
                job_id = bg_result.get('job_id')
                
                if job_id:
                    self.log_test("Background Grading Job Creation", True, f"Job ID: {job_id}")
                    
                    # Verify response structure
                    expected_fields = ['job_id', 'status', 'total_papers', 'message']
                    has_all_fields = all(field in bg_result for field in expected_fields)
                    
                    if has_all_fields:
                        self.log_test("Background Grading Response Structure", True, 
                            f"All required fields present: {list(bg_result.keys())}")
                    else:
                        missing = [f for f in expected_fields if f not in bg_result]
                        self.log_test("Background Grading Response Structure", False, 
                            f"Missing fields: {missing}")
                    
                    # Verify initial status is 'pending'
                    if bg_result.get('status') == 'pending':
                        self.log_test("Initial Job Status", True, "Status is 'pending' as expected")
                    else:
                        self.log_test("Initial Job Status", False, 
                            f"Expected 'pending', got '{bg_result.get('status')}'")
                    
                    # Phase 5: Monitor job progress
                    print("\n⏳ Monitoring job progress...")
                    self.monitor_background_job_progress(job_id)
                    
                    # Phase 6: Verify fix resolved issues
                    print("\n🔍 Verifying fix resolved 'read of closed file' errors...")
                    self.verify_background_grading_fix(job_id, bg_exam_id)
                    
                    return bg_result
                else:
                    self.log_test("Background Grading Job Creation", False, "No job_id in response")
            else:
                error_msg = "Unknown error"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', 'No error details')
                except:
                    error_msg = response.text[:200]
                
                self.log_test("Background Grading Job Creation", False, 
                    f"Status {response.status_code}: {error_msg}")
        
        except Exception as e:
            self.log_test("Background Grading Job Creation", False, f"Request failed: {str(e)}")
        
        return None

    def monitor_background_job_progress(self, job_id: str):
        """Monitor background job progress with polling"""
        max_polls = 30  # Maximum 60 seconds (30 polls * 2 seconds)
        poll_count = 0
        
        while poll_count < max_polls:
            poll_count += 1
            
            # Poll job status
            job_status = self.run_api_test(
                f"Poll Job Status (attempt {poll_count})",
                "GET",
                f"grading-jobs/{job_id}",
                200
            )
            
            if job_status:
                status = job_status.get('status')
                processed = job_status.get('processed_papers', 0)
                total = job_status.get('total_papers', 0)
                successful = job_status.get('successful', 0)
                failed = job_status.get('failed', 0)
                
                print(f"   Status: {status}, Progress: {processed}/{total}, Success: {successful}, Failed: {failed}")
                
                # Check for completion
                if status == 'completed':
                    self.log_test("Background Job Completion", True, 
                        f"Job completed successfully: {successful} successful, {failed} failed")
                    
                    # Verify submissions were created
                    submissions = job_status.get('submissions', [])
                    if submissions and len(submissions) > 0:
                        self.log_test("Submissions Creation", True, 
                            f"Created {len(submissions)} submissions")
                        
                        # Store for verification
                        self.bg_submissions = submissions
                    else:
                        self.log_test("Submissions Creation", False, "No submissions created")
                    
                    # Verify progress tracking worked
                    if processed == total and processed > 0:
                        self.log_test("Progress Tracking", True, 
                            f"All {total} papers processed")
                    else:
                        self.log_test("Progress Tracking", False, 
                            f"Progress mismatch: {processed}/{total}")
                    
                    return job_status
                
                elif status == 'failed':
                    error = job_status.get('error', 'Unknown error')
                    self.log_test("Background Job Completion", False, 
                        f"Job failed: {error}")
                    return job_status
                
                elif status == 'processing':
                    # Job is processing, continue polling
                    time.sleep(2)
                    continue
                
                else:
                    # Still pending, continue polling
                    time.sleep(2)
                    continue
            else:
                self.log_test(f"Poll Job Status (attempt {poll_count})", False, 
                    "Failed to get job status")
                time.sleep(2)
        
        # Timeout reached
        self.log_test("Background Job Completion", False, 
            f"Job did not complete within {max_polls * 2} seconds")
        return None

    def verify_background_grading_fix(self, job_id: str, exam_id: str):
        """Verify the fix resolved 'read of closed file' errors"""
        print("🔍 Verifying background grading fix...")
        
        # Check backend logs for errors
        try:
            result = subprocess.run([
                'tail', '-n', '100', '/var/log/supervisor/backend.err.log'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                log_content = result.stdout
                
                # Check for 'read of closed file' errors
                if 'read of closed file' in log_content.lower():
                    self.log_test("No 'Read of Closed File' Errors", False, 
                        "Found 'read of closed file' errors in logs")
                else:
                    self.log_test("No 'Read of Closed File' Errors", True, 
                        "No 'read of closed file' errors found in recent logs")
                
                # Check for successful processing messages
                job_messages = [
                    f"Reading 3 files for job {job_id}",
                    "File data type: <class 'bytes'>",
                    f"Job {job_id}"
                ]
                
                found_messages = []
                for msg in job_messages:
                    if msg in log_content:
                        found_messages.append(msg)
                
                if found_messages:
                    self.log_test("Background Processing Log Messages", True, 
                        f"Found expected log messages: {len(found_messages)}/{len(job_messages)}")
                else:
                    self.log_test("Background Processing Log Messages", False, 
                        "Expected log messages not found")
            else:
                self.log_test("Backend Log Check", False, 
                    f"Failed to read backend logs: {result.stderr}")
        
        except Exception as e:
            self.log_test("Backend Log Check", False, f"Error checking logs: {str(e)}")
        
        # Verify submissions were created in database
        if hasattr(self, 'bg_submissions') and self.bg_submissions:
            # Check if submissions exist in database by querying submissions endpoint
            submissions_result = self.run_api_test(
                "Verify Submissions in Database",
                "GET",
                f"submissions?exam_id={exam_id}",
                200
            )
            
            if submissions_result and len(submissions_result) > 0:
                self.log_test("Database Submissions Verification", True, 
                    f"Found {len(submissions_result)} submissions in database")
                
                # Verify submission structure
                first_sub = submissions_result[0]
                required_fields = ['submission_id', 'student_name', 'total_score', 'percentage', 'status']
                has_required = all(field in first_sub for field in required_fields)
                
                if has_required:
                    self.log_test("Submission Structure Verification", True, 
                        "Submissions have correct structure")
                else:
                    missing = [f for f in required_fields if f not in first_sub]
                    self.log_test("Submission Structure Verification", False, 
                        f"Missing fields: {missing}")
            else:
                self.log_test("Database Submissions Verification", False, 
                    "No submissions found in database")

    def run_test(self):
        """Run the background grading test"""
        print("🚀 Starting Background Grading System Test...")
        print(f"📍 Base URL: {self.base_url}")
        
        # Create test user and session
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user. Exiting.")
            return False
        
        # Run the background grading test
        self.test_background_grading_system()
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"🏁 TEST SUMMARY")
        print(f"{'='*60}")
        print(f"✅ Tests Passed: {self.tests_passed}/{self.tests_run}")
        print(f"❌ Tests Failed: {self.tests_run - self.tests_passed}/{self.tests_run}")
        print(f"📊 Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%")
        
        if self.tests_passed == self.tests_run:
            print("🎉 ALL TESTS PASSED!")
        else:
            print("⚠️  Some tests failed. Check details above.")
            
        return self.tests_passed == self.tests_run

def main():
    tester = BackgroundGradingTester()
    success = tester.run_test()
    
    # Save detailed results
    results = {
        "timestamp": datetime.now().isoformat(),
        "total_tests": tester.tests_run,
        "passed_tests": tester.tests_passed,
        "success_rate": (tester.tests_passed / tester.tests_run * 100) if tester.tests_run > 0 else 0,
        "test_details": tester.test_results
    }
    
    with open('/app/background_grading_test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())