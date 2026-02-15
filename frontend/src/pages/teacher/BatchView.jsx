import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Settings, UserPlus, AlertCircle, TrendingUp, Users, FileText, Eye, EyeOff, CheckCircle2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '../../components/ui/dialog';
import { Button } from '../../components/ui/button';
import { Checkbox } from '../../components/ui/checkbox';
import { Label } from '../../components/ui/label';
import { toast } from 'sonner';
import StudentProfileDrawer from '../../components/StudentProfileDrawer';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const BatchView = () => {
  const { batchId } = useParams();
  const navigate = useNavigate();
  
  const [batch, setBatch] = useState(null);
  const [exams, setExams] = useState([]);
  const [students, setStudents] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedStudent, setSelectedStudent] = useState(null);
  const [activeTab, setActiveTab] = useState('exams');
  const [showAtRiskOnly, setShowAtRiskOnly] = useState(false);
  
  // Publish dialog state
  const [publishDialogOpen, setPublishDialogOpen] = useState(false);
  const [examToPublish, setExamToPublish] = useState(null);
  const [publishSettings, setPublishSettings] = useState({
    show_model_answer: false,
    show_answer_sheet: true,
    show_question_paper: true
  });

  useEffect(() => {
    fetchBatchData();
  }, [batchId]);

  const fetchBatchData = async () => {
    try {
      // Fetch batch details
      const batchRes = await axios.get(`${API}/batches/${batchId}`, { withCredentials: true });
      setBatch(batchRes.data);

      // Fetch stats
      const statsRes = await axios.get(`${API}/batches/${batchId}/stats`, { withCredentials: true });
      setStats(statsRes.data);

      // Fetch exams for this batch
      const examsRes = await axios.get(`${API}/exams?batch_id=${batchId}`, { withCredentials: true });
      setExams(examsRes.data);

      // Fetch students
      const studentsRes = await axios.get(`${API}/batches/${batchId}/students`, { withCredentials: true });
      setStudents(studentsRes.data);
      
    } catch (error) {
      console.error('Error fetching batch data:', error);
    } finally {
      setLoading(false);
    }
  };

  const getExamStatus = (exam) => {
    if (exam.status === 'processing') return { label: 'Grading', color: 'yellow' };
    if (exam.status === 'completed') return { label: 'Completed', color: 'green' };
    return { label: 'Upcoming', color: 'gray' };
  };

  const handlePublishClick = (exam, e) => {
    e.stopPropagation(); // Prevent card click
    setExamToPublish(exam);
    setPublishDialogOpen(true);
  };

  const publishResults = async () => {
    if (!examToPublish) return;
    
    try {
      await axios.post(`${API}/exams/${examToPublish.exam_id}/publish-results`, publishSettings, {
        withCredentials: true
      });
      toast.success("Results published! Students can now see their scores.");
      setPublishDialogOpen(false);
      fetchBatchData(); // Refresh data
    } catch (error) {
      console.error("Publish error:", error);
      toast.error("Failed to publish results");
    }
  };

  const unpublishResults = async (examId, e) => {
    e.stopPropagation(); // Prevent card click
    
    try {
      await axios.post(`${API}/exams/${examId}/unpublish-results`, {}, {
        withCredentials: true
      });
      toast.success("Results hidden from students");
      fetchBatchData(); // Refresh data
    } catch (error) {
      console.error("Unpublish error:", error);
      toast.error("Failed to unpublish results");
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      {/* Header */}
      <div className="max-w-7xl mx-auto mb-6">
        <button
          onClick={() => navigate('/teacher/dashboard')}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </button>

        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">{batch?.name}</h1>
            <p className="text-gray-500 mt-1">{batch?.subject || 'General'}</p>
          </div>
          
          <div className="flex gap-3">
            <button
              onClick={() => navigate(`/teacher/batch/${batchId}/create-student-exam`)}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
            >
              <FileText className="w-4 h-4" />
              Create Exam for Students
            </button>
            <button
              onClick={() => navigate(`/teacher/batch/${batchId}/students/add`)}
              className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <UserPlus className="w-4 h-4" />
              Manage Students
            </button>
            <button
              onClick={() => navigate(`/teacher/batch/${batchId}/settings`)}
              className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <Settings className="w-4 h-4" />
              Settings
            </button>
          </div>
        </div>
      </div>

      {/* Stats Cards (The Pulse) */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Action Required */}
          <Card className="border-l-4 border-l-orange-500">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-orange-600">
                <AlertCircle className="w-5 h-5" />
                Action Required
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-4xl font-bold text-gray-900 mb-2">
                {stats?.action_required || 0}
              </div>
              <p className="text-sm text-gray-600">Papers to review</p>
              <button
                onClick={() => navigate(`/teacher/review?batch_id=${batchId}`)}
                className="text-sm text-orange-600 hover:underline mt-4"
              >
                Review Now →
              </button>
            </CardContent>
          </Card>

          {/* Class Average */}
          <Card className="border-l-4 border-l-blue-500">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-blue-600">
                <TrendingUp className="w-5 h-5" />
                Class Average
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-4xl font-bold text-gray-900 mb-2">
                {stats?.class_average || 0}%
              </div>
              <p className="text-sm text-gray-600">vs. previous exams</p>
              <button
                onClick={() => navigate(`/teacher/analytics?batch_id=${batchId}`)}
                className="text-sm text-blue-600 hover:underline mt-4"
              >
                View Trend →
              </button>
            </CardContent>
          </Card>

          {/* At Risk Students */}
          <Card className="border-l-4 border-l-red-500">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-red-600">
                <Users className="w-5 h-5" />
                Needs Support
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-4xl font-bold text-gray-900 mb-2">
                {stats?.at_risk_count || 0}
              </div>
              <p className="text-sm text-gray-600">Students below 40%</p>
              <button
                onClick={() => {
                  setShowAtRiskOnly(true);
                  setActiveTab('students');
                }}
                className="text-sm text-red-600 hover:underline mt-4"
              >
                View List →
              </button>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Tabs: Exams & Students */}
      <div className="max-w-7xl mx-auto">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="grid w-full max-w-md grid-cols-2">
            <TabsTrigger value="exams">Exams</TabsTrigger>
            <TabsTrigger value="students">Students</TabsTrigger>
          </TabsList>

          {/* Exams Tab */}
          <TabsContent value="exams" className="mt-6">
            <div className="space-y-6">
              {/* Student-Upload Exams (Awaiting Submissions) */}
              {exams.filter(e => e.exam_mode === 'student_upload' && e.status === 'awaiting_submissions').length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-4">Student Upload - Awaiting Submissions</h3>
                  <div className="space-y-3">
                    {exams.filter(e => e.exam_mode === 'student_upload' && e.status === 'awaiting_submissions').map(exam => (
                      <Card key={exam.exam_id} className="border-l-4 border-l-blue-500 hover:shadow-md transition-shadow cursor-pointer"
                        onClick={() => navigate(`/teacher/exam/${exam.exam_id}/submissions`)}>
                        <CardContent className="p-4 flex items-center justify-between">
                          <div className="flex-1">
                            <h4 className="font-semibold text-gray-900">{exam.exam_name}</h4>
                            <p className="text-sm text-gray-600 mt-1">
                              {exam.submitted_count || 0}/{exam.total_students || 0} Students Submitted
                            </p>
                          </div>
                          <button className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors">
                            View Submissions
                          </button>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </div>
              )}

              {/* Active/Grading */}
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Active / Grading</h3>
                <div className="space-y-3">
                  {exams.filter(e => e.status === 'processing').map(exam => (
                    <Card key={exam.exam_id} className="border-l-4 border-l-yellow-500 hover:shadow-md transition-shadow cursor-pointer"
                      onClick={() => navigate(`/teacher/exam/${exam.exam_id}`)}>
                      <CardContent className="p-4 flex items-center justify-between">
                        <div className="flex-1">
                          <h4 className="font-semibold text-gray-900">{exam.exam_name}</h4>
                          <p className="text-sm text-gray-600 mt-1">
                            {exam.graded_count}/{exam.total_papers} Graded
                          </p>
                        </div>
                        <button className="px-4 py-2 bg-yellow-500 text-white rounded-lg hover:bg-yellow-600 transition-colors">
                          Continue Grading
                        </button>
                      </CardContent>
                    </Card>
                  ))}
                  {exams.filter(e => e.status === 'processing').length === 0 && (
                    <p className="text-gray-500 text-center py-8">No active grading</p>
                  )}
                </div>
              </div>

              {/* Completed */}
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Completed</h3>
                <div className="space-y-3">
                  {exams.filter(e => e.status === 'completed').map(exam => (
                    <Card key={exam.exam_id} className="border-l-4 border-l-green-500 hover:shadow-md transition-shadow">
                      <CardContent className="p-4">
                        <div className="flex items-center justify-between mb-3">
                          <div 
                            className="flex-1 cursor-pointer"
                            onClick={() => navigate(`/teacher/analytics?exam_id=${exam.exam_id}`)}
                          >
                            <h4 className="font-semibold text-gray-900">{exam.exam_name}</h4>
                            <p className="text-sm text-gray-600 mt-1">
                              Avg: {exam.average_score}% • {exam.total_submissions || 0} submissions
                            </p>
                          </div>
                          {exam.results_published && (
                            <span className="px-2 py-1 bg-green-100 text-green-700 text-xs font-medium rounded-full">
                              Published
                            </span>
                          )}
                        </div>
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => navigate(`/teacher/analytics?exam_id=${exam.exam_id}`)}
                            className="flex-1"
                          >
                            <FileText className="w-4 h-4 mr-2" />
                            View Analytics
                          </Button>
                          {exam.results_published ? (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={(e) => unpublishResults(exam.exam_id, e)}
                              className="flex-1 border-orange-300 text-orange-600 hover:bg-orange-50"
                            >
                              <EyeOff className="w-4 h-4 mr-2" />
                              Unpublish
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              onClick={(e) => handlePublishClick(exam, e)}
                              className="flex-1 bg-green-500 hover:bg-green-600"
                            >
                              <Eye className="w-4 h-4 mr-2" />
                              Publish Results
                            </Button>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                  {exams.filter(e => e.status === 'completed').length === 0 && (
                    <p className="text-gray-500 text-center py-8">No completed exams yet</p>
                  )}
                </div>
              </div>
            </div>
          </TabsContent>

          {/* Students Tab */}
          <TabsContent value="students" className="mt-6">
            {showAtRiskOnly && (
              <div className="mb-4 flex items-center justify-between bg-red-50 border border-red-200 rounded-lg p-4">
                <div className="flex items-center gap-2 text-red-700">
                  <AlertCircle className="w-5 h-5" />
                  <span className="font-semibold">Showing students below 40% only</span>
                </div>
                <button
                  onClick={() => setShowAtRiskOnly(false)}
                  className="text-sm text-red-600 hover:underline"
                >
                  Show All Students
                </button>
              </div>
            )}
            <Card>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-gray-50 border-b">
                      <tr>
                        <th className="text-left p-4 text-sm font-semibold text-gray-700">Name</th>
                        <th className="text-left p-4 text-sm font-semibold text-gray-700">Roll Number</th>
                        <th className="text-center p-4 text-sm font-semibold text-gray-700">Avg Score</th>
                        <th className="text-center p-4 text-sm font-semibold text-gray-700">Trend</th>
                        <th className="text-center p-4 text-sm font-semibold text-gray-700">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {students
                        .filter(student => !showAtRiskOnly || (student.average < 40))
                        .map(student => (
                        <tr
                          key={student.student_id}
                          onClick={() => setSelectedStudent(student)}
                          className="hover:bg-gray-50 cursor-pointer transition-colors"
                        >
                          <td className="p-4">
                            <div className="font-medium text-gray-900">{student.name}</div>
                            <div className="text-sm text-gray-500">{student.email}</div>
                          </td>
                          <td className="p-4 text-gray-700">{student.roll_number || '-'}</td>
                          <td className="p-4 text-center">
                            <span className={`font-semibold ${
                              student.average >= 75 ? 'text-green-600' :
                              student.average >= 40 ? 'text-yellow-600' :
                              'text-red-600'
                            }`}>
                              {student.average || 0}%
                            </span>
                          </td>
                          <td className="p-4 text-center">
                            <span className="text-2xl">
                              {student.trend === 'up' ? '↗️' : student.trend === 'down' ? '↘️' : '→'}
                            </span>
                          </td>
                          <td className="p-4 text-center">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedStudent(student);
                              }}
                              className="text-primary hover:underline text-sm"
                            >
                              View Profile
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            {students.length === 0 && (
              <div className="text-center py-12">
                <Users className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-gray-600 mb-2">No Students Yet</h3>
                <p className="text-gray-500 mb-6">Add students to this batch to start tracking performance</p>
                <button
                  onClick={() => navigate(`/teacher/batch/${batchId}/students/add`)}
                  className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                >
                  Add Students
                </button>
              </div>
            )}
            {students.length > 0 && showAtRiskOnly && students.filter(s => s.average < 40).length === 0 && (
              <div className="text-center py-12">
                <Users className="w-16 h-16 text-green-300 mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-green-600 mb-2">Great News!</h3>
                <p className="text-gray-600 mb-6">No students are below 40%. Everyone is doing well!</p>
                <button
                  onClick={() => setShowAtRiskOnly(false)}
                  className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                >
                  View All Students
                </button>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>

      {/* Student Profile Drawer */}
      {selectedStudent && (
        <StudentProfileDrawer
          student={selectedStudent}
          batchId={batchId}
          onClose={() => setSelectedStudent(null)}
        />
      )}

      {/* Publish Results Dialog */}
      <Dialog open={publishDialogOpen} onOpenChange={setPublishDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Publish Results - Configure Student Visibility</DialogTitle>
            <DialogDescription>
              Choose what students can see when viewing their results for {examToPublish?.exam_name}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div>
                  <Label className="font-medium">Show Question Paper</Label>
                  <p className="text-xs text-muted-foreground">Students can see the original questions</p>
                </div>
                <Checkbox 
                  checked={publishSettings.show_question_paper}
                  onCheckedChange={(checked) => 
                    setPublishSettings(prev => ({...prev, show_question_paper: checked}))
                  }
                />
              </div>

              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div>
                  <Label className="font-medium">Show Answer Sheet</Label>
                  <p className="text-xs text-muted-foreground">Students can see their submitted answer paper</p>
                </div>
                <Checkbox 
                  checked={publishSettings.show_answer_sheet}
                  onCheckedChange={(checked) => 
                    setPublishSettings(prev => ({...prev, show_answer_sheet: checked}))
                  }
                />
              </div>

              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div>
                  <Label className="font-medium">Show Model Answer</Label>
                  <p className="text-xs text-muted-foreground">Students can see the correct model answer</p>
                </div>
                <Checkbox 
                  checked={publishSettings.show_model_answer}
                  onCheckedChange={(checked) => 
                    setPublishSettings(prev => ({...prev, show_model_answer: checked}))
                  }
                />
              </div>
            </div>

            <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm text-blue-800">
                <CheckCircle2 className="inline h-4 w-4 mr-1" />
                <strong>Note:</strong> Feedback and scores are always visible to students
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishDialogOpen(false)}>
              Cancel
            </Button>
            <Button 
              onClick={publishResults}
              className="bg-green-500 hover:bg-green-600"
            >
              <Eye className="w-4 h-4 mr-2" />
              Publish Results
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default BatchView;
