import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Upload, FileText, CheckCircle, Clock, AlertCircle, Download } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Badge } from '../../components/ui/badge';
import { toast } from 'sonner';
import Layout from '../../components/Layout';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const StudentExams = ({ user }) => {
  const navigate = useNavigate();
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [selectedExam, setSelectedExam] = useState(null);
  const [answerFile, setAnswerFile] = useState(null);

  useEffect(() => {
    fetchExams();
  }, []);

  const fetchExams = async () => {
    try {
      // Get all student-upload exams where this student is selected
      const response = await axios.get(`${API}/exams`, { withCredentials: true });
      const allExams = response.data;
      
      // Filter student-upload exams where student is in selected list
      const studentExams = allExams.filter(exam => 
        exam.exam_mode === 'student_upload' && 
        exam.selected_students?.includes(user.user_id)
      );
      
      // Check submission status for each
      const examsWithStatus = await Promise.all(
        studentExams.map(async (exam) => {
          try {
            const subCheck = await axios.get(
              `${API}/exams/${exam.exam_id}/submissions-status`,
              { withCredentials: true }
            );
            const studentData = subCheck.data.students.find(s => s.student_id === user.user_id);
            return {
              ...exam,
              has_submitted: studentData?.submitted || false,
              submitted_at: studentData?.submitted_at
            };
          } catch {
            return { ...exam, has_submitted: false };
          }
        })
      );
      
      setExams(examsWithStatus);
    } catch (error) {
      console.error('Error fetching exams:', error);
      toast.error('Failed to load exams');
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadQuestion = async (exam) => {
    try {
      const response = await axios.get(
        `${API}/exams/${exam.exam_id}/question-paper`,
        { 
          withCredentials: true,
          responseType: 'blob'
        }
      );
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${exam.exam_name}_question.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      
      toast.success('Question paper downloaded');
    } catch (error) {
      console.error('Error downloading question paper:', error);
      toast.error('Failed to download question paper');
    }
  };

  const handleSubmit = async () => {
    if (!answerFile) {
      toast.error('Please select a file');
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('answer_paper', answerFile);
      
      await axios.post(
        `${API}/exams/${selectedExam.exam_id}/submit`,
        formData,
        {
          withCredentials: true,
          headers: { 'Content-Type': 'multipart/form-data' }
        }
      );
      
      toast.success('Answer submitted successfully!');
      setSelectedExam(null);
      setAnswerFile(null);
      fetchExams();
    } catch (error) {
      console.error('Error submitting answer:', error);
      toast.error(error.response?.data?.detail || 'Failed to submit answer');
    } finally {
      setUploading(false);
    }
  };

  if (loading) {
    return (
      <Layout user={user}>
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout user={user}>
      <div className="p-6">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">My Exams</h1>
        <p className="text-gray-500 mb-8">Upload your answer papers for assigned exams</p>

        {exams.length === 0 ? (
          <Card>
            <CardContent className="p-12 text-center">
              <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-600 mb-2">No Exams Yet</h3>
              <p className="text-gray-500">Your teacher hasn't assigned any exams</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {exams.map((exam) => (
              <Card key={exam.exam_id} className={exam.has_submitted ? 'border-green-200' : 'border-orange-200'}>
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <CardTitle className="text-lg">{exam.exam_name}</CardTitle>
                    {exam.has_submitted ? (
                      <Badge className="bg-green-100 text-green-700">
                        <CheckCircle className="w-3 h-3 mr-1" />
                        Submitted
                      </Badge>
                    ) : (
                      <Badge className="bg-orange-100 text-orange-700">
                        <Clock className="w-3 h-3 mr-1" />
                        Pending
                      </Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div>
                      <p className="text-gray-600">Total Marks</p>
                      <p className="font-semibold">{exam.total_marks}</p>
                    </div>
                    <div>
                      <p className="text-gray-600">Grading Mode</p>
                      <p className="font-semibold capitalize">{exam.grading_mode}</p>
                    </div>
                  </div>
                  
                  {exam.has_submitted ? (
                    <div className="bg-green-50 border border-green-200 rounded-lg p-3">
                      <p className="text-sm text-green-800">
                        \u2713 Submitted on {new Date(exam.submitted_at).toLocaleString()}
                      </p>
                      <p className="text-xs text-green-600 mt-1">
                        Waiting for teacher to grade
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {exam.show_question_paper && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleDownloadQuestion(exam)}
                          className="w-full"
                        >
                          <Download className="w-4 h-4 mr-2" />
                          Download Question Paper
                        </Button>
                      )}
                      <Button
                        onClick={() => setSelectedExam(exam)}
                        className="w-full"
                      >
                        <Upload className="w-4 h-4 mr-2" />
                        Upload Answer Paper
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Upload Dialog */}
        {selectedExam && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
            <Card className="w-full max-w-lg">
              <CardHeader>
                <CardTitle>Upload Answer Paper</CardTitle>
                <p className="text-sm text-gray-600">{selectedExam.exam_name}</p>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
                  <p className="text-sm text-orange-800 font-semibold">
                    <AlertCircle className="w-4 h-4 inline mr-1" />
                    Important: You can only submit once. Re-submission is not allowed.
                  </p>
                </div>
                
                <div>
                  <label className="block text-sm font-medium mb-2">
                    Select your answer paper (PDF only)
                  </label>
                  <Input
                    type="file"
                    accept=".pdf"
                    onChange={(e) => setAnswerFile(e.target.files[0])}
                  />
                  {answerFile && (
                    <p className="text-sm text-green-600 mt-2">
                      \u2713 {answerFile.name}
                    </p>
                  )}
                </div>
                
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    onClick={() => {
                      setSelectedExam(null);
                      setAnswerFile(null);
                    }}
                    className="flex-1"
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={handleSubmit}
                    disabled={!answerFile || uploading}
                    className="flex-1"
                  >
                    {uploading ? 'Uploading...' : 'Submit Answer'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </Layout>
  );
};

export default StudentExams;
