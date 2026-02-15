#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os

class DuplicateAndDeletionTester:
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
                response = requests.get(url, headers=test_headers, timeout=15)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, timeout=15)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=test_headers, timeout=15)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, timeout=15)

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
  email: 'test.duplicate.{timestamp}@example.com',
  name: 'Test Teacher Duplicate',
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
            with open('/tmp/mongo_duplicate_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            # Execute MongoDB commands
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_duplicate_setup.js'
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

    def setup_prerequisites(self):
        """Create batch and subject needed for exam tests"""
        print("\n📋 Setting up prerequisites (batch and subject)...")
        
        # Create batch
        batch_data = {
            "name": f"Test Batch Duplicate {datetime.now().strftime('%H%M%S')}"
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
        else:
            return False
        
        # Create subject
        subject_data = {
            "name": f"Test Subject Duplicate {datetime.now().strftime('%H%M%S')}"
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
            return True
        else:
            return False

    def test_duplicate_exam_prevention(self):
        """Test duplicate exam name prevention"""
        print("\n🔒 Testing Duplicate Exam Name Prevention...")
        
        # Create first exam with specific name
        exam_name = "Test Exam 1"
        exam_data = {
            "batch_id": self.test_batch_id,
            "subject_id": self.test_subject_id,
            "exam_type": "Unit Test",
            "exam_name": exam_name,
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 100.0,
                    "rubric": "Test question"
                }
            ]
        }
        
        # Create first exam (should succeed)
        first_result = self.run_api_test(
            "Create First Exam (Test Exam 1)",
            "POST",
            "exams",
            200,
            data=exam_data
        )
        
        if first_result:
            self.test_exam_id = first_result.get('exam_id')
            print(f"   Created exam with ID: {self.test_exam_id}")
            
            # Try to create second exam with same name (should fail)
            print("\n   Attempting to create duplicate exam...")
            url = f"{self.base_url}/exams"
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.session_token}'
            }
            
            try:
                response = requests.post(url, json=exam_data, headers=headers, timeout=15)
                print(f"   Duplicate attempt status: {response.status_code}")
                
                if response.status_code == 400:
                    error_data = response.json()
                    error_message = error_data.get('detail', '')
                    print(f"   Error message: {error_message}")
                    
                    if "already exists" in error_message.lower():
                        self.log_test("Duplicate Exam Prevention", True, f"Correctly prevented duplicate with message: {error_message}")
                    else:
                        self.log_test("Duplicate Exam Prevention", False, f"Wrong error message: {error_message}")
                else:
                    self.log_test("Duplicate Exam Prevention", False, f"Expected 400, got {response.status_code}")
                    
            except Exception as e:
                self.log_test("Duplicate Exam Prevention", False, f"Request failed: {str(e)}")
            
            return first_result
        
        return None

    def test_exam_deletion(self):
        """Test exam deletion functionality"""
        print("\n🗑️  Testing Exam Deletion...")
        
        if not hasattr(self, 'test_exam_id'):
            print("⚠️  No exam to delete")
            return None
            
        exam_id = self.test_exam_id
        
        # First verify exam exists
        verify_result = self.run_api_test(
            "Verify Exam Exists Before Deletion",
            "GET",
            "exams",
            200
        )
        
        if verify_result:
            # Check if our exam is in the list
            exam_found = any(exam.get('exam_id') == exam_id for exam in verify_result)
            if exam_found:
                print(f"   ✅ Exam {exam_id} found in exam list")
            else:
                print(f"   ⚠️  Exam {exam_id} not found in exam list")
        
        # Delete the exam
        delete_result = self.run_api_test(
            "Delete Exam",
            "DELETE",
            f"exams/{exam_id}",
            200
        )
        
        if delete_result:
            print(f"   Delete response: {delete_result}")
            
            # Verify exam is deleted by checking exam list
            verify_deleted = self.run_api_test(
                "Verify Exam Deleted",
                "GET", 
                "exams",
                200
            )
            
            if verify_deleted:
                exam_still_exists = any(exam.get('exam_id') == exam_id for exam in verify_deleted)
                if not exam_still_exists:
                    self.log_test("Exam Deletion Verification", True, "Exam successfully removed from list")
                else:
                    self.log_test("Exam Deletion Verification", False, "Exam still exists in list after deletion")
            
            # Try to delete the same exam again (should return 404)
            second_delete_result = self.run_api_test(
                "Delete Non-existent Exam (should fail)",
                "DELETE",
                f"exams/{exam_id}",
                404  # Should fail with 404
            )
            
            return delete_result
        
        return None

    def cleanup_test_data(self):
        """Clean up test data from MongoDB"""
        print("\n🧹 Cleaning up test data...")
        
        cleanup_commands = f"""
use('test_database');
// Clean up test data
db.users.deleteMany({{email: /test\\.duplicate\\./}});
db.user_sessions.deleteMany({{session_token: /test_session/}});
db.batches.deleteMany({{name: /Test Batch Duplicate/}});
db.subjects.deleteMany({{name: /Test Subject Duplicate/}});
db.exams.deleteMany({{exam_name: /Test Exam 1/}});
print('Test data cleaned up');
"""
        
        try:
            with open('/tmp/mongo_duplicate_cleanup.js', 'w') as f:
                f.write(cleanup_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_duplicate_cleanup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ Test data cleaned up")
            else:
                print(f"⚠️  Cleanup warning: {result.stderr}")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {str(e)}")

    def run_tests(self):
        """Run duplicate prevention and deletion tests"""
        print("🚀 Starting Duplicate Prevention & Deletion Tests")
        print("=" * 60)
        
        # Create test user and session
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user - stopping tests")
            return False
        
        # Setup prerequisites
        if not self.setup_prerequisites():
            print("❌ Failed to setup prerequisites - stopping tests")
            return False
        
        # Test duplicate prevention
        self.test_duplicate_exam_prevention()
        
        # Test deletion
        self.test_exam_deletion()
        
        # Cleanup
        self.cleanup_test_data()
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Test Summary: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return True
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} tests failed")
            return False

def main():
    tester = DuplicateAndDeletionTester()
    success = tester.run_tests()
    
    # Save detailed results
    results = {
        "timestamp": datetime.now().isoformat(),
        "total_tests": tester.tests_run,
        "passed_tests": tester.tests_passed,
        "success_rate": (tester.tests_passed / tester.tests_run * 100) if tester.tests_run > 0 else 0,
        "test_details": tester.test_results
    }
    
    with open('/app/duplicate_deletion_test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())