import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, CheckCircle, Clock, XCircle, Trash2, PlayCircle } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { toast } from 'sonner';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const ExamSubmissionsView = () => {
  const { examId } = useParams();
  const navigate = useNavigate();
  
  const [examData, setExamData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [grading, setGrading] = useState(false);
  const [removing, setRemoving] = useState(null);

  useEffect(() => {
    fetchSubmissionStatus();
  }, [examId]);

  const fetchSubmissionStatus = async () => {
    try {
      const response = await axios.get(`${API}/exams/${examId}/submissions-status`, { 
        withCredentials: true 
      });
      setExamData(response.data);
    } catch (error) {
      console.error('Error fetching submission status:', error);
      toast.error('Failed to load submission status');
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveStudent = async (studentId) => {
    if (!window.confirm('Are you sure you want to remove this student from the exam?')) {
      return;
    }

    setRemoving(studentId);
    try {
      await axios.delete(`${API}/exams/${examId}/remove-student/${studentId}`, { 
        withCredentials: true 
      });
      toast.success('Student removed from exam');
      fetchSubmissionStatus();
    } catch (error) {
      console.error('Error removing student:', error);
      toast.error('Failed to remove student');
    } finally {
      setRemoving(null);
    }
  };

  const handleGradeNow = async () => {
    if (!window.confirm(`Start grading ${examData.submitted_count} submitted papers?`)) {
      return;
    }

    setGrading(true);
    try {
      await axios.post(`${API}/exams/${examId}/grade-student-submissions`, {}, { 
        withCredentials: true 
      });
      toast.success('Grading started! This may take a few minutes.');
      
      // Navigate to review page
      setTimeout(() => {
        navigate(`/teacher/review?exam_id=${examId}`);
      }, 2000);
    } catch (error) {
      console.error('Error starting grading:', error);
      toast.error(error.response?.data?.detail || 'Failed to start grading');
      setGrading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
      </div>
    );
  }

  const submittedStudents = examData?.students?.filter(s => s.submitted) || [];
  const pendingStudents = examData?.students?.filter(s => !s.submitted) || [];

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-5xl mx-auto">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>

        <div className="mb-6">
          <h1 className="text-3xl font-bold text-gray-900">{examData?.exam_name}</h1>
          <p className="text-gray-500 mt-1">Submission Status & Grading</p>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          <Card>
            <CardContent className="p-6">
              <div className="text-center">
                <p className="text-sm text-gray-600">Total Students</p>
                <p className="text-4xl font-bold text-gray-900 mt-2">{examData?.total_students || 0}</p>
              </div>
            </CardContent>
          </Card>
          <Card className="border-l-4 border-l-green-500">
            <CardContent className="p-6">
              <div className="text-center">
                <p className="text-sm text-gray-600">Submitted</p>
                <p className="text-4xl font-bold text-green-600 mt-2">{examData?.submitted_count || 0}</p>
              </div>
            </CardContent>
          </Card>
          <Card className="border-l-4 border-l-orange-500">
            <CardContent className="p-6">
              <div className="text-center">
                <p className="text-sm text-gray-600">Pending</p>
                <p className="text-4xl font-bold text-orange-600 mt-2">{pendingStudents.length}</p>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Grade Now Button */}
        {examData?.submitted_count > 0 && (
          <div className="mb-8">
            <Card className="border-l-4 border-l-primary">
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">
                      {examData?.all_submitted 
                        ? '✓ All students have submitted!' 
                        : `${examData?.submitted_count} submissions ready for grading`}
                    </h3>
                    <p className="text-sm text-gray-600 mt-1">
                      {examData?.all_submitted 
                        ? 'You can start grading now'
                        : 'You can start grading now, or wait for more submissions'}
                    </p>
                  </div>
                  <Button
                    onClick={handleGradeNow}
                    disabled={grading}
                    className="bg-primary hover:bg-primary/90"
                    size="lg"
                  >
                    {grading ? (
                      <>
                        <Clock className="w-5 h-5 mr-2 animate-spin" />
                        Starting...
                      </>
                    ) : (
                      <>
                        <PlayCircle className="w-5 h-5 mr-2" />
                        Grade Now
                      </>
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Submitted Students */}
        {submittedStudents.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-green-600" />
              Submitted ({submittedStudents.length})
            </h2>
            <Card>
              <CardContent className="p-0">
                <div className="divide-y">
                  {submittedStudents.map(student => (
                    <div key={student.student_id} className="p-4 flex items-center justify-between hover:bg-gray-50">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
                          <CheckCircle className="w-5 h-5 text-green-600" />
                        </div>
                        <div>
                          <p className="font-semibold text-gray-900">{student.name}</p>
                          <p className="text-sm text-gray-500">{student.email}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-sm text-green-600 font-medium">Submitted</p>
                        <p className="text-xs text-gray-500">
                          {new Date(student.submitted_at).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Pending Students */}
        {pendingStudents.length > 0 && (
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Clock className="w-5 h-5 text-orange-600" />
              Pending Submission ({pendingStudents.length})
            </h2>
            <Card>
              <CardContent className="p-0">
                <div className="divide-y">
                  {pendingStudents.map(student => (
                    <div key={student.student_id} className="p-4 flex items-center justify-between hover:bg-gray-50">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-orange-100 flex items-center justify-center">
                          <Clock className="w-5 h-5 text-orange-600" />
                        </div>
                        <div>
                          <p className="font-semibold text-gray-900">{student.name}</p>
                          <p className="text-sm text-gray-500">{student.email}</p>
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleRemoveStudent(student.student_id)}
                        disabled={removing === student.student_id}
                        className="text-red-600 hover:text-red-700 hover:bg-red-50"
                      >
                        <Trash2 className="w-4 h-4 mr-1" />
                        Remove
                      </Button>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
            <div className="mt-4 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-sm text-yellow-800">
                💡 <strong>Tip:</strong> You can remove non-submitting students and start grading with the students who have already submitted.
              </p>
            </div>
          </div>
        )}

        {/* Empty State */}
        {examData?.students?.length === 0 && (
          <Card>
            <CardContent className="p-12 text-center">
              <XCircle className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-600 mb-2">No Students Assigned</h3>
              <p className="text-gray-500">This exam has no students assigned to it</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
};

export default ExamSubmissionsView;
