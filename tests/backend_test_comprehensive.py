#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os
import base64

class GradeSenseComprehensiveTester:
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
  email: 'test.comprehensive.{timestamp}@example.com',
  name: 'Test Comprehensive Teacher',
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
"""
        
        try:
            with open('/tmp/mongo_comprehensive_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_comprehensive_setup.js'
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

    def run_api_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        test_headers = {'Content-Type': 'application/json'}
        
        if self.session_token:
            test_headers['Authorization'] = f'Bearer {self.session_token}'
        
        if headers:
            test_headers.update(headers)

        print(f"\n🔍 Testing {name}...")
        
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

    def setup_test_environment(self):
        """Setup test environment with batch, subject, and exam"""
        print("\n🏗️  Setting up test environment...")
        
        # Create batch
        batch_data = {
            "name": f"Comprehensive Test Batch {datetime.now().strftime('%H%M%S')}"
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
            "name": f"Comprehensive Test Subject {datetime.now().strftime('%H%M%S')}"
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
            "exam_type": "Comprehensive Test",
            "exam_name": f"Comprehensive Test Exam {datetime.now().strftime('%H%M%S')}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 100.0,
                    "rubric": "Test question for comprehensive testing"
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

    def test_backend_tasks_needing_retesting(self):
        """Test backend tasks that need retesting from test_result.md"""
        print("\n🔄 Testing Backend Tasks Needing Retesting...")
        
        # Test Visual Annotations for Error Highlighting (needs_retesting: true)
        # This is a backend feature that should be testable via API
        print("\n📍 Testing Visual Annotations Feature...")
        
        # Test Topic Mastery Heatmap (working: false, needs_retesting: true)
        topic_mastery_result = self.run_api_test(
            "Topic Mastery Heatmap Analytics",
            "GET",
            "analytics/topic-mastery",
            200
        )
        
        if topic_mastery_result:
            # Check if the response has proper topic structure
            topics = topic_mastery_result.get("topics", [])
            if topics:
                # Check if topics have required fields
                first_topic = topics[0]
                required_fields = ["topic", "percentage", "color"]
                has_all_fields = all(field in first_topic for field in required_fields)
                
                if has_all_fields:
                    self.log_test("Topic Mastery Data Structure", True, 
                        f"Found {len(topics)} topics with proper structure")
                else:
                    self.log_test("Topic Mastery Data Structure", False, 
                        f"Missing required fields in topic data")
            else:
                self.log_test("Topic Mastery Data Structure", False, 
                    "No topics found in response")
        
        # Test Student Deep-Dive Modal Logic (working: false, needs_retesting: true)
        # Create a test student first
        student_data = {
            "email": f"test.student.{datetime.now().strftime('%H%M%S')}@example.com",
            "name": "Test Student for Deep Dive",
            "role": "student",
            "student_id": f"DEEP{datetime.now().strftime('%H%M%S')}",
            "batches": [self.test_batch_id] if hasattr(self, 'test_batch_id') else []
        }
        
        student_result = self.run_api_test(
            "Create Test Student for Deep Dive",
            "POST",
            "students",
            200,
            data=student_data
        )
        
        if student_result:
            student_id = student_result.get('user_id')
            
            # Test student deep-dive analytics
            deep_dive_result = self.run_api_test(
                "Student Deep-Dive Analytics",
                "GET",
                f"analytics/student-deep-dive/{student_id}",
                200
            )
            
            if deep_dive_result:
                # Check if response has proper structure
                required_sections = ["performance_summary", "weak_areas", "strong_areas", "recommendations"]
                has_all_sections = all(section in deep_dive_result for section in required_sections)
                
                if has_all_sections:
                    self.log_test("Student Deep-Dive Data Structure", True, 
                        "All required sections present in deep-dive response")
                else:
                    missing_sections = [s for s in required_sections if s not in deep_dive_result]
                    self.log_test("Student Deep-Dive Data Structure", False, 
                        f"Missing sections: {missing_sections}")

    def test_multi_format_file_upload_comprehensive(self):
        """Comprehensive test of multi-format file upload with proper file content"""
        print("\n📄 Testing Multi-Format File Upload (Comprehensive)...")
        
        if not self.test_exam_id:
            print("⚠️  Skipping multi-format upload test - no exam created")
            return None
        
        # Test 1: Valid PDF upload
        # Create a proper minimal PDF
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
(Test PDF) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000189 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
284
%%EOF"""
        
        pdf_result = self.run_multipart_upload_test(
            "Model Answer Upload - Valid PDF",
            f"exams/{self.test_exam_id}/upload-model-answer",
            pdf_content,
            "model_answer.pdf",
            "application/pdf"
        )
        
        # Test 2: Valid image upload (create a proper 1x1 PNG)
        # PNG signature + minimal PNG data
        png_content = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChAI9jU8j8gAAAABJRU5ErkJggg==")
        
        image_result = self.run_multipart_upload_test(
            "Model Answer Upload - Valid PNG Image",
            f"exams/{self.test_exam_id}/upload-model-answer",
            png_content,
            "model_answer.png",
            "image/png"
        )
        
        return [pdf_result, image_result]

    def run_multipart_upload_test(self, name, endpoint, file_content, filename, content_type, expected_status=200):
        """Helper method to run multipart file upload tests"""
        url = f"{self.base_url}/{endpoint}"
        
        print(f"\n🔍 Testing {name}...")
        print(f"   File: {filename} ({content_type})")
        
        try:
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

    def test_critical_backend_endpoints(self):
        """Test critical backend endpoints mentioned in review request"""
        print("\n🎯 Testing Critical Backend Endpoints...")
        
        # Test health endpoint
        self.run_api_test("Health Check", "GET", "health", 200)
        
        # Test auth endpoint
        self.run_api_test("Auth Me", "GET", "auth/me", 200)
        
        # Test analytics endpoints that were reported as having issues
        self.run_api_test("Class Insights Analytics", "GET", "analytics/insights", 200)
        
        # Test dashboard analytics
        self.run_api_test("Dashboard Analytics", "GET", "analytics/dashboard", 200)
        
        # Test class report analytics
        self.run_api_test("Class Report Analytics", "GET", "analytics/class-report", 200)

    def test_backend_logs_for_critical_errors(self):
        """Check backend logs for critical errors mentioned in review request"""
        print("\n📋 Checking Backend Logs for Critical Errors...")
        
        try:
            # Check supervisor backend logs
            result = subprocess.run([
                'tail', '-n', '200', '/var/log/supervisor/backend.err.log'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                error_log = result.stdout
                
                # Check for specific critical errors mentioned in review request
                critical_errors = [
                    "poppler not installed",
                    "DialogDescription is not defined", 
                    "pdf_to_base64_images",
                    "ModuleNotFoundError",
                    "ImportError",
                    "FileDataError"
                ]
                
                found_errors = []
                for error in critical_errors:
                    if error.lower() in error_log.lower():
                        found_errors.append(error)
                
                if found_errors:
                    self.log_test("Critical Backend Errors Check", False, 
                        f"Found critical errors: {', '.join(found_errors)}")
                    
                    # Print some context around errors
                    print("   Error context:")
                    for line in error_log.split('\n')[-20:]:
                        if any(err.lower() in line.lower() for err in found_errors):
                            print(f"   {line}")
                else:
                    self.log_test("Critical Backend Errors Check", True, 
                        "No critical errors found in backend logs")
                
            else:
                self.log_test("Critical Backend Errors Check", False, 
                    "Could not access backend error logs")
                
        except Exception as e:
            self.log_test("Critical Backend Errors Check", False, 
                f"Error checking logs: {str(e)}")

    def print_summary(self):
        """Print comprehensive test summary"""
        print("\n" + "="*80)
        print("🔥 COMPREHENSIVE GRADESENSE BACKEND TEST SUMMARY")
        print("="*80)
        print(f"Total Tests: {self.tests_run}")
        print(f"Passed: {self.tests_passed}")
        print(f"Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%" if self.tests_run > 0 else "0%")
        
        # Categorize results
        failed_tests = [r for r in self.test_results if not r["success"]]
        passed_tests = [r for r in self.test_results if r["success"]]
        
        if failed_tests:
            print(f"\n❌ FAILED TESTS ({len(failed_tests)}):")
            for result in failed_tests:
                print(f"   • {result['test']}")
                print(f"     └─ {result['details']}")
        
        print(f"\n✅ PASSED TESTS ({len(passed_tests)}):")
        for result in passed_tests:
            print(f"   • {result['test']}")
        
        # Summary for main agent
        print("\n" + "="*80)
        print("📊 SUMMARY FOR MAIN AGENT")
        print("="*80)
        
        if failed_tests:
            print("🚨 CRITICAL ISSUES FOUND:")
            for result in failed_tests:
                if "error" in result['details'].lower() or "500" in result['details'] or "520" in result['details']:
                    print(f"   🔴 {result['test']}: {result['details']}")
        
        print("\n✅ WORKING FEATURES:")
        for result in passed_tests:
            if "upload" in result['test'].lower() or "analytics" in result['test'].lower():
                print(f"   🟢 {result['test']}")
        
        print("="*80)

    def run_comprehensive_tests(self):
        """Run comprehensive backend tests"""
        print("🔥 STARTING COMPREHENSIVE GRADESENSE BACKEND TESTING")
        print("="*80)
        
        # Setup
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user and session")
            return False
        
        if not self.setup_test_environment():
            print("❌ Failed to setup test environment")
            return False
        
        # Test critical backend endpoints
        self.test_critical_backend_endpoints()
        
        # Test backend tasks that need retesting
        self.test_backend_tasks_needing_retesting()
        
        # Test multi-format file upload
        self.test_multi_format_file_upload_comprehensive()
        
        # Check backend logs for critical errors
        self.test_backend_logs_for_critical_errors()
        
        # Summary
        self.print_summary()
        
        return self.tests_passed >= (self.tests_run * 0.7)  # 70% pass rate

if __name__ == "__main__":
    tester = GradeSenseComprehensiveTester()
    success = tester.run_comprehensive_tests()
    sys.exit(0 if success else 1)