#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime, timedelta
import subprocess
import os

class CascadeDeletionTester:
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

    def create_test_user_and_session(self):
        """Create test user and session in MongoDB"""
        print("\n🔧 Creating test user and session in MongoDB...")
        
        timestamp = int(datetime.now().timestamp())
        self.user_id = f"test-cascade-{timestamp}"
        self.session_token = f"cascade_session_{timestamp}"
        
        # Create MongoDB commands
        mongo_commands = f"""
use('test_database');
var userId = '{self.user_id}';
var sessionToken = '{self.session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert test user
db.users.insertOne({{
  user_id: userId,
  email: 'test.cascade.{timestamp}@example.com',
  name: 'Test Teacher Cascade',
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
            with open('/tmp/mongo_cascade_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_cascade_setup.js'
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

    def setup_exam_with_data(self):
        """Create exam with associated submissions and re-evaluation requests"""
        print("\n📋 Setting up exam with associated data...")
        
        timestamp = datetime.now().strftime('%H%M%S')
        
        # Create batch
        batch_data = {"name": f"Cascade Test Batch {timestamp}"}
        batch_result = requests.post(
            f"{self.base_url}/batches",
            json=batch_data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.session_token}'},
            timeout=15
        )
        
        if batch_result.status_code != 200:
            print(f"❌ Failed to create batch: {batch_result.status_code}")
            return False
        
        self.test_batch_id = batch_result.json().get('batch_id')
        
        # Create subject
        subject_data = {"name": f"Cascade Test Subject {timestamp}"}
        subject_result = requests.post(
            f"{self.base_url}/subjects",
            json=subject_data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.session_token}'},
            timeout=15
        )
        
        if subject_result.status_code != 200:
            print(f"❌ Failed to create subject: {subject_result.status_code}")
            return False
        
        self.test_subject_id = subject_result.json().get('subject_id')
        
        # Create exam
        exam_data = {
            "batch_id": self.test_batch_id,
            "subject_id": self.test_subject_id,
            "exam_type": "Unit Test",
            "exam_name": f"Cascade Test Exam {timestamp}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 100.0,
                    "rubric": "Test question for cascade deletion"
                }
            ]
        }
        
        exam_result = requests.post(
            f"{self.base_url}/exams",
            json=exam_data,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.session_token}'},
            timeout=15
        )
        
        if exam_result.status_code != 200:
            print(f"❌ Failed to create exam: {exam_result.status_code}")
            return False
        
        self.test_exam_id = exam_result.json().get('exam_id')
        print(f"✅ Created exam: {self.test_exam_id}")
        
        # Create test submissions and re-evaluation requests directly in MongoDB
        mongo_commands = f"""
use('test_database');
var examId = '{self.test_exam_id}';
var studentId1 = 'test-student-1';
var studentId2 = 'test-student-2';
var submissionId1 = 'test-sub-1';
var submissionId2 = 'test-sub-2';
var reevalId1 = 'test-reeval-1';

// Create test submissions
db.submissions.insertMany([
  {{
    submission_id: submissionId1,
    exam_id: examId,
    student_id: studentId1,
    student_name: 'Test Student 1',
    total_score: 85,
    percentage: 85,
    question_scores: [{{
      question_number: 1,
      max_marks: 100,
      obtained_marks: 85,
      ai_feedback: 'Good work'
    }}],
    status: 'ai_graded',
    created_at: new Date().toISOString()
  }},
  {{
    submission_id: submissionId2,
    exam_id: examId,
    student_id: studentId2,
    student_name: 'Test Student 2',
    total_score: 75,
    percentage: 75,
    question_scores: [{{
      question_number: 1,
      max_marks: 100,
      obtained_marks: 75,
      ai_feedback: 'Needs improvement'
    }}],
    status: 'ai_graded',
    created_at: new Date().toISOString()
  }}
]);

// Create test re-evaluation request
db.re_evaluations.insertOne({{
  request_id: reevalId1,
  submission_id: submissionId1,
  student_id: studentId1,
  student_name: 'Test Student 1',
  exam_id: examId,
  questions: [1],
  reason: 'I think my answer deserves more marks',
  status: 'pending',
  created_at: new Date().toISOString()
}});

print('Test submissions and re-evaluation requests created');
"""
        
        try:
            with open('/tmp/mongo_cascade_data.js', 'w') as f:
                f.write(mongo_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_cascade_data.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ Test submissions and re-evaluation requests created")
                return True
            else:
                print(f"❌ Failed to create test data: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating test data: {str(e)}")
            return False

    def verify_data_exists(self):
        """Verify that submissions and re-evaluation requests exist"""
        print("\n🔍 Verifying test data exists...")
        
        # Check submissions count
        mongo_check = f"""
