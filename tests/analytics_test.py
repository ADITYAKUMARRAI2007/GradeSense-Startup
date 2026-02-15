#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime
import subprocess
import os

class AnalyticsAPITester:
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
        self.user_id = f"analytics-test-user-{timestamp}"
        self.session_token = f"analytics_test_session_{timestamp}"
        
        # Create MongoDB commands
        mongo_commands = f"""
use('test_database');
var userId = '{self.user_id}';
var sessionToken = '{self.session_token}';
var expiresAt = new Date(Date.now() + 7*24*60*60*1000);

// Insert test user
db.users.insertOne({{
  user_id: userId,
  email: 'analytics.test.{timestamp}@example.com',
  name: 'Analytics Test Teacher',
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

print('Analytics test user and session created successfully');
"""
        
        try:
            # Write commands to temp file
            with open('/tmp/mongo_analytics_setup.js', 'w') as f:
                f.write(mongo_commands)
            
            # Execute MongoDB commands
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_analytics_setup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ Analytics test user created: {self.user_id}")
                print(f"✅ Session token: {self.session_token}")
                return True
            else:
                print(f"❌ MongoDB setup failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Error creating test user: {str(e)}")
            return False

    def create_test_data(self):
        """Create test data for analytics testing"""
        print("\n📊 Creating test data for analytics...")
        
        # Create batch
        batch_data = {"name": f"Analytics Test Batch {datetime.now().strftime('%H%M%S')}"}
        batch_result = self.run_api_test("Create Test Batch", "POST", "batches", 200, data=batch_data)
        if not batch_result:
            return False
        self.test_batch_id = batch_result.get('batch_id')
        
        # Create subject
        subject_data = {"name": f"Analytics Test Subject {datetime.now().strftime('%H%M%S')}"}
        subject_result = self.run_api_test("Create Test Subject", "POST", "subjects", 200, data=subject_data)
        if not subject_result:
            return False
        self.test_subject_id = subject_result.get('subject_id')
        
        # Create student
        timestamp = datetime.now().strftime('%H%M%S')
        student_data = {
            "email": f"analytics.student.{timestamp}@school.edu",
            "name": "Analytics Test Student",
            "role": "student",
            "student_id": f"ANALYTICS{timestamp}",
            "batches": [self.test_batch_id]
        }
        student_result = self.run_api_test("Create Test Student", "POST", "students", 200, data=student_data)
        if not student_result:
            return False
        self.test_student_id = student_result.get('user_id')
        
        # Create exam with detailed questions
        exam_data = {
            "batch_id": self.test_batch_id,
            "subject_id": self.test_subject_id,
            "exam_type": "Analytics Test",
            "exam_name": f"Analytics Test Exam {timestamp}",
            "total_marks": 100.0,
            "exam_date": "2024-01-15",
            "grading_mode": "balanced",
            "questions": [
                {
                    "question_number": 1,
                    "max_marks": 50.0,
                    "rubric": "Solve algebraic equations and show all working steps",
                    "sub_questions": []
                },
                {
                    "question_number": 2,
                    "max_marks": 50.0,
                    "rubric": "Analyze quadratic functions and graph the parabola",
                    "sub_questions": []
                }
            ]
        }
        exam_result = self.run_api_test("Create Test Exam", "POST", "exams", 200, data=exam_data)
        if not exam_result:
            return False
        self.test_exam_id = exam_result.get('exam_id')
        
        print(f"✅ Test data created - Batch: {self.test_batch_id}, Subject: {self.test_subject_id}, Student: {self.test_student_id}, Exam: {self.test_exam_id}")
        return True

    def test_analytics_misconceptions(self):
        """Test GET /api/analytics/misconceptions endpoint"""
        print("\n📊 Testing Analytics: Misconceptions Analysis...")
        
        result = self.run_api_test(
            "Analytics: Misconceptions Analysis",
            "GET",
            f"analytics/misconceptions?exam_id={self.test_exam_id}",
            200
        )
        
        if result:
            # Verify response structure
            required_fields = ["exam_name", "total_submissions", "misconceptions", "question_insights", "ai_analysis"]
            missing_fields = [field for field in required_fields if field not in result]
            
            if not missing_fields:
                self.log_test("Misconceptions Response Structure", True, "All required fields present")
            else:
                self.log_test("Misconceptions Response Structure", False, f"Missing fields: {missing_fields}")
        
        return result

    def test_analytics_topic_mastery(self):
        """Test GET /api/analytics/topic-mastery endpoint"""
        print("\n🎯 Testing Analytics: Topic Mastery...")
        
        # Test with exam_id filter
        result = self.run_api_test(
            "Topic Mastery: With Exam Filter",
            "GET",
            f"analytics/topic-mastery?exam_id={self.test_exam_id}",
            200
        )
        
        if result:
            # Verify response structure
            required_fields = ["topics", "students_by_topic"]
            missing_fields = [field for field in required_fields if field not in result]
            
            if not missing_fields:
                self.log_test("Topic Mastery Response Structure", True, "All required fields present")
            else:
                self.log_test("Topic Mastery Response Structure", False, f"Missing fields: {missing_fields}")
        
        return result

    def test_analytics_student_deep_dive(self):
        """Test GET /api/analytics/student-deep-dive/{student_id} endpoint"""
        print("\n🔍 Testing Analytics: Student Deep Dive...")
        
        result = self.run_api_test(
            "Student Deep Dive: Basic Analysis",
            "GET",
            f"analytics/student-deep-dive/{self.test_student_id}",
            200
        )
        
        if result:
            # Verify response structure
            required_fields = ["student", "overall_average", "worst_questions", "performance_trend", "ai_analysis"]
            missing_fields = [field for field in required_fields if field not in result]
            
            if not missing_fields:
                self.log_test("Student Deep Dive Response Structure", True, "All required fields present")
            else:
                self.log_test("Student Deep Dive Response Structure", False, f"Missing fields: {missing_fields}")
        
        return result

    def test_analytics_generate_review_packet(self):
        """Test POST /api/analytics/generate-review-packet endpoint"""
        print("\n📝 Testing Analytics: Generate Review Packet...")
        
        result = self.run_api_test(
            "Generate Review Packet",
            "POST",
            f"analytics/generate-review-packet?exam_id={self.test_exam_id}",
            200
        )
        
        if result:
            # Check if we got practice questions or a message about no weak areas
            if "practice_questions" in result:
                self.log_test("Review Packet Response Structure", True, "practice_questions field present")
            else:
                self.log_test("Review Packet Response Structure", False, "No practice_questions field in response")
        
        return result

    def test_exams_infer_topics(self):
        """Test POST /api/exams/{exam_id}/infer-topics endpoint"""
        print("\n🏷️  Testing Exams: Auto-Infer Topic Tags...")
        
        result = self.run_api_test(
            "Auto-Infer Topic Tags",
            "POST",
            f"exams/{self.test_exam_id}/infer-topics",
            200
        )
        
        if result:
            # Verify response structure
            required_fields = ["message", "topics"]
            missing_fields = [field for field in required_fields if field not in result]
            
            if not missing_fields:
                self.log_test("Infer Topics Response Structure", True, "All required fields present")
            else:
                self.log_test("Infer Topics Response Structure", False, f"Missing fields: {missing_fields}")
        
        return result

    def test_exams_update_question_topics(self):
        """Test PUT /api/exams/{exam_id}/question-topics endpoint"""
        print("\n✏️  Testing Exams: Update Question Topics...")
        
        # Test with valid topic updates
        topic_updates = {
            "1": ["Algebra", "Linear Equations"],
            "2": ["Algebra", "Quadratic Functions", "Graphing"]
        }
        
        result = self.run_api_test(
            "Update Question Topics",
            "PUT",
            f"exams/{self.test_exam_id}/question-topics",
            200,
            data=topic_updates
        )
        
        if result:
            # Verify response message
            message = result.get("message", "")
            if "successfully" in message.lower():
                self.log_test("Update Topics Response", True, f"Success message: {message}")
            else:
                self.log_test("Update Topics Response", False, f"Unexpected message: {message}")
        
        return result

    def cleanup_test_data(self):
        """Clean up test data from MongoDB"""
        print("\n🧹 Cleaning up analytics test data...")
        
        cleanup_commands = f"""
use('test_database');
// Clean up analytics test data
db.users.deleteMany({{email: /analytics\\.test\\./}});
db.user_sessions.deleteMany({{session_token: /analytics_test_session/}});
db.batches.deleteMany({{name: /Analytics Test Batch/}});
db.subjects.deleteMany({{name: /Analytics Test Subject/}});
db.exams.deleteMany({{exam_name: /Analytics Test Exam/}});
db.submissions.deleteMany({{student_name: /Analytics Test Student/}});

print('Analytics test data cleaned up');
"""
        
        try:
            with open('/tmp/mongo_analytics_cleanup.js', 'w') as f:
                f.write(cleanup_commands)
            
            result = subprocess.run([
                'mongosh', '--quiet', '--file', '/tmp/mongo_analytics_cleanup.js'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print("✅ Analytics test data cleaned up")
            else:
                print(f"⚠️  Cleanup warning: {result.stderr}")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {str(e)}")

    def run_analytics_tests(self):
        """Run all analytics API tests"""
        print("🚀 Starting Advanced Analytics API Testing")
        print("=" * 50)
        
        # Create test user and session
        if not self.create_test_user_and_session():
            print("❌ Failed to create test user - stopping tests")
            return False
        
        # Create test data
        if not self.create_test_data():
            print("❌ Failed to create test data - stopping tests")
            return False
        
        # Test all analytics endpoints
        print("\n📊 Testing Advanced Analytics Endpoints")
        print("-" * 50)
        
        self.test_analytics_misconceptions()
        self.test_analytics_topic_mastery()
        self.test_analytics_student_deep_dive()
        self.test_analytics_generate_review_packet()
        self.test_exams_infer_topics()
        self.test_exams_update_question_topics()
        
        # Cleanup
        self.cleanup_test_data()
        
        # Print summary
        print("\n" + "=" * 50)
        print(f"📊 Analytics Test Summary: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All analytics tests passed!")
            return True
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} analytics tests failed")
            return False

def main():
    tester = AnalyticsAPITester()
    success = tester.run_analytics_tests()
    
    # Save detailed results
    results = {
        "timestamp": datetime.now().isoformat(),
        "total_tests": tester.tests_run,
        "passed_tests": tester.tests_passed,
        "success_rate": (tester.tests_passed / tester.tests_run * 100) if tester.tests_run > 0 else 0,
        "test_details": tester.test_results
    }
    
    with open('/app/analytics_test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())