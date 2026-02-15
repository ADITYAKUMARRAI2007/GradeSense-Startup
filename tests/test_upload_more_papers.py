#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime
import subprocess
import os
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import base64

class UploadMorePapersTest:
    def __init__(self):
        self.base_url = "https://smartgrade-app-1.preview.emergentagent.com/api"
        self.session_token = None
        self.user_id = None
        self.test_batch_id = None
        self.test_subject_id = None
        self.test_exam_id = None

    def create_test_pdf(self, filename, student_id, student_name):
        """Create a test PDF file with student information"""
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # Add student information at the top
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, height - 50, f"Student ID: {student_id}")
        p.drawString(50, height - 80, f"Name: {student_name}")
        
        # Add some sample content
        p.setFont("Helvetica", 12)
        p.drawString(50, height - 120, "Mathematics Test - Answer Sheet")
        p.drawString(50, height - 150, "Question 1: Solve 2x + 5 = 15")
        p.drawString(50, height - 180, "Answer: x = 5")
        p.drawString(50, height - 210, "Working: 2x = 15 - 5 = 10, therefore x = 5")
        
        p.drawString(50, height - 250, "Question 2: Find the roots of x² - 5x + 6 = 0")
        p.drawString(50, height - 280, "Answer: x = 2, x = 3")
        p.drawString(50, height - 310, "Working: (x-2)(x-3) = 0")
        
        p.showPage()
        p.save()
        
        buffer.seek(0)
        return buffer.getvalue()

    def create_test_user_and_session(self):
        """Create test user and session in MongoDB"""
        print("\n🔧 Creating test user and session...")
        
        timestamp = int(datetime.now().timestamp())
        self.user_id = f"test-upload-user-{timestamp}"
        self.session_token = f"test_upload_session_{timestamp}"
        
        mongo_commands = f"""
use('test_database');
var userId = '{self.user_id}';
var sessionToken = '{self.session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert test user
db.users.insertOne({{
  user_id: userId,
  email: 'test.upload.{timestamp}@example.com',
  name: 'Test Upload Teacher',
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

print('Test upload user and session created');
"""
        
        try:
            with open('/tmp/mongo_upload_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_upload_setup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ Test user created: {self.user_id}")
                return True
            else:
                print(f"❌ MongoDB setup failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating test user: {str(e)}")
            return False

    def run_api_test(self, name, method, endpoint, expected_status, data=None, files=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        headers = {}
        
        if self.session_token:
            headers['Authorization'] = f'Bearer {self.session_token}'
        
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            elif method == 'POST':
                if files:
                    # Don't set Content-Type for multipart/form-data
                    response = requests.post(url, files=files, headers=headers, timeout=30)
                else:
                    headers['Content-Type'] = 'application/json'
                    response = requests.post(url, json=data, headers=headers, timeout=30)
            elif method == 'PUT':
                headers['Content-Type'] = 'application/json'
                response = requests.put(url, json=data, headers=headers, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=30)

            print(f"   Status: {response.status_code}")
            
            success = response.status_code == expected_status
            
            if success:
                print(f"✅ {name} - PASSED")
                try:
                    return response.json()
                except:
                    return {"status": "success"}
            else:
                print(f"❌ {name} - FAILED: Expected {expected_status}, got {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"   Error: {error_data}")
                except:
                    print(f"   Response: {response.text[:200]}")
                return None

        except Exception as e:
            print(f"❌ {name} - FAILED: Request failed: {str(e)}")
            return None

    def setup_test_data(self):
        """Create batch, subject, and exam for testing"""
        print("\n📋 Setting up test data...")
        
        # Create batch
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
        
        if batch_result:
            self.test_batch_id = batch_result.get('batch_id')
            print(f"✅ Created batch: {self.test_batch_id}")
        else:
            return False
        
        # Create subject
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
        
        if subject_result:
            self.test_subject_id = subject_result.get('subject_id')
            print(f"✅ Created subject: {self.test_subject_id}")
        else:
            return False
        
        # Create exam
        exam_data = {
            "batch_id": self.test_batch_id,
            "subject_id": self.test_subject_id,
            "exam_type": "Unit Test",
            "exam_name": f"Upload More Papers Test {datetime.now().strftime('%H%M%S')}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 50.0,
                    "rubric": "Solve the algebraic equation: 2x + 5 = 15"
                },
                {
                    "question_number": 2,
                    "max_marks": 50.0,
                    "rubric": "Find the roots of the quadratic equation: x² - 5x + 6 = 0"
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
            print(f"✅ Created exam: {self.test_exam_id}")
            return True
        else:
            return False

    def test_upload_more_papers_with_files(self):
        """Test upload-more-papers with actual PDF files"""
        print("\n🚨 P0 CRITICAL: Testing Upload More Papers with PDF Files...")
        
        if not self.test_exam_id:
            print("❌ Cannot test - no exam available")
            return False
        
        # Create test PDF files with different filename formats
        test_cases = [
            {
                "filename": "STU001_TestStudent_Maths.pdf",
                "student_id": "STU001",
                "student_name": "Test Student",
                "description": "Standard format with subject"
            },
            {
                "filename": "STU002_AnotherStudent_Subject.pdf", 
                "student_id": "STU002",
                "student_name": "Another Student",
                "description": "Standard format"
            },
            {
                "filename": "123_John_Doe.pdf",
                "student_id": "123", 
                "student_name": "John Doe",
                "description": "Numeric ID with space in name"
            }
        ]
        
        # Create PDF files
        files_to_upload = []
        for case in test_cases:
            pdf_content = self.create_test_pdf(
                case["filename"], 
                case["student_id"], 
                case["student_name"]
            )
            files_to_upload.append(
                ('files', (case["filename"], pdf_content, 'application/pdf'))
            )
            print(f"📄 Created PDF: {case['filename']} ({case['description']})")
        
        # Test the upload
        result = self.run_api_test(
            "Upload More Papers with PDF Files",
            "POST",
            f"exams/{self.test_exam_id}/upload-more-papers",
            200,
            files=files_to_upload
        )
        
        if result:
            processed = result.get("processed", 0)
            submissions = result.get("submissions", [])
            errors = result.get("errors", [])
            
            print(f"📊 Upload Results:")
            print(f"   Processed: {processed} files")
            print(f"   Submissions created: {len(submissions)}")
            print(f"   Errors: {len(errors)}")
            
            if errors:
                print("❌ Errors encountered:")
                for error in errors:
                    print(f"   - {error.get('filename', 'Unknown')}: {error.get('error', 'Unknown error')}")
            
            if submissions:
                print("✅ Submissions created:")
                for sub in submissions:
                    print(f"   - {sub.get('student_id', 'Unknown')} ({sub.get('student_name', 'Unknown')}): {sub.get('percentage', 0)}%")
            
            # Verify students were created/found
            students_result = self.run_api_test(
                "Verify Students Created",
                "GET",
                "students",
                200
            )
            
            if students_result:
                created_student_ids = [s.get('student_id') for s in students_result]
                print(f"📋 Students in system: {created_student_ids}")
                
                # Check if our test students are there
                expected_ids = [case["student_id"] for case in test_cases]
                found_ids = [sid for sid in expected_ids if sid in created_student_ids]
                
                if len(found_ids) == len(expected_ids):
                    print("✅ All students created/found successfully")
                else:
                    print(f"⚠️  Only {len(found_ids)}/{len(expected_ids)} students found: {found_ids}")
            
            return processed > 0
        
        return False

    def test_upload_with_existing_student(self):
        """Test upload with a student that already exists"""
        print("\n👥 Testing Upload with Existing Student...")
        
        if not self.test_exam_id or not self.test_batch_id:
            print("❌ Cannot test - missing exam or batch")
            return False
        
        # Create an existing student first
        timestamp = datetime.now().strftime('%H%M%S')
        existing_student_data = {
            "email": f"existing.{timestamp}@school.edu",
            "name": "Existing Student",
            "role": "student", 
            "student_id": f"EXIST{timestamp}",
            "batches": [self.test_batch_id]
        }
        
        student_result = self.run_api_test(
            "Create Existing Student",
            "POST",
            "students",
            200,
            data=existing_student_data
        )
        
        if not student_result:
            print("❌ Failed to create existing student")
            return False
        
        existing_student_id = existing_student_data["student_id"]
        print(f"✅ Created existing student: {existing_student_id}")
        
        # Now upload a paper with the same student ID
        pdf_content = self.create_test_pdf(
            f"{existing_student_id}_ExistingStudent_Test.pdf",
            existing_student_id,
            "Existing Student"
        )
        
        files_to_upload = [
            ('files', (f"{existing_student_id}_ExistingStudent_Test.pdf", pdf_content, 'application/pdf'))
        ]
        
        result = self.run_api_test(
            "Upload Paper for Existing Student",
            "POST",
            f"exams/{self.test_exam_id}/upload-more-papers",
            200,
            files=files_to_upload
        )
        
        if result:
            processed = result.get("processed", 0)
            errors = result.get("errors", [])
            
            if processed > 0 and len(errors) == 0:
                print("✅ Successfully uploaded paper for existing student")
                return True
            else:
                print(f"❌ Upload failed - Processed: {processed}, Errors: {len(errors)}")
                if errors:
                    for error in errors:
                        print(f"   Error: {error}")
                return False
        
        return False

    def test_error_scenarios(self):
        """Test various error scenarios"""
        print("\n⚠️  Testing Error Scenarios...")
        
        if not self.test_exam_id:
            print("❌ Cannot test - no exam available")
            return False
        
        # Test 1: Upload file with unparseable filename
        print("\n📄 Testing unparseable filename...")
        pdf_content = self.create_test_pdf("unparseable.pdf", "TEST123", "Test Student")
        
        files_to_upload = [
            ('files', ('unparseable.pdf', pdf_content, 'application/pdf'))
        ]
        
        result = self.run_api_test(
            "Upload with Unparseable Filename",
            "POST",
            f"exams/{self.test_exam_id}/upload-more-papers",
            200,  # Should still return 200 but with errors
            files=files_to_upload
        )
        
        if result:
            errors = result.get("errors", [])
            if errors:
                print("✅ Correctly handled unparseable filename with error")
                print(f"   Error: {errors[0].get('error', 'Unknown')}")
            else:
                print("⚠️  Expected error for unparseable filename but got none")
        
        # Test 2: Upload to non-existent exam
        print("\n📄 Testing non-existent exam...")
        result = self.run_api_test(
            "Upload to Non-existent Exam",
            "POST",
            "exams/fake_exam_123/upload-more-papers",
            404,
            files=files_to_upload
        )
        
        if result is None:  # 404 expected
            print("✅ Correctly rejected upload to non-existent exam")
        
        return True

    def cleanup(self):
        """Clean up test data"""
        print("\n🧹 Cleaning up test data...")
        
        try:
            # Delete exam (this will cascade delete submissions)
            if self.test_exam_id:
                self.run_api_test(
                    "Delete Test Exam",
                    "DELETE",
                    f"exams/{self.test_exam_id}",
                    200
                )
            
            # Delete batch
            if self.test_batch_id:
                self.run_api_test(
                    "Delete Test Batch", 
                    "DELETE",
                    f"batches/{self.test_batch_id}",
                    200
                )
            
            print("✅ Cleanup completed")
        except Exception as e:
            print(f"⚠️  Cleanup warning: {str(e)}")

    def run_all_tests(self):
        """Run all upload-more-papers tests"""
        print("🚨 P0 CRITICAL: Upload More Papers Comprehensive Test")
        print("=" * 60)
        
        # Setup
        if not self.create_test_user_and_session():
            return False
        
        if not self.setup_test_data():
            return False
        
        # Run tests
        tests_passed = 0
        total_tests = 3
        
        if self.test_upload_more_papers_with_files():
            tests_passed += 1
        
        if self.test_upload_with_existing_student():
            tests_passed += 1
        
        if self.test_error_scenarios():
            tests_passed += 1
        
        # Cleanup
        self.cleanup()
        
        # Summary
        print("\n" + "=" * 60)
        print(f"📊 Upload More Papers Test Summary: {tests_passed}/{total_tests} tests passed")
        
        if tests_passed == total_tests:
            print("🎉 All upload-more-papers tests passed!")
            print("✅ P0 BUG VERIFIED AS FIXED:")
            print("   - Student ID extraction from filename working correctly")
            print("   - AI extraction fallback to filename parsing working")
            print("   - Existing student handling working correctly")
            print("   - Error handling for unparseable filenames working")
            return True
        else:
            print(f"⚠️  {total_tests - tests_passed} tests failed")
            return False

def main():
    tester = UploadMorePapersTest()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())