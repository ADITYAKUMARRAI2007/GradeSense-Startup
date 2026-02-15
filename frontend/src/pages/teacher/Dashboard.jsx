import { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { 
  FileText, 
  Users, 
  CheckCircle, 
  Clock, 
  TrendingUp,
  AlertCircle,
  ArrowRight,
  BookOpen,
  MessageSquarePlus,
  Send,
  Lightbulb
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Textarea } from "../../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { toast } from "sonner";
import DashboardStats from "../../components/DashboardStats";

export default function TeacherDashboard({ user }) {
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [feedbackDialogOpen, setFeedbackDialogOpen] = useState(false);
  const [generalFeedback, setGeneralFeedback] = useState("");
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  
  // New: Class snapshot
  const [classSnapshot, setClassSnapshot] = useState(null);
  
  // New: Batches for DashboardStats
  const [batches, setBatches] = useState([]);
  
  const navigate = useNavigate();

  const dateString = useMemo(() => {
    return new Date().toLocaleDateString('en-US', {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
  }, []);

  useEffect(() => {
    fetchDashboard();
    fetchClassSnapshot();
    fetchBatches();
  }, []);

  const fetchDashboard = async () => {
    try {
      const response = await axios.get(`${API}/analytics/dashboard`);
      setAnalytics(response.data);
    } catch (error) {
      console.error("Error fetching dashboard:", error);
    } finally {
      setLoading(false);
    }
  };
  
  const fetchClassSnapshot = async () => {
    try {
      const response = await axios.get(`${API}/dashboard/class-snapshot`);
      setClassSnapshot(response.data);
    } catch (error) {
      console.error("Error fetching class snapshot:", error);
    }
  };
  
  const fetchBatches = async () => {
    try {
      const response = await axios.get(`${API}/batches`);
      // Filter out archived/closed batches from dashboard
      const activeBatches = response.data.filter(batch => batch.status !== 'closed' && batch.status !== 'archived');
      setBatches(activeBatches);
    } catch (error) {
      console.error("Error fetching batches:", error);
    }
  };
  
  const handleSubmissionClick = async (submission) => {
    // Navigate directly to ReviewPapers page with filters for this specific submission
    navigate(`/teacher/review?exam=${submission.exam_id}&student=${submission.student_id}`);
  };

  const handleSubmitGeneralFeedback = async () => {
    if (!generalFeedback.trim()) return;
    
    setSubmittingFeedback(true);
    try {
      await axios.post(`${API}/feedback/submit`, {
        feedback_type: "general_suggestion",
        teacher_correction: generalFeedback
      });
      setGeneralFeedback("");
      setFeedbackDialogOpen(false);
      toast.success("Feedback submitted! Thank you for helping improve the AI.");
    } catch (error) {
      console.error("Feedback error:", error);
      toast.error("Failed to submit feedback");
    } finally {
      setSubmittingFeedback(false);
    }
  };

  const stats = analytics?.stats || {};
  const recentSubmissions = analytics?.recent_submissions || [];

  return (
    <Layout user={user}>
      <div className="space-y-4 lg:space-y-6" data-testid="teacher-dashboard">
        {/* Welcome Header */}
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between lg:gap-4">
          <div>
            <h1 className="text-2xl lg:text-3xl font-bold text-foreground">
              Welcome back, {user?.name?.split(" ")[0]}!
            </h1>
            <p className="text-sm lg:text-base text-muted-foreground mt-1">
              {dateString}
            </p>
          </div>
          <Button 
            onClick={() => navigate("/teacher/upload")}
            className="rounded-full shadow-md hover:shadow-lg transition-all w-full lg:w-auto"
            data-testid="upload-papers-btn"
          >
            Upload & Grade Papers
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </div>

        {/* Class Performance Snapshot */}
        {classSnapshot && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 animate-fade-in">
            {/* Batch Info */}
            <Card className="bg-gradient-to-br from-blue-50 to-white border-blue-200 card-hover">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Users className="w-4 h-4 text-blue-600" />
                  <p className="text-xs text-muted-foreground font-medium">Batch</p>
                </div>
                <p className="text-lg font-bold text-blue-900 truncate" title={classSnapshot.batch_name}>
                  {classSnapshot.batch_name}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {classSnapshot.total_students} students
                </p>
              </CardContent>
            </Card>

            {/* Class Average */}
            <Card className="bg-gradient-to-br from-green-50 to-white border-green-200 card-hover cursor-pointer" onClick={() => navigate('/teacher/analytics')}>
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-1">
                  <TrendingUp className="w-4 h-4 text-green-600" />
                  <p className="text-xs text-muted-foreground font-medium">Class Avg</p>
                </div>
                <div className="flex items-baseline gap-2">
                  <p className="text-lg font-bold text-green-900">
                    {classSnapshot.class_average}%
                  </p>
                  {classSnapshot.trend !== 0 && (
                    <Badge variant="outline" className={`text-xs ${classSnapshot.trend > 0 ? 'text-green-600 border-green-300' : 'text-red-600 border-red-300'}`}>
                      {classSnapshot.trend > 0 ? '↗' : '↘'} {Math.abs(classSnapshot.trend)}%
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {classSnapshot.trend > 0 ? '↗ Improving' : classSnapshot.trend < 0 ? '↘ Declining' : '→ Stable'}
                </p>
              </CardContent>
            </Card>

            {/* Pass Rate */}
            <Card className="bg-gradient-to-br from-amber-50 to-white border-amber-200 card-hover cursor-pointer" onClick={() => navigate('/teacher/analytics')}>
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-1">
                  <CheckCircle className="w-4 h-4 text-amber-600" />
                  <p className="text-xs text-muted-foreground font-medium">Pass Rate</p>
                </div>
                <p className="text-lg font-bold text-amber-900">
                  {classSnapshot.pass_rate}%
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {classSnapshot.total_exams} exams
                </p>
              </CardContent>
            </Card>

            {/* Recent Exam */}
            <Card className="bg-gradient-to-br from-purple-50 to-white border-purple-200 card-hover">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-1">
                  <BookOpen className="w-4 h-4 text-purple-600" />
                  <p className="text-xs text-muted-foreground font-medium">Recent Exam</p>
                </div>
                <p className="text-sm font-bold text-purple-900 truncate" title={classSnapshot.recent_exam}>
                  {classSnapshot.recent_exam}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {classSnapshot.recent_exam_date ? new Date(classSnapshot.recent_exam_date).toLocaleDateString() : ''}
                </p>
              </CardContent>
            </Card>
          </div>
        )}

        {/* New Actionable Dashboard Stats */}
        <DashboardStats batches={batches} />

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:gap-6">
          {/* Recent Activity */}
          <Card className="lg:col-span-2 animate-fade-in stagger-2" data-testid="recent-activity">
            <CardHeader className="flex flex-row items-center justify-between p-4 lg:p-6">
              <CardTitle className="text-base lg:text-lg">Recent Submissions</CardTitle>
              <Button 
                variant="ghost" 
                size="sm"
                onClick={() => navigate("/teacher/review")}
                className="text-xs lg:text-sm"
              >
                View All
                <ArrowRight className="w-3 h-3 lg:w-4 lg:h-4 ml-1" />
              </Button>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0 lg:pt-0">
              {loading ? (
                <div className="space-y-3">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-14 lg:h-16 bg-muted animate-pulse rounded-lg" />
                  ))}
                </div>
              ) : recentSubmissions.length === 0 ? (
                <div className="text-center py-6 lg:py-8">
                  <FileText className="w-10 h-10 lg:w-12 lg:h-12 mx-auto text-muted-foreground/50 mb-3" />
                  <p className="text-sm lg:text-base text-muted-foreground">No submissions yet</p>
                  <Button 
                    variant="outline" 
                    size="sm" 
                    className="mt-3"
                    onClick={() => navigate("/teacher/upload")}
                  >
                    Upload your first paper
                  </Button>
                </div>
              ) : (
                <div className="space-y-2 lg:space-y-3">
                  {recentSubmissions.map((submission, index) => (
                    <div 
                      key={submission.submission_id}
                      className="flex items-center justify-between p-3 lg:p-4 rounded-lg bg-muted/50 hover:bg-muted hover:shadow-md transition-all cursor-pointer"
                      onClick={() => handleSubmissionClick(submission)}
                    >
                      <div className="flex items-center gap-2 lg:gap-3 min-w-0">
                        <div className="w-8 h-8 lg:w-10 lg:h-10 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                          <span className="text-xs lg:text-sm font-medium text-primary">
                            {submission.student_name?.charAt(0) || "?"}
                          </span>
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-sm lg:text-base truncate">{submission.student_name}</p>
                          <p className="text-xs lg:text-sm text-muted-foreground">
                            Score: {submission.obtained_marks || submission.total_score || 0}/{submission.total_marks || 100} ({submission.percentage || 0}%)
                          </p>
                        </div>
                      </div>
                      <Badge 
                        variant={submission.status === "teacher_reviewed" ? "default" : "secondary"}
                        className={cn(
                          "text-xs flex-shrink-0 ml-2",
                          submission.status === "ai_graded" ? "bg-yellow-100 text-yellow-700" : ""
                        )}
                      >
                        <span className="hidden sm:inline">
                          {submission.status === "ai_graded" ? "Needs Review" : "Reviewed"}
                        </span>
                        <span className="sm:hidden">
                          {submission.status === "ai_graded" ? "Review" : "Done"}
                        </span>
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Quick Actions & Alerts */}
          <div className="space-y-4 lg:space-y-6">
            {/* Pending Re-evaluations */}
            {stats.pending_reeval > 0 && (
              <Card className="border-yellow-200 bg-yellow-50/50 animate-fade-in stagger-3">
                <CardContent className="p-3 lg:p-4">
                  <div className="flex items-start gap-2 lg:gap-3">
                    <AlertCircle className="w-4 h-4 lg:w-5 lg:h-5 text-yellow-600 mt-0.5 flex-shrink-0" />
                    <div className="min-w-0">
                      <p className="font-medium text-yellow-900 text-sm lg:text-base">
                        {stats.pending_reeval} Re-evaluation Request{stats.pending_reeval > 1 ? "s" : ""}
                      </p>
                      <p className="text-xs lg:text-sm text-yellow-700 mt-1">
                        Students have requested grade reviews
                      </p>
                      <Button 
                        variant="outline" 
                        size="sm" 
                        className="mt-2 border-yellow-300 text-yellow-700 hover:bg-yellow-100 text-xs lg:text-sm"
                        onClick={() => navigate("/teacher/re-evaluations")}
                      >
                        Review Requests
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Quick Actions */}
            <Card className="animate-fade-in stagger-4" data-testid="quick-actions">
              <CardHeader className="p-4 lg:p-6 pb-2 lg:pb-3">
                <CardTitle className="text-base lg:text-lg">Quick Actions</CardTitle>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0 space-y-2">
                <Button 
                  variant="outline" 
                  className="w-full justify-start text-sm"
                  onClick={() => navigate("/teacher/upload")}
                >
                  <FileText className="w-4 h-4 mr-2" />
                  Upload New Papers
                </Button>
                <Button 
                  variant="outline" 
                  className="w-full justify-start text-sm"
                  onClick={() => navigate("/teacher/students")}
                >
                  <Users className="w-4 h-4 mr-2" />
                  Manage Students
                </Button>
                <Button 
                  variant="outline" 
                  className="w-full justify-start text-sm"
                  onClick={() => navigate("/teacher/reports")}
                >
                  <TrendingUp className="w-4 h-4 mr-2" />
                  View Reports
                </Button>
                <Button 
                  variant="outline" 
                  className="w-full justify-start text-sm text-orange-600 border-orange-200 hover:bg-orange-50"
                  onClick={() => setFeedbackDialogOpen(true)}
                >
                  <MessageSquarePlus className="w-4 h-4 mr-2" />
                  Improve AI Grading
                </Button>
              </CardContent>
            </Card>

            {/* Summary */}
            <Card className="animate-fade-in stagger-5">
              <CardContent className="p-3 lg:p-4">
                <div className="flex items-center gap-2 lg:gap-3">
                  <div className="p-2 rounded-lg bg-green-50 flex-shrink-0">
                    <CheckCircle className="w-4 h-4 lg:w-5 lg:h-5 text-green-600" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-medium text-sm lg:text-base">{stats.total_students || 0} Students</p>
                    <p className="text-xs lg:text-sm text-muted-foreground">
                      Across {stats.total_batches || 0} batches
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* General AI Feedback Dialog */}
        <Dialog open={feedbackDialogOpen} onOpenChange={setFeedbackDialogOpen}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Lightbulb className="w-5 h-5 text-orange-500" />
                Help Improve AI Grading
              </DialogTitle>
            </DialogHeader>
            
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Share general feedback or suggestions to help improve how the AI grades papers. 
                Your input helps make grading more accurate for everyone.
              </p>
              
              <div>
                <Textarea 
                  value={generalFeedback}
                  onChange={(e) => setGeneralFeedback(e.target.value)}
                  placeholder="Examples:
• The AI is too strict on partial credit
• It should give more weight to conceptual understanding
• Handwritten diagrams are often misinterpreted
• Spelling errors shouldn't affect science answers..."
                  rows={5}
                  className="text-sm"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button 
                  variant="outline" 
                  onClick={() => setFeedbackDialogOpen(false)}
                  disabled={submittingFeedback}
                >
                  Cancel
                </Button>
                <Button 
                  onClick={handleSubmitGeneralFeedback}
                  disabled={submittingFeedback || !generalFeedback.trim()}
                  className="bg-orange-500 hover:bg-orange-600"
                >
                  {submittingFeedback ? (
                    <Clock className="w-4 h-4 animate-spin mr-2" />
                  ) : (
                    <Send className="w-4 h-4 mr-2" />
                  )}
                  Submit Feedback
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </Layout>
  );
}

function cn(...classes) {
  return classes.filter(Boolean).join(' ');
}
