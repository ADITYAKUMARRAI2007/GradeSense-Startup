#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os
import base64

class GradeSenseMultiFormatTester:
    def __init__(self):
        self.base_url = "https://smartgrade-app-1.preview.emergentagent.com/api"
        self.session_token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        self.test_exam_id = None

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
  email: 'test.multiformat.{timestamp}@example.com',
  name: 'Test Multi-Format Teacher',
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
            with open('/tmp/mongo_multiformat_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            # Execute MongoDB commands
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_multiformat_setup.js'
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

    def run_multipart_upload_test(self, name, endpoint, file_content, filename, content_type, expected_status=200):
        """Helper method to run multipart file upload tests"""
        url = f"{self.base_url}/{endpoint}"
        
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        print(f"   File: {filename} ({content_type})")
        
        try:
            # Prepare multipart form data
            files = {
                'file': (filename, file_content, content_type)
            }
            
            headers = {}
            if self.session_token:
                headers['Authorization'] = f'Bearer {self.session_token}'
            
            response = requests.post(url, files=files, headers=headers, timeout=30)
            
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

    def setup_test_environment(self):
        """Setup test environment with batch, subject, and exam"""
        print("\n🏗️  Setting up test environment...")
        
        # Create batch
        batch_data = {
            "name": f"Multi-Format Test Batch {datetime.now().strftime('%H%M%S')}"
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
        
        # Create subject
        subject_data = {
            "name": f"Multi-Format Test Subject {datetime.now().strftime('%H%M%S')}"
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
            "exam_type": "Multi-Format Test",
            "exam_name": f"Multi-Format Upload Test {datetime.now().strftime('%H%M%S')}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 100.0,
                    "rubric": "Test question for multi-format upload"
                }
            ]
        }
        
        exam_result = self.run_api_test(
            "Create Test Exam",
            "POST",
            "exams",
            200,
            data=exam_data
        )
        
        if exam_result:
            self.test_exam_id = exam_result.get('exam_id')
            print(f"✅ Test environment setup complete. Exam ID: {self.test_exam_id}")
            return True
        
        return False

    def test_poppler_dependency_fix(self):
        """Test that poppler-utils dependency is working (no PDF processing crashes)"""
        print("\n🔧 Testing Poppler-Utils Dependency Fix...")
        
        # Check if poppler-utils is installed
        try:
            result = subprocess.run(['pdftoppm', '-h'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0 or "Usage:" in result.stderr:
                self.log_test("Poppler-Utils Installation", True, "pdftoppm command available")
            else:
                self.log_test("Poppler-Utils Installation", False, "pdftoppm command not working")
        except FileNotFoundError:
            self.log_test("Poppler-Utils Installation", False, "pdftoppm command not found")
        except Exception as e:
            self.log_test("Poppler-Utils Installation", False, f"Error checking poppler: {str(e)}")

    def test_multi_format_model_answer_upload(self):
        """Test multi-format file upload for model answers"""
        print("\n📄 Testing Multi-Format Model Answer Upload...")
        
        if not self.test_exam_id:
            print("⚠️  Skipping multi-format upload test - no exam created")
            return None
        
        # Test 1: PDF upload
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000074 00000 n \n0000000120 00000 n \ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n179\n%%EOF"
        
        pdf_result = self.run_multipart_upload_test(
            "Model Answer Upload - PDF Format",
            f"exams/{self.test_exam_id}/upload-model-answer",
            pdf_content,
            "model_answer.pdf",
            "application/pdf"
        )
        
        # Test 2: Word document upload
        word_content = b"PK\x03\x04\x14\x00\x00\x00\x08\x00"  # Minimal DOCX header
        
        word_result = self.run_multipart_upload_test(
            "Model Answer Upload - Word Format",
            f"exams/{self.test_exam_id}/upload-model-answer",
            word_content,
            "model_answer.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        
        # Test 3: Image upload
        image_content = base64.b64decode("/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwA/8A8A")
        
        image_result = self.run_multipart_upload_test(
            "Model Answer Upload - Image Format (JPG)",
            f"exams/{self.test_exam_id}/upload-model-answer",
            image_content,
            "model_answer.jpg",
            "image/jpeg"
        )
        
        # Test 4: ZIP upload
        zip_content = b"PK\x03\x04\x14\x00\x00\x00\x00\x00"  # Minimal ZIP header
        
        zip_result = self.run_multipart_upload_test(
            "Model Answer Upload - ZIP Format",
            f"exams/{self.test_exam_id}/upload-model-answer",
            zip_content,
            "model_answers.zip",
            "application/zip"
        )
        
        return [pdf_result, word_result, image_result, zip_result]

    def test_multi_format_question_paper_upload(self):
        """Test multi-format file upload for question papers"""
        print("\n📋 Testing Multi-Format Question Paper Upload...")
        
        if not self.test_exam_id:
            print("⚠️  Skipping question paper upload test - no exam created")
            return None
        
        # Test PDF upload for question paper
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000074 00000 n \n0000000120 00000 n \ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n179\n%%EOF"
        
        pdf_result = self.run_multipart_upload_test(
            "Question Paper Upload - PDF Format",
            f"exams/{self.test_exam_id}/upload-question-paper",
            pdf_content,
            "question_paper.pdf",
            "application/pdf"
        )
        
        # Test Word document upload
        word_content = b"PK\x03\x04\x14\x00\x00\x00\x08\x00"
        
        word_result = self.run_multipart_upload_test(
            "Question Paper Upload - Word Format",
            f"exams/{self.test_exam_id}/upload-question-paper",
            word_content,
            "question_paper.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        
        # Test ZIP upload
        zip_content = b"PK\x03\x04\x14\x00\x00\x00\x00\x00"
        
        zip_result = self.run_multipart_upload_test(
            "Question Paper Upload - ZIP Format",
            f"exams/{self.test_exam_id}/upload-question-paper",
            zip_content,
            "question_papers.zip",
            "application/zip"
        )
        
        return [pdf_result, word_result, zip_result]

    def test_file_processing_error_handling(self):
        """Test error handling for unsupported file formats and corrupted files"""
        print("\n🚫 Testing File Processing Error Handling...")
        
        if not self.test_exam_id:
            print("⚠️  Skipping error handling test - no exam created")
            return None
        
        # Test 1: Unsupported file format
        unsupported_content = b"This is not a valid file format"
        
        unsupported_result = self.run_multipart_upload_test(
            "Upload Unsupported File Format (should fail gracefully)",
            f"exams/{self.test_exam_id}/upload-model-answer",
            unsupported_content,
            "unsupported.xyz",
            "application/octet-stream",
            expected_status=400  # Should fail with 400
        )
        
        # Test 2: Corrupted PDF
        corrupted_pdf = b"corrupted pdf content"
        
        corrupted_result = self.run_multipart_upload_test(
            "Upload Corrupted PDF (should fail gracefully)",
            f"exams/{self.test_exam_id}/upload-model-answer",
            corrupted_pdf,
            "corrupted.pdf",
            "application/pdf",
            expected_status=400  # Should fail with 400
        )
        
        # Test 3: Empty file
        empty_result = self.run_multipart_upload_test(
            "Upload Empty File (should fail)",
            f"exams/{self.test_exam_id}/upload-model-answer",
            b"",
            "empty.pdf",
            "application/pdf",
            expected_status=400  # Should fail with 400
        )
        
        return [unsupported_result, corrupted_result, empty_result]

    def test_backend_logs_for_errors(self):
        """Check backend logs for any critical errors"""
        print("\n📋 Checking Backend Logs for Errors...")
        
        try:
            # Check supervisor backend logs
            result = subprocess.run([
                'tail', '-n', '100', '/var/log/supervisor/backend.err.log'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                error_log = result.stdout
                
                # Check for specific errors
                critical_errors = [
                    "poppler not installed",
                    "DialogDescription is not defined", 
                    "pdf_to_base64_images",
                    "ModuleNotFoundError",
                    "ImportError"
                ]
                
                found_errors = []
                for error in critical_errors:
                    if error.lower() in error_log.lower():
                        found_errors.append(error)
                
                if found_errors:
                    self.log_test("Backend Error Log Check", False, 
                        f"Found critical errors: {', '.join(found_errors)}")
                else:
                    self.log_test("Backend Error Log Check", True, 
                        "No critical errors found in backend logs")
                
                # Check for successful file processing
                success_indicators = [
                    "File converted to images successfully",
                    "Model answer uploaded successfully",
                    "Question paper uploaded successfully"
                ]
                
                found_success = []
                for indicator in success_indicators:
                    if indicator.lower() in error_log.lower():
                        found_success.append(indicator)
                
                if found_success:
                    self.log_test("File Processing Success Indicators", True,
                        f"Found success indicators: {', '.join(found_success)}")
                
            else:
                self.log_test("Backend Error Log Check", False, 
                    "Could not access backend error logs")
                
        except Exception as e:
            self.log_test("Backend Error Log Check", False, 
                f"Error checking logs: {str(e)}")

    def test_grading_workflow_with_multi_format(self):
        """Test grading workflow with multi-format file processing"""
        print("\n⚖️  Testing Grading Workflow with Multi-Format Files...")
        
        if not self.test_exam_id:
            print("⚠️  Skipping grading workflow test - no exam created")
            return None
        
        # Test grading endpoint
        grading_result = self.run_api_test(
            "Grade Student Submissions with Multi-Format Processing",
            "POST",
            f"exams/{self.test_exam_id}/grade-student-submissions",
            200
        )
        
        if grading_result:
            # Check if grading was successful
            grading_status = grading_result.get("status", "")
            if "success" in grading_status.lower() or "graded" in grading_status.lower():
                self.log_test("Multi-Format Grading Success", True, 
                    f"Grading completed: {grading_status}")
            else:
                self.log_test("Multi-Format Grading Success", False, 
                    f"Grading may have failed: {grading_status}")
        
        return grading_result

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("🔥 MULTI-FORMAT FILE UPLOAD TEST SUMMARY")
        print("="*60)
        print(f"Total Tests: {self.tests_run}")
        print(f"Passed: {self.tests_passed}")
        print(f"Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%" if self.tests_run > 0 else "0%")
        
        if self.tests_run - self.tests_passed > 0:
            print("\n❌ FAILED TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"   • {result['test']}: {result['details']}")
        
        print("\n✅ PASSED TESTS:")
        for result in self.test_results:
            if result["success"]:
                print(f"   • {result['test']}")
        
        print("="*60)

    def run_all_multi_format_tests(self):
        """Run all multi-format file upload tests"""
        print("🔥 STARTING MULTI-FORMAT FILE UPLOAD TESTING")
        print("="*60)
        
        # Setup
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user and session")
            return False
        
        if not self.setup_test_environment():
            print("❌ Failed to setup test environment")
            return False
        
        # Test poppler dependency fix
        self.test_poppler_dependency_fix()
        
        # Test multi-format uploads
        self.test_multi_format_model_answer_upload()
        self.test_multi_format_question_paper_upload()
        
        # Test grading with multi-format files
        self.test_grading_workflow_with_multi_format()
        
        # Test error handling
        self.test_file_processing_error_handling()
        
        # Check backend logs for errors
        self.test_backend_logs_for_errors()
        
        # Summary
        self.print_summary()
        
        return self.tests_passed == self.tests_run

if __name__ == "__main__":
    tester = GradeSenseMultiFormatTester()
    success = tester.run_all_multi_format_tests()
    sys.exit(0 if success else 1)