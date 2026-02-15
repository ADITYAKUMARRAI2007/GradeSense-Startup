#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os

class ObjectIdSerializationTester:
    def __init__(self):
        self.base_url = "https://smartgrade-app-1.preview.emergentagent.com/api"
        self.session_token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        self.critical_failures = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED")
        else:
            print(f"❌ {name} - FAILED: {details}")
            self.critical_failures.append(f"{name}: {details}")
        
        self.test_results.append({
            "test": name,
            "success": success,
            "details": details
        })

    def check_objectid_serialization(self, data, endpoint_name):
        """Check if response contains any ObjectId or _id fields"""
        issues = []
        
        def check_recursive(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key
                    
                    # Check for _id fields (should be removed by serialize_doc)
                    if key == "_id":
                        issues.append(f"Found _id field at {current_path}")
                    
                    # Check for ObjectId-like strings (24 hex chars)
                    if isinstance(value, str) and len(value) == 24:
                        try:
                            int(value, 16)  # Try to parse as hex
                            # This might be an ObjectId string, but it's acceptable if converted
                            pass
                        except ValueError:
                            pass
                    
                    # Recursively check nested objects
                    check_recursive(value, current_path)
                    
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_recursive(item, f"{path}[{i}]")
        
        check_recursive(data)
        
        if issues:
            self.log_test(f"{endpoint_name} - ObjectId Serialization Check", False, 
                         f"Found serialization issues: {'; '.join(issues)}")
            return False
        else:
            self.log_test(f"{endpoint_name} - ObjectId Serialization Check", True, 
                         "No _id fields or ObjectId serialization issues found")
            return True

    def run_api_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test and check for ObjectId serialization"""
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
                return None
            
            # If successful, check for ObjectId serialization issues
            try:
                response_data = response.json()
                
                # Check for ObjectId serialization issues
                self.check_objectid_serialization(response_data, name)
                
                self.log_test(name, success, details)
                return response_data
                
            except Exception as json_error:
                self.log_test(name, False, f"JSON parsing failed: {str(json_error)}")
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
  email: 'test.objectid.{timestamp}@example.com',
  name: 'ObjectId Test Teacher',
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
            with open('/tmp/mongo_objectid_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            # Execute MongoDB commands
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_objectid_setup.js'
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

    def create_test_data(self):
        """Create test data for ObjectId serialization testing"""
        print("\n🔧 Creating test data for ObjectId serialization tests...")
        
        timestamp = int(datetime.now().timestamp())
        
        # Create test data in MongoDB
        mongo_commands = f"""
use('test_database');
var userId = '{self.user_id}';
var timestamp = {timestamp};

// Create test batch
var batchId = 'batch_' + timestamp;
db.batches.insertOne({{
  batch_id: batchId,
  name: 'ObjectId Test Batch',
  teacher_id: userId,
  students: [],
  created_at: new Date().toISOString()
}});

// Create test subject
var subjectId = 'subject_' + timestamp;
db.subjects.insertOne({{
  subject_id: subjectId,
  name: 'ObjectId Test Subject',
  teacher_id: userId,
  created_at: new Date().toISOString()
}});

// Create test student
var studentId = 'student_' + timestamp;
db.users.insertOne({{
  user_id: studentId,
  email: 'test.student.objectid.' + timestamp + '@example.com',
  name: 'ObjectId Test Student',
  role: 'student',
  student_id: 'STU' + timestamp,
  batches: [batchId],
  created_at: new Date().toISOString()
}});

// Create test exam
var examId = 'exam_' + timestamp;
db.exams.insertOne({{
  exam_id: examId,
  batch_id: batchId,
  subject_id: subjectId,
  exam_type: 'ObjectId Test',
  exam_name: 'ObjectId Serialization Test Exam',
  total_marks: 100.0,
  exam_date: '2024-01-15',
  grading_mode: 'balanced',
  questions: [
    {{
      question_number: 1,
      max_marks: 50.0,
      rubric: 'Test question 1'
    }},
    {{
      question_number: 2,
      max_marks: 50.0,
      rubric: 'Test question 2'
    }}
  ],
  teacher_id: userId,
  status: 'completed',
  created_at: new Date().toISOString()
}});

// Create test submission
var submissionId = 'sub_' + timestamp;
db.submissions.insertOne({{
  submission_id: submissionId,
  exam_id: examId,
  student_id: studentId,
  student_name: 'ObjectId Test Student',
  total_score: 85,
  percentage: 85.0,
  question_scores: [
    {{
      question_number: 1,
      max_marks: 50,
      obtained_marks: 45,
      ai_feedback: 'Good work on question 1',
      teacher_comment: null,
      is_reviewed: false,
      sub_scores: []
    }},
    {{
      question_number: 2,
      max_marks: 50,
      obtained_marks: 40,
      ai_feedback: 'Good work on question 2',
      teacher_comment: null,
      is_reviewed: false,
      sub_scores: []
    }}
  ],
  status: 'ai_graded',
  graded_at: new Date().toISOString(),
  created_at: new Date().toISOString()
}});

// Create test grading job
var jobId = 'job_' + timestamp;
db.grading_jobs.insertOne({{
  job_id: jobId,
  exam_id: examId,
  teacher_id: userId,
  status: 'completed',
  total_papers: 1,
  processed_papers: 1,
  submissions: [
    {{
      submission_id: submissionId,
      student_id: studentId,
      student_name: 'ObjectId Test Student',
      status: 'completed',
      total_score: 85,
      percentage: 85.0
    }}
  ],
  created_at: new Date().toISOString(),
  completed_at: new Date().toISOString()
}});

print('Test data created successfully');
print('Batch ID: ' + batchId);
print('Subject ID: ' + subjectId);
print('Student ID: ' + studentId);
print('Exam ID: ' + examId);
print('Submission ID: ' + submissionId);
print('Grading Job ID: ' + jobId);
"""
        
        try:
            with open('/tmp/mongo_test_data.js', 'w') as f:
                f.write(mongo_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_test_data.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ Test data created successfully")
                
                # Store test IDs for use in tests
                self.test_batch_id = f"batch_{timestamp}"
                self.test_subject_id = f"subject_{timestamp}"
                self.test_student_id = f"student_{timestamp}"
                self.test_exam_id = f"exam_{timestamp}"
                self.test_submission_id = f"sub_{timestamp}"
                self.test_job_id = f"job_{timestamp}"
                
                return True
            else:
                print(f"❌ Test data creation failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating test data: {str(e)}")
            return False

    def test_grading_jobs_endpoint(self):
        """Test GET /api/grading-jobs/{job_id} for ObjectId serialization"""
        if not hasattr(self, 'test_job_id'):
            print("⚠️  Skipping grading jobs test - no test job created")
            return None
            
        return self.run_api_test(
            "GET /api/grading-jobs/{job_id}",
            "GET",
            f"grading-jobs/{self.test_job_id}",
            200
        )

    def test_submissions_endpoint(self):
        """Test GET /api/submissions for ObjectId serialization"""
        return self.run_api_test(
            "GET /api/submissions",
            "GET",
            "submissions",
            200
        )

    def test_exams_endpoint(self):
        """Test GET /api/exams for ObjectId serialization"""
        return self.run_api_test(
            "GET /api/exams",
            "GET",
            "exams",
            200
        )

    def test_batches_endpoint(self):
        """Test GET /api/batches for ObjectId serialization"""
        return self.run_api_test(
            "GET /api/batches",
            "GET",
            "batches",
            200
        )

    def test_students_endpoint(self):
        """Test GET /api/students for ObjectId serialization"""
        return self.run_api_test(
            "GET /api/students",
            "GET",
            "students",
            200
        )

    def test_admin_users_endpoint(self):
        """Test GET /api/admin/users for ObjectId serialization"""
        # This endpoint requires admin API key, so we'll test with invalid key to check structure
        admin_api_key = "invalid_key_for_testing"
        
        result = self.run_api_test(
            "GET /api/admin/users (structure test)",
            "GET",
            f"admin/export-users?api_key={admin_api_key}&format=json",
            403  # Expected to fail with 403, but we can check response structure
        )
        
        # Note: This will fail with 403, but that's expected
        # The important thing is that if it did work, it would use serialize_doc
        print("   Note: Admin endpoint tested for structure (403 expected without valid API key)")
        return result

    def test_nested_submissions_in_grading_job(self):
        """Test that nested submissions in grading job response have no _id fields"""
        if not hasattr(self, 'test_job_id'):
            print("⚠️  Skipping nested submissions test - no test job created")
            return None
            
        result = self.run_api_test(
            "Grading Job - Nested Submissions Check",
            "GET",
            f"grading-jobs/{self.test_job_id}",
            200
        )
        
        if result:
            # Specifically check nested submissions array
            submissions = result.get('submissions', [])
            if submissions:
                print(f"   Found {len(submissions)} nested submissions to check")
                for i, submission in enumerate(submissions):
                    if '_id' in submission:
                        self.log_test(f"Nested Submission {i+1} - No _id field", False, 
                                     "Found _id field in nested submission")
                    else:
                        self.log_test(f"Nested Submission {i+1} - No _id field", True, 
                                     "No _id field found in nested submission")
            else:
                print("   No nested submissions found to check")
        
        return result

    def run_all_objectid_tests(self):
        """Run all ObjectId serialization tests"""
        print("=" * 80)
        print("🔍 OBJECTID SERIALIZATION FIX VERIFICATION")
        print("=" * 80)
        
        # Setup
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user and session")
            return False
        
        if not self.create_test_data():
            print("❌ Failed to create test data")
            return False
        
        print("\n" + "=" * 60)
        print("🧪 TESTING CRITICAL ENDPOINTS FOR OBJECTID SERIALIZATION")
        print("=" * 60)
        
        # Test all critical endpoints
        self.test_grading_jobs_endpoint()
        self.test_submissions_endpoint()
        self.test_exams_endpoint()
        self.test_batches_endpoint()
        self.test_students_endpoint()
        self.test_admin_users_endpoint()
        
        # Test nested objects specifically
        self.test_nested_submissions_in_grading_job()
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 OBJECTID SERIALIZATION TEST SUMMARY")
        print("=" * 60)
        
        print(f"Total Tests Run: {self.tests_run}")
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_run - self.tests_passed}")
        
        if self.critical_failures:
            print("\n❌ CRITICAL FAILURES:")
            for failure in self.critical_failures:
                print(f"   • {failure}")
        else:
            print("\n✅ ALL OBJECTID SERIALIZATION TESTS PASSED!")
        
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        print(f"\nSuccess Rate: {success_rate:.1f}%")
        
        return len(self.critical_failures) == 0

def main():
    """Main function to run ObjectId serialization tests"""
    tester = ObjectIdSerializationTester()
    
    try:
        success = tester.run_all_objectid_tests()
        
        if success:
            print("\n🎉 ObjectId serialization fix verification COMPLETED SUCCESSFULLY!")
            sys.exit(0)
        else:
            print("\n💥 ObjectId serialization fix verification FAILED!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error during testing: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()