use('test_database');
var examId = '{self.test_exam_id}';
var submissionCount = db.submissions.countDocuments({{exam_id: examId}});
var reevalCount = db.re_evaluations.countDocuments({{exam_id: examId}});
print('Submissions for exam ' + examId + ': ' + submissionCount);
print('Re-evaluations for exam ' + examId + ': ' + reevalCount);
"""
        
        try:
            with open('/tmp/mongo_check_data.js', 'w') as f:
                f.write(mongo_check)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_check_data.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                output = result.stdout
                print(f"   {output}")
                
                # Parse the output to check counts
                if "Submissions for exam" in output and "Re-evaluations for exam" in output:
                    lines = output.strip().split('\n')
                    submission_line = [line for line in lines if "Submissions for exam" in line][0]
                    reeval_line = [line for line in lines if "Re-evaluations for exam" in line][0]
                    
                    submission_count = int(submission_line.split(': ')[-1])
                    reeval_count = int(reeval_line.split(': ')[-1])
                    
                    if submission_count > 0 and reeval_count > 0:
                        self.log_test("Data Exists Before Deletion", True, f"Found {submission_count} submissions and {reeval_count} re-evaluations")
                        return True
                    else:
                        self.log_test("Data Exists Before Deletion", False, f"Expected data not found: {submission_count} submissions, {reeval_count} re-evaluations")
                        return False
                else:
                    self.log_test("Data Exists Before Deletion", False, "Could not parse MongoDB output")
                    return False
            else:
                self.log_test("Data Exists Before Deletion", False, f"MongoDB check failed: {result.stderr}")
                return False
                
        except Exception as e:
            self.log_test("Data Exists Before Deletion", False, f"Error checking data: {str(e)}")
            return False

    def test_cascade_deletion(self):
        """Test that exam deletion cascades to submissions and re-evaluations"""
        print("\n🗑️  Testing Cascade Deletion...")
        
        # Delete the exam
        delete_result = requests.delete(
            f"{self.base_url}/exams/{self.test_exam_id}",
            headers={'Authorization': f'Bearer {self.session_token}'},
            timeout=15
        )
        
        if delete_result.status_code == 200:
            self.log_test("Exam Deletion", True, f"Exam deleted successfully: {delete_result.json()}")
            
            # Verify cascade deletion
            mongo_verify = f"""
use('test_database');
var examId = '{self.test_exam_id}';
var submissionCount = db.submissions.countDocuments({{exam_id: examId}});
var reevalCount = db.re_evaluations.countDocuments({{exam_id: examId}});
var examCount = db.exams.countDocuments({{exam_id: examId}});
print('After deletion:');
print('Exams: ' + examCount);
print('Submissions: ' + submissionCount);
print('Re-evaluations: ' + reevalCount);
"""
            
            try:
                with open('/tmp/mongo_verify_cascade.js', 'w') as f:
                    f.write(mongo_verify)
                
                result = subprocess.run([
                    'mongosh', '--quiet', '--file', '/tmp/mongo_verify_cascade.js'
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    output = result.stdout
                    print(f"   {output}")
                    
                    # Parse the output to verify all counts are 0
                    lines = output.strip().split('\n')
                    exam_count = 0
                    submission_count = 0
                    reeval_count = 0
                    
                    for line in lines:
                        if "Exams:" in line:
                            exam_count = int(line.split(': ')[-1])
                        elif "Submissions:" in line:
                            submission_count = int(line.split(': ')[-1])
                        elif "Re-evaluations:" in line:
                            reeval_count = int(line.split(': ')[-1])
                    
                    if exam_count == 0 and submission_count == 0 and reeval_count == 0:
                        self.log_test("Cascade Deletion Verification", True, "All related data successfully deleted")
                    else:
                        self.log_test("Cascade Deletion Verification", False, f"Some data remains: {exam_count} exams, {submission_count} submissions, {reeval_count} re-evaluations")
                else:
                    self.log_test("Cascade Deletion Verification", False, f"MongoDB verification failed: {result.stderr}")
                    
            except Exception as e:
                self.log_test("Cascade Deletion Verification", False, f"Error verifying cascade: {str(e)}")
        else:
            self.log_test("Exam Deletion", False, f"Expected 200, got {delete_result.status_code}: {delete_result.text}")

    def cleanup_test_data(self):
        """Clean up test data from MongoDB"""
        print("\n🧹 Cleaning up test data...")
        
        cleanup_commands = f"""
use('test_database');
// Clean up test data
db.users.deleteMany({{email: /test\\.cascade\\./}});
db.user_sessions.deleteMany({{session_token: /cascade_session/}});
db.batches.deleteMany({{name: /Cascade Test Batch/}});
db.subjects.deleteMany({{name: /Cascade Test Subject/}});
db.exams.deleteMany({{exam_name: /Cascade Test Exam/}});
db.submissions.deleteMany({{submission_id: /test-sub-/}});
db.re_evaluations.deleteMany({{request_id: /test-reeval-/}});
print('Test data cleaned up');
"""
        
        try:
            with open('/tmp/mongo_cascade_cleanup.js', 'w') as f:
                f.write(cleanup_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_cascade_cleanup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ Test data cleaned up")
            else:
                print(f"⚠️  Cleanup warning: {result.stderr}")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {str(e)}")

    def run_tests(self):
        """Run cascade deletion tests"""
        print("🚀 Starting Cascade Deletion Tests")
        print("=" * 50)
        
        # Create test user and session
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user - stopping tests")
            return False
        
        # Setup exam with associated data
        if not self.setup_exam_with_data():
            print("❌ Failed to setup exam with data - stopping tests")
            return False
        
        # Verify data exists
        if not self.verify_data_exists():
            print("❌ Test data verification failed - stopping tests")
            return False
        
        # Test cascade deletion
        self.test_cascade_deletion()
        
        # Cleanup
        self.cleanup_test_data()
        
        # Print summary
        print("\n" + "=" * 50)
        print(f"📊 Test Summary: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return True
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} tests failed")
            return False

def main():
    tester = CascadeDeletionTester()
    success = tester.run_tests()
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())