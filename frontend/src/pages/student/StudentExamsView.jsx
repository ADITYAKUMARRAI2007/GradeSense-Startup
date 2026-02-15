import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { FileUp, Download, Clock, CheckCircle, AlertCircle, Upload } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../../components/ui/dialog';
import { toast } from 'sonner';
import Layout from '../../components/Layout';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const StudentExamsView = ({ user }) => {
  const navigate = useNavigate();
  const [exams, setExams] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [selectedExam, setSelectedExam] = useState(null);
  const [answerFile, setAnswerFile] = useState(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    fetchAvailableExams();
  }, []);

  const fetchAvailableExams = async () => {
    try {
      const response = await axios.get(`${API}/students/my-exams`, { withCredentials: true });
      setExams(response.data);
    } catch (error) {
      console.error('Error fetching exams:', error);
      toast.error('Failed to load exams');
    } finally {
      setLoading(false);
    }
  };

  const handleUploadClick = (exam) => {
    setSelectedExam(exam);
    setAnswerFile(null);
    setUploadDialogOpen(true);
  };

  const handleDownloadQuestionPaper = async (exam) => {
    try {
      const response = await axios.get(`${API}/exams/${exam.exam_id}/question-paper`, {
        withCredentials: true,
        responseType: 'blob'
      });
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${exam.exam_name}_Question_Paper.pdf`);
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
      toast.error('Please select a file to upload');
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('answer_paper', answerFile);
      
      await axios.post(`${API}/exams/${selectedExam.exam_id}/submit`, formData, {
        withCredentials: true,
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      
      toast.success('Answer paper submitted successfully!');
      setUploadDialogOpen(false);
      fetchAvailableExams(); // Refresh list
    } catch (error) {
      console.error('Error submitting answer:', error);
      toast.error(error.response?.data?.detail || 'Failed to submit answer paper');
    } finally {
      setUploading(false);
    }
  };

  const pendingExams = exams.filter(e => !e.submitted && e.status === 'awaiting_submissions');
  const submittedExams = exams.filter(e => e.submitted);
  const gradedExams = exams.filter(e => e.graded);

  if (loading) {
    return (
      <Layout user={user}>
        <div className="min-h-screen flex items-center justify-center">
          <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout user={user}>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">My Exams</h1>
          <p className="text-gray-500 mt-1">View and submit your answer papers</p>
        </div>

        {/* Pending Submissions */}
        {pendingExams.length > 0 && (
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Clock className="w-5 h-5 text-orange-600" />
              Pending Submissions ({pendingExams.length})
            </h2>
            <div className="grid gap-4">
              {pendingExams.map(exam => (
                <Card key={exam.exam_id} className="border-l-4 border-l-orange-500">
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <h3 className="text-lg font-semibold text-gray-900">{exam.exam_name}</h3>
                        <p className="text-sm text-gray-600 mt-1">Batch: {exam.batch_name}</p>
                        <div className="flex items-center gap-4 mt-3">
                          <span className="text-sm text-gray-700">Total Marks: {exam.total_marks}</span>
                          <span className="text-sm text-gray-700">Mode: {exam.grading_mode}</span>
                        </div>
                      </div>
                      <div className="flex flex-col gap-2">
                        {exam.show_question_paper && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleDownloadQuestionPaper(exam)}
                          >
                            <Download className="w-4 h-4 mr-2" />
                            Question Paper
                          </Button>
                        )}
                        <Button
                          onClick={() => handleUploadClick(exam)}
                          className="bg-orange-600 hover:bg-orange-700"
                        >
                          <FileUp className="w-4 h-4 mr-2" />
                          Upload Answer
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* Submitted (Awaiting Grading) */}
        {submittedExams.length > 0 && (
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-blue-600" />
              Submitted - Awaiting Grading ({submittedExams.length})
            </h2>
            <div className="grid gap-4">
              {submittedExams.map(exam => (
                <Card key={exam.exam_id} className="border-l-4 border-l-blue-500">
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <h3 className="text-lg font-semibold text-gray-900">{exam.exam_name}</h3>
                        <p className="text-sm text-gray-600 mt-1">Batch: {exam.batch_name}</p>
                        <p className="text-sm text-green-600 mt-2">✓ Submitted on {new Date(exam.submitted_at).toLocaleDateString()}</p>
                      </div>
                      <div className="text-right">
                        <span className="inline-block px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-sm font-medium">
                          Under Review
                        </span>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* Graded */}
        {gradedExams.length > 0 && (
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-green-600" />
              Graded Exams ({gradedExams.length})
            </h2>
            <div className="grid gap-4">
              {gradedExams.map(exam => (
                <Card key={exam.exam_id} className="border-l-4 border-l-green-500">
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <h3 className="text-lg font-semibold text-gray-900">{exam.exam_name}</h3>
                        <p className="text-sm text-gray-600 mt-1">Batch: {exam.batch_name}</p>
                        <p className="text-lg font-bold text-green-600 mt-2">
                          Score: {exam.obtained_marks}/{exam.total_marks} ({exam.percentage}%)
                        </p>
                      </div>
                      <Button
                        onClick={() => navigate('/student/results')}
                        variant="outline"
                      >
                        View Details
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {/* Empty State */}
        {exams.length === 0 && (
          <Card>
            <CardContent className="p-12 text-center">
              <AlertCircle className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-600 mb-2">No Exams Available</h3>
              <p className="text-gray-500">Your teacher hasn't created any exams yet</p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Upload Dialog */}
      <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Answer Paper</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-sm text-blue-800">
                <strong>Exam:</strong> {selectedExam?.exam_name}
              </p>
              <p className="text-sm text-blue-800 mt-1">
                <strong>Total Marks:</strong> {selectedExam?.total_marks}
              </p>
            </div>
            <div>
              <Label>Select Answer Paper (PDF) *</Label>
              <Input
                type="file"
                accept=".pdf"
                onChange={(e) => setAnswerFile(e.target.files[0])}
                className="mt-1"
              />
              {answerFile && (
                <p className="text-sm text-green-600 mt-2">✓ {answerFile.name}</p>
              )}
            </div>
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-sm text-yellow-800">
                ⚠️ <strong>Note:</strong> You can only submit once. Re-submission is not allowed.
              </p>
            </div>
            <div className="flex gap-3 pt-4">
              <Button
                variant="outline"
                onClick={() => setUploadDialogOpen(false)}
                className="flex-1"
                disabled={uploading}
              >
                Cancel
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={!answerFile || uploading}
                className="flex-1"
              >
                {uploading ? (
                  <>
                    <Upload className="w-4 h-4 mr-2 animate-spin" />
                    Uploading...
                  </>
                ) : (
                  <>
                    <Upload className="w-4 h-4 mr-2" />
                    Submit Answer
                  </>
                )}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </Layout>
  );
};

export default StudentExamsView;
