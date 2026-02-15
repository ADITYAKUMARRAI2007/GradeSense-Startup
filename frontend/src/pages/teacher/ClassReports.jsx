import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { ScrollArea } from "../../components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Textarea } from "../../components/ui/textarea";
import { Progress } from "../../components/ui/progress";
import { toast } from "sonner";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  Cell,
  LineChart,
  Line
} from "recharts";
import { 
  Download, 
  Users, 
  TrendingUp, 
  TrendingDown, 
  Award,
  AlertTriangle,
  FileSpreadsheet,
  Lightbulb,
  Brain,
  Target,
  ChevronRight,
  Eye,
  FileText,
  RefreshCw,
  Sparkles,
  BookOpen,
  User,
  HelpCircle,
  Layers,
  Zap,
  CheckCircle
} from "lucide-react";

const COLORS = ['#F97316', '#3B82F6', '#22C55E', '#EAB308', '#EF4444'];

export default function ClassReports({ user }) {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [batches, setBatches] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [exams, setExams] = useState([]);
  const [filters, setFilters] = useState({
    batch_id: "",
    subject_id: "",
    exam_id: ""
  });
  
  // Advanced analytics state
  const [misconceptions, setMisconceptions] = useState(null);
  const [topicMastery, setTopicMastery] = useState(null);
  const [loadingMisconceptions, setLoadingMisconceptions] = useState(false);
  const [loadingTopicMastery, setLoadingTopicMastery] = useState(false);
  
  // Student deep-dive modal
  const [selectedStudent, setSelectedStudent] = useState(null);
  const [studentDeepDive, setStudentDeepDive] = useState(null);
  const [loadingDeepDive, setLoadingDeepDive] = useState(false);
  
  // Topic detail modal
  const [selectedTopic, setSelectedTopic] = useState(null);
  
  // Review packet generation
  const [generatingReviewPacket, setGeneratingReviewPacket] = useState(false);
  const [reviewPacket, setReviewPacket] = useState(null);
  
  // Question insight modal
  const [selectedQuestionInsight, setSelectedQuestionInsight] = useState(null);

  useEffect(() => {
    fetchFiltersData();
  }, []);

  useEffect(() => {
    fetchReport();
  }, [filters]);
  
  useEffect(() => {
    if (filters.exam_id) {
      fetchMisconceptions();
      fetchTopicMastery();
    } else {
      setMisconceptions(null);
      fetchTopicMastery();
    }
  }, [filters.exam_id, filters.batch_id]);

  const fetchFiltersData = async () => {
    try {
      const [batchesRes, subjectsRes, examsRes] = await Promise.all([
        axios.get(`${API}/batches`),
        axios.get(`${API}/subjects`),
        axios.get(`${API}/exams`)
      ]);
      setBatches(batchesRes.data);
      setSubjects(subjectsRes.data);
      setExams(examsRes.data);
    } catch (error) {
      console.error("Error fetching filter data:", error);
    }
  };

  const fetchReport = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.batch_id) params.append("batch_id", filters.batch_id);
      if (filters.subject_id) params.append("subject_id", filters.subject_id);
      if (filters.exam_id) params.append("exam_id", filters.exam_id);
      
      const response = await axios.get(`${API}/analytics/class-report?${params}`);
      setReport(response.data);
    } catch (error) {
      console.error("Error fetching report:", error);
    } finally {
      setLoading(false);
    }
  };
  
  const fetchMisconceptions = async () => {
    if (!filters.exam_id) return;
    
    setLoadingMisconceptions(true);
    try {
      const response = await axios.get(`${API}/analytics/misconceptions?exam_id=${filters.exam_id}`);
      setMisconceptions(response.data);
    } catch (error) {
      console.error("Error fetching misconceptions:", error);
    } finally {
      setLoadingMisconceptions(false);
    }
  };
  
  const fetchTopicMastery = async () => {
    setLoadingTopicMastery(true);
    try {
      const params = new URLSearchParams();
      if (filters.exam_id) params.append("exam_id", filters.exam_id);
      if (filters.batch_id) params.append("batch_id", filters.batch_id);
      
      const response = await axios.get(`${API}/analytics/topic-mastery?${params}`);
      setTopicMastery(response.data);
    } catch (error) {
      console.error("Error fetching topic mastery:", error);
    } finally {
      setLoadingTopicMastery(false);
    }
  };
  
  const fetchStudentDeepDive = async (studentId, studentName) => {
    setSelectedStudent({ student_id: studentId, name: studentName });
    setLoadingDeepDive(true);
    try {
      const params = filters.exam_id ? `?exam_id=${filters.exam_id}` : "";
      const response = await axios.get(`${API}/analytics/student-deep-dive/${studentId}${params}`);
      setStudentDeepDive(response.data);
    } catch (error) {
      console.error("Error fetching student deep dive:", error);
      toast.error("Failed to load student details");
    } finally {
      setLoadingDeepDive(false);
    }
  };
  
  const generateReviewPacket = async () => {
    if (!filters.exam_id) {
      toast.error("Please select an exam first");
      return;
    }
    
    setGeneratingReviewPacket(true);
    try {
      const response = await axios.post(`${API}/analytics/generate-review-packet?exam_id=${filters.exam_id}`);
      setReviewPacket(response.data);
      toast.success("Review packet generated!");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to generate review packet");
    } finally {
      setGeneratingReviewPacket(false);
    }
  };

  const overview = report?.overview || {};
  const scoreDistribution = report?.score_distribution || [];
  const topPerformers = report?.top_performers || [];
  const needsAttention = report?.needs_attention || [];
  const questionAnalysis = report?.question_analysis || [];

  const exportReport = () => {
    const csvContent = [
      ["Class Report"],
      [""],
      ["Overview"],
      ["Total Students", overview.total_students],
      ["Average Score", `${overview.avg_score}%`],
      ["Highest Score", `${overview.highest_score}%`],
      ["Lowest Score", `${overview.lowest_score}%`],
      ["Pass Percentage", `${overview.pass_percentage}%`],
      [""],
      ["Top Performers"],
      ["Name", "Score", "Percentage"],
      ...topPerformers.map(p => [p.name, p.score, `${p.percentage}%`]),
      [""],
      ["Needs Attention"],
      ["Name", "Score", "Percentage"],
      ...needsAttention.map(p => [p.name, p.score, `${p.percentage}%`])
    ].map(row => row.join(",")).join("\n");

    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "class_report.csv";
    a.click();
  };
  
  const getScoreColor = (percentage) => {
    if (percentage >= 70) return "text-green-600";
    if (percentage >= 50) return "text-amber-600";
    return "text-red-600";
  };
  
  const getScoreBg = (percentage) => {
    if (percentage >= 70) return "bg-green-50 border-green-200";
    if (percentage >= 50) return "bg-amber-50 border-amber-200";
    return "bg-red-50 border-red-200";
  };

  return (
    <Layout user={user}>
      <div className="space-y-4 lg:space-y-6" data-testid="class-reports-page">
        {/* Header with Filters */}
        <Card>
          <CardContent className="p-3 lg:p-4">
            <div className="flex flex-col sm:flex-row sm:flex-wrap items-stretch sm:items-center gap-3 lg:gap-4">
              <Select 
                value={filters.batch_id || "all"} 
                onValueChange={(v) => setFilters(prev => ({ ...prev, batch_id: v === "all" ? "" : v }))}
              >
                <SelectTrigger className="w-full sm:w-40 lg:w-48 text-sm" data-testid="batch-filter">
                  <SelectValue placeholder="All Batches" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Batches</SelectItem>
                  {batches.map(batch => (
                    <SelectItem key={batch.batch_id} value={batch.batch_id}>
                      {batch.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select 
                value={filters.subject_id || "all"} 
                onValueChange={(v) => setFilters(prev => ({ ...prev, subject_id: v === "all" ? "" : v }))}
              >
                <SelectTrigger className="w-full sm:w-40 lg:w-48 text-sm" data-testid="subject-filter">
                  <SelectValue placeholder="All Subjects" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Subjects</SelectItem>
                  {subjects.map(subject => (
                    <SelectItem key={subject.subject_id} value={subject.subject_id}>
                      {subject.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select 
                value={filters.exam_id || "all"} 
                onValueChange={(v) => setFilters(prev => ({ ...prev, exam_id: v === "all" ? "" : v }))}
              >
                <SelectTrigger className="w-full sm:w-40 lg:w-48 text-sm" data-testid="exam-filter">
                  <SelectValue placeholder="All Exams" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Exams</SelectItem>
                  {exams.map(exam => (
                    <SelectItem key={exam.exam_id} value={exam.exam_id}>
                      {exam.exam_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="sm:ml-auto flex gap-2">
                <Button variant="outline" onClick={exportReport} data-testid="export-btn" className="text-sm">
                  <Download className="w-4 h-4 mr-2" />
                  Export
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Overview Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 lg:gap-4">
          <Card className="animate-fade-in">
            <CardContent className="p-3 lg:p-4">
              <div className="flex items-center gap-2 lg:gap-3">
                <div className="p-1.5 lg:p-2 rounded-lg bg-blue-50 flex-shrink-0">
                  <Users className="w-4 h-4 lg:w-5 lg:h-5 text-blue-600" />
                </div>
                <div className="min-w-0">
                  <p className="text-lg lg:text-2xl font-bold">{overview.total_students || 0}</p>
                  <p className="text-xs lg:text-sm text-muted-foreground truncate">Total Students</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="animate-fade-in stagger-1">
            <CardContent className="p-3 lg:p-4">
              <div className="flex items-center gap-2 lg:gap-3">
                <div className="p-1.5 lg:p-2 rounded-lg bg-orange-50 flex-shrink-0">
                  <TrendingUp className="w-4 h-4 lg:w-5 lg:h-5 text-orange-600" />
                </div>
                <div className="min-w-0">
                  <p className={`text-lg lg:text-2xl font-bold ${getScoreColor(overview.avg_score || 0)}`}>
                    {overview.avg_score || 0}%
                  </p>
                  <p className="text-xs lg:text-sm text-muted-foreground truncate">Class Average</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="animate-fade-in stagger-2">
            <CardContent className="p-3 lg:p-4">
              <div className="flex items-center gap-2 lg:gap-3">
                <div className="p-1.5 lg:p-2 rounded-lg bg-green-50 flex-shrink-0">
                  <Award className="w-4 h-4 lg:w-5 lg:h-5 text-green-600" />
                </div>
                <div className="min-w-0">
                  <p className="text-lg lg:text-2xl font-bold text-green-600">{overview.highest_score || 0}%</p>
                  <p className="text-xs lg:text-sm text-muted-foreground truncate">Highest Score</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="animate-fade-in stagger-3">
            <CardContent className="p-3 lg:p-4">
              <div className="flex items-center gap-2 lg:gap-3">
                <div className="p-1.5 lg:p-2 rounded-lg bg-red-50 flex-shrink-0">
                  <TrendingDown className="w-4 h-4 lg:w-5 lg:h-5 text-red-600" />
                </div>
                <div className="min-w-0">
                  <p className="text-lg lg:text-2xl font-bold text-red-600">{overview.lowest_score || 0}%</p>
                  <p className="text-xs lg:text-sm text-muted-foreground truncate">Lowest Score</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="animate-fade-in stagger-4 col-span-2 lg:col-span-1">
            <CardContent className="p-3 lg:p-4">
              <div className="flex items-center gap-2 lg:gap-3">
                <div className="p-1.5 lg:p-2 rounded-lg bg-purple-50 flex-shrink-0">
                  <FileSpreadsheet className="w-4 h-4 lg:w-5 lg:h-5 text-purple-600" />
                </div>
                <div className="min-w-0">
                  <p className={`text-lg lg:text-2xl font-bold ${getScoreColor(overview.pass_percentage || 0)}`}>
                    {overview.pass_percentage || 0}%
                  </p>
                  <p className="text-xs lg:text-sm text-muted-foreground truncate">Pass Rate</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Actionable Buttons */}
        {filters.exam_id && (
          <Card className="border-orange-200 bg-gradient-to-r from-orange-50 to-white">
            <CardContent className="p-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <h3 className="font-semibold flex items-center gap-2">
                    <Zap className="w-5 h-5 text-orange-500" />
                    Quick Actions
                  </h3>
                  <p className="text-sm text-muted-foreground">AI-powered tools to help improve class performance</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button 
                    onClick={generateReviewPacket}
                    disabled={generatingReviewPacket}
                    className="bg-orange-500 hover:bg-orange-600"
                  >
                    {generatingReviewPacket ? (
                      <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Sparkles className="w-4 h-4 mr-2" />
                    )}
                    Generate Review Packet
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Topic Mastery Heatmap */}
        <Card className="animate-fade-in">
          <CardHeader className="p-4 lg:p-6">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base lg:text-lg flex items-center gap-2">
                  <Layers className="w-5 h-5 text-primary" />
                  Topic Mastery Heatmap
                </CardTitle>
                <CardDescription>Click on a topic to see details and take action</CardDescription>
              </div>
              {loadingTopicMastery && <RefreshCw className="w-4 h-4 animate-spin text-muted-foreground" />}
            </div>
          </CardHeader>
          <CardContent className="p-4 lg:p-6 pt-0">
            {!topicMastery?.topics?.length ? (
              <div className="text-center py-8 text-muted-foreground">
                <Layers className="w-12 h-12 mx-auto mb-3 opacity-30" />
                <p>No topic data available. Select an exam with graded submissions.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Legend */}
                <div className="flex items-center gap-4 text-xs">
                  <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded bg-green-500" />
                    <span>Mastered (≥70%)</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded bg-amber-500" />
                    <span>Developing (50-69%)</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-4 h-4 rounded bg-red-500" />
                    <span>Critical (&lt;50%)</span>
                  </div>
                </div>
                
                {/* Heatmap Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
                  {topicMastery.topics.map((topic, idx) => (
                    <div
                      key={idx}
                      className={`relative p-4 rounded-lg border-2 cursor-pointer transition-all hover:scale-105 hover:shadow-lg ${
                        topic.color === "green" ? "bg-green-50 border-green-300 hover:border-green-500" :
                        topic.color === "amber" ? "bg-amber-50 border-amber-300 hover:border-amber-500" :
                        "bg-red-50 border-red-300 hover:border-red-500"
                      }`}
                      onClick={() => setSelectedTopic(topic)}
                    >
                      <p className="font-medium text-sm truncate mb-1" title={topic.topic}>
                        {topic.topic}
                      </p>
                      <p className={`text-2xl font-bold ${
                        topic.color === "green" ? "text-green-700" :
                        topic.color === "amber" ? "text-amber-700" :
                        "text-red-700"
                      }`}>
                        {topic.avg_percentage}%
                      </p>
                      <div className="flex items-center gap-2 mt-2">
                        {topic.question_count > 0 && (
                          <Badge variant="outline" className="text-xs">
                            {topic.question_count} Q
                          </Badge>
                        )}
                        {topic.struggling_count > 0 && (
                          <Badge variant="outline" className="text-xs text-red-600 border-red-300">
                            {topic.struggling_count} need help
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground mt-2">Click to view details →</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Common Misconceptions (The "Why" Engine) */}
        {filters.exam_id && (
          <Card className="animate-fade-in">
            <CardHeader className="p-4 lg:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base lg:text-lg flex items-center gap-2">
                    <Brain className="w-5 h-5 text-purple-600" />
                    Common Misconceptions
                  </CardTitle>
                  <CardDescription>AI-powered analysis of why students fail specific questions</CardDescription>
                </div>
                {loadingMisconceptions && <RefreshCw className="w-4 h-4 animate-spin text-muted-foreground" />}
              </div>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0">
              {!misconceptions?.question_insights?.length ? (
                <div className="text-center py-8 text-muted-foreground">
                  <Brain className="w-12 h-12 mx-auto mb-3 opacity-30" />
                  <p>No misconception data available yet.</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* AI Analysis Summary */}
                  {misconceptions.ai_analysis?.length > 0 && (
                    <div className="p-4 bg-purple-50 border border-purple-200 rounded-lg">
                      <h4 className="font-semibold text-purple-800 mb-3 flex items-center gap-2">
                        <Lightbulb className="w-4 h-4" />
                        AI Insights
                      </h4>
                      <div className="space-y-3">
                        {misconceptions.ai_analysis.map((insight, idx) => (
                          <div key={idx} className="p-3 bg-white rounded-lg border border-purple-100">
                            <p className="font-medium text-sm mb-1">Question {insight.question}</p>
                            <p className="text-sm text-purple-700">{insight.confusion}</p>
                            {insight.recommendation && (
                              <p className="text-xs text-muted-foreground mt-2 italic">
                                💡 {insight.recommendation}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {/* Question Breakdown */}
                  <div className="space-y-2">
                    {misconceptions.question_insights.filter(q => q.fail_rate >= 20).map((question, idx) => (
                      <div 
                        key={idx}
                        className={`p-4 rounded-lg border cursor-pointer transition-all hover:shadow-md ${getScoreBg(100 - question.fail_rate)}`}
                        onClick={() => setSelectedQuestionInsight(question)}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold">Q{question.question_number}</span>
                            {question.fail_rate >= 50 && (
                              <Badge variant="destructive" className="text-xs">High Failure</Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-3">
                            <span className={`text-sm font-medium ${getScoreColor(question.avg_percentage)}`}>
                              {question.avg_percentage}% avg
                            </span>
                            <span className="text-sm text-red-600">
                              {question.failing_students}/{question.total_students} failed
                            </span>
                            <ChevronRight className="w-4 h-4 text-muted-foreground" />
                          </div>
                        </div>
                        {question.question_text && (
                          <p className="text-sm text-muted-foreground line-clamp-1">
                            {(() => {
                              let text = question.question_text;
                              // Handle nested object structure
                              if (typeof text === 'object' && text !== null) {
                                text = text.rubric || text.question_text || JSON.stringify(text);
                              }
                              return typeof text === 'string' ? text : String(text || '');
                            })()}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6">
          {/* Score Distribution */}
          <Card className="animate-fade-in stagger-2">
            <CardHeader className="p-4 lg:p-6">
              <CardTitle className="text-base lg:text-lg">Score Distribution</CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0">
              <div className="h-60 lg:h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={scoreDistribution}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                    <XAxis dataKey="range" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip 
                      contentStyle={{ 
                        backgroundColor: 'white', 
                        border: '1px solid #E2E8F0',
                        borderRadius: '8px',
                        fontSize: '12px'
                      }} 
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {scoreDistribution.map((entry, index) => {
                        const ranges = ['0-20', '21-40', '41-60', '61-80', '81-100'];
                        const colors = ['#EF4444', '#F97316', '#EAB308', '#22C55E', '#10B981'];
                        return <Cell key={`cell-${index}`} fill={colors[index] || '#F97316'} />;
                      })}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          {/* Question Analysis */}
          <Card className="animate-fade-in stagger-3">
            <CardHeader className="p-4 lg:p-6">
              <CardTitle className="text-base lg:text-lg">Question-wise Performance</CardTitle>
            </CardHeader>
            <CardContent className="p-4 lg:p-6 pt-0">
              <div className="h-60 lg:h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={questionAnalysis} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                    <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10 }} />
                    <YAxis dataKey="question" type="category" tick={{ fontSize: 10 }} width={40} tickFormatter={(v) => `Q${v}`} />
                    <Tooltip 
                      contentStyle={{ 
                        backgroundColor: 'white', 
                        border: '1px solid #E2E8F0',
                        borderRadius: '8px',
                        fontSize: '12px'
                      }}
                      formatter={(value) => [`${value}%`, 'Average']}
                    />
                    <Bar dataKey="percentage" radius={[0, 4, 4, 0]}>
                      {questionAnalysis.map((entry, index) => (
                        <Cell 
                          key={`cell-${index}`} 
                          fill={entry.percentage >= 70 ? '#22C55E' : entry.percentage >= 50 ? '#F97316' : '#EF4444'} 
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Student Lists */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Top Performers */}
          <Card className="animate-fade-in stagger-4">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Award className="w-5 h-5 text-green-600" />
                Top Performers
              </CardTitle>
            </CardHeader>
            <CardContent>
              {topPerformers.length === 0 ? (
                <p className="text-center text-muted-foreground py-4">No data available</p>
              ) : (
                <div className="space-y-3">
                  {topPerformers.map((student, index) => (
                    <div 
                      key={index} 
                      className="flex items-center justify-between p-3 bg-green-50/50 rounded-lg cursor-pointer hover:bg-green-100/50 transition-colors"
                      onClick={() => fetchStudentDeepDive(student.student_id, student.name)}
                    >
                      <div className="flex items-center gap-3">
                        <span className="w-6 h-6 rounded-full bg-green-100 flex items-center justify-center text-sm font-bold text-green-700">
                          {index + 1}
                        </span>
                        <span className="font-medium">{student.name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge className="bg-green-100 text-green-700">
                          {student.percentage}%
                        </Badge>
                        <Eye className="w-4 h-4 text-muted-foreground" />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Needs Attention */}
          <Card className="animate-fade-in stagger-5">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="w-5 h-5 text-red-600" />
                Needs Attention
              </CardTitle>
            </CardHeader>
            <CardContent>
              {needsAttention.length === 0 ? (
                <p className="text-center text-muted-foreground py-4">All students performing well!</p>
              ) : (
                <div className="space-y-3">
                  {needsAttention.map((student, index) => (
                    <div 
                      key={index} 
                      className="flex items-center justify-between p-3 bg-red-50/50 rounded-lg cursor-pointer hover:bg-red-100/50 transition-colors"
                      onClick={() => fetchStudentDeepDive(student.student_id, student.name)}
                    >
                      <div className="flex items-center gap-3">
                        <span className="w-6 h-6 rounded-full bg-red-100 flex items-center justify-center text-sm font-bold text-red-700">
                          {index + 1}
                        </span>
                        <span className="font-medium">{student.name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge className="bg-red-100 text-red-700">
                          {student.percentage}%
                        </Badge>
                        <Eye className="w-4 h-4 text-muted-foreground" />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Student Deep-Dive Modal */}
      <Dialog open={!!selectedStudent} onOpenChange={() => { setSelectedStudent(null); setStudentDeepDive(null); }}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <User className="w-5 h-5 text-primary" />
              Student Analysis: {selectedStudent?.name}
            </DialogTitle>
            <DialogDescription>
              Detailed performance breakdown with AI-generated insights
            </DialogDescription>
          </DialogHeader>
          
          {loadingDeepDive ? (
            <div className="flex items-center justify-center py-12">
              <RefreshCw className="w-8 h-8 animate-spin text-primary" />
            </div>
          ) : studentDeepDive ? (
            <div className="overflow-y-auto max-h-[60vh] pr-2">
              <div className="space-y-6 pb-4">
                {/* Overview */}
                <div className="grid grid-cols-3 gap-3">
                  <div className={`p-3 rounded-lg text-center ${studentDeepDive.overall_average >= 70 ? 'bg-green-50' : studentDeepDive.overall_average >= 50 ? 'bg-amber-50' : 'bg-red-50'}`}>
                    <p className={`text-2xl font-bold ${studentDeepDive.overall_average >= 70 ? 'text-green-600' : studentDeepDive.overall_average >= 50 ? 'text-amber-600' : 'text-red-600'}`}>
                      {studentDeepDive.overall_average}%
                    </p>
                    <p className="text-xs text-muted-foreground">Overall Average</p>
                  </div>
                  <div className="p-3 bg-muted rounded-lg text-center">
                    <p className="text-2xl font-bold">{studentDeepDive.total_exams}</p>
                    <p className="text-xs text-muted-foreground">Total Exams</p>
                  </div>
                  <div className="p-3 bg-muted rounded-lg text-center">
                    <p className="text-2xl font-bold">
                      {studentDeepDive.worst_questions?.filter(q => q.percentage < 50).length || 0}
                    </p>
                    <p className="text-xs text-muted-foreground">Areas to Improve</p>
                  </div>
                </div>
                
                {/* AI Analysis */}
                {studentDeepDive.ai_analysis && (
                  <div className="p-4 bg-purple-50 border border-purple-200 rounded-lg">
                    <h4 className="font-semibold text-purple-800 mb-2 flex items-center gap-2">
                      <Brain className="w-4 h-4" />
                      AI Analysis
                    </h4>
                    <p className="text-sm text-purple-700 mb-3">{studentDeepDive.ai_analysis.summary}</p>
                    
                    {studentDeepDive.ai_analysis.recommendations?.length > 0 && (
                      <div className="mt-3">
                        <p className="text-xs font-semibold text-purple-800 mb-1">Recommendations:</p>
                        <ul className="list-disc list-inside text-sm text-purple-700 space-y-1">
                          {studentDeepDive.ai_analysis.recommendations.map((rec, i) => (
                            <li key={i}>{rec}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    
                    {studentDeepDive.ai_analysis.concepts_to_review?.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {studentDeepDive.ai_analysis.concepts_to_review.map((concept, i) => (
                          <Badge key={i} variant="outline" className="bg-white">
                            {concept}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                
                {/* Worst Questions - Only show if student has weak areas */}
                {studentDeepDive.worst_questions?.filter(q => q.percentage < 60).length > 0 ? (
                  <div>
                    <h4 className="font-semibold mb-3 flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-red-600" />
                      Areas Needing Improvement
                    </h4>
                    <div className="space-y-3">
                      {studentDeepDive.worst_questions.filter(q => q.percentage < 60).map((q, idx) => (
                        <div key={idx} className="p-3 border rounded-lg bg-red-50/50">
                          <div className="flex items-center justify-between mb-2">
                            <span className="font-medium">{q.exam_name} - Q{q.question_number}</span>
                            <Badge variant="destructive">{q.percentage}%</Badge>
                          </div>
                          {q.question_text && (
                            <p className="text-sm text-muted-foreground mb-2 line-clamp-2">{q.question_text}</p>
                          )}
                          {q.ai_feedback && (
                            <p className="text-xs text-red-700 bg-red-100 p-2 rounded">
                              {q.ai_feedback}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : studentDeepDive.overall_average >= 60 && (
                  <div className="p-4 bg-green-50 border border-green-200 rounded-lg text-center">
                    <CheckCircle className="w-8 h-8 text-green-600 mx-auto mb-2" />
                    <p className="font-medium text-green-800">Great Performance!</p>
                    <p className="text-sm text-green-600">This student is doing well across all areas.</p>
                  </div>
                )}
                
                {/* Performance Trend */}
                {studentDeepDive.performance_trend?.length > 1 && (
                  <div>
                    <h4 className="font-semibold mb-3">Performance Trend</h4>
                    <div className="h-40">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={studentDeepDive.performance_trend}>
                          <CartesianGrid strokeDasharray="3 3" />
                          <XAxis dataKey="exam_name" tick={{ fontSize: 10 }} />
                          <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
                          <Tooltip />
                          <Line type="monotone" dataKey="percentage" stroke="#F97316" strokeWidth={2} dot={{ fill: '#F97316' }} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <p className="text-center text-muted-foreground py-8">No data available</p>
          )}
        </DialogContent>
      </Dialog>

      {/* Question Insight Modal */}
      <Dialog open={!!selectedQuestionInsight} onOpenChange={() => setSelectedQuestionInsight(null)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Question {selectedQuestionInsight?.question_number} Analysis</DialogTitle>
            <DialogDescription>
              {selectedQuestionInsight?.failing_students} of {selectedQuestionInsight?.total_students} students struggled with this question
            </DialogDescription>
          </DialogHeader>
          
          {selectedQuestionInsight && (
            <div className="space-y-4">
              {selectedQuestionInsight.question_text && (
                <div className="p-3 bg-muted rounded-lg">
                  <p className="text-sm">{selectedQuestionInsight.question_text}</p>
                </div>
              )}
              
              <div className="grid grid-cols-2 gap-3">
                <div className={`p-3 rounded-lg ${getScoreBg(selectedQuestionInsight.avg_percentage)}`}>
                  <p className="text-sm text-muted-foreground">Average Score</p>
                  <p className={`text-xl font-bold ${getScoreColor(selectedQuestionInsight.avg_percentage)}`}>
                    {selectedQuestionInsight.avg_percentage}%
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-red-50 border border-red-200">
                  <p className="text-sm text-muted-foreground">Failure Rate</p>
                  <p className="text-xl font-bold text-red-600">{selectedQuestionInsight.fail_rate}%</p>
                </div>
              </div>
              
              {selectedQuestionInsight.wrong_answers?.length > 0 && (
                <div>
                  <h4 className="font-semibold mb-2 text-sm">Sample Wrong Answers</h4>
                  <div className="space-y-2 max-h-48 overflow-y-auto">
                    {selectedQuestionInsight.wrong_answers.map((wa, idx) => (
                      <div key={idx} className="p-2 border rounded text-sm">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-medium">{wa.student_name}</span>
                          <Badge variant="destructive" className="text-xs">
                            {wa.obtained}/{wa.max}
                          </Badge>
                        </div>
                        {wa.feedback && (
                          <p className="text-xs text-muted-foreground">{wa.feedback}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Review Packet Modal */}
      <Dialog open={!!reviewPacket} onOpenChange={() => setReviewPacket(null)}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-primary" />
              AI-Generated Review Packet
            </DialogTitle>
            <DialogDescription>
              {reviewPacket?.exam_name} - {reviewPacket?.subject}
            </DialogDescription>
          </DialogHeader>
          
          {reviewPacket && (
            <ScrollArea className="flex-1 pr-4">
              <div className="space-y-4 pb-4">
                <div className="p-3 bg-orange-50 border border-orange-200 rounded-lg">
                  <p className="text-sm text-orange-800">
                    <strong>{reviewPacket.weak_areas_identified}</strong> weak areas identified. 
                    Practice questions below target these specific concepts.
                  </p>
                </div>
                
                {reviewPacket.practice_questions?.map((q, idx) => (
                  <div key={idx} className="p-4 border rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-semibold">Question {q.question_number}</span>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{q.marks} marks</Badge>
                        <Badge className={
                          q.difficulty === "easy" ? "bg-green-100 text-green-700" :
                          q.difficulty === "medium" ? "bg-amber-100 text-amber-700" :
                          "bg-red-100 text-red-700"
                        }>
                          {q.difficulty}
                        </Badge>
                      </div>
                    </div>
                    <p className="text-sm mb-2">{q.question}</p>
                    {q.topic && (
                      <p className="text-xs text-muted-foreground">Topic: {q.topic}</p>
                    )}
                    {q.hint && (
                      <p className="text-xs text-blue-600 mt-2 italic">💡 Hint: {q.hint}</p>
                    )}
                  </div>
                ))}
                
                <Button className="w-full" onClick={() => {
                  // Export as text
                  const content = reviewPacket.practice_questions?.map((q, i) => 
                    `Q${i+1}. (${q.marks} marks - ${q.difficulty})\n${q.question}\n${q.hint ? `Hint: ${q.hint}\n` : ''}`
                  ).join('\n\n');
                  const blob = new Blob([content], { type: 'text/plain' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `review_packet_${reviewPacket.exam_name}.txt`;
                  a.click();
                }}>
                  <Download className="w-4 h-4 mr-2" />
                  Download Review Packet
                </Button>
              </div>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>

      {/* Topic Detail Modal */}
      <Dialog open={!!selectedTopic} onOpenChange={() => setSelectedTopic(null)}>
        <DialogContent className="max-w-2xl max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Layers className={`w-5 h-5 ${
                selectedTopic?.color === "green" ? "text-green-600" :
                selectedTopic?.color === "amber" ? "text-amber-600" :
                "text-red-600"
              }`} />
              {selectedTopic?.topic}
            </DialogTitle>
            <DialogDescription>
              Topic performance details and action items
            </DialogDescription>
          </DialogHeader>
          
          {selectedTopic && (
            <div className="overflow-y-auto max-h-[60vh] space-y-4">
              {/* Topic Stats */}
              <div className={`p-4 rounded-lg ${getScoreBg(selectedTopic.avg_percentage)}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className={`text-3xl font-bold ${getScoreColor(selectedTopic.avg_percentage)}`}>
                      {selectedTopic.avg_percentage}%
                    </p>
                    <p className="text-sm text-muted-foreground">Class Average</p>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-semibold">{selectedTopic.sample_count} responses</p>
                    <p className="text-sm text-muted-foreground">
                      {selectedTopic.struggling_count} students need help
                    </p>
                  </div>
                </div>
              </div>

              {/* Questions in this topic */}
              {topicMastery?.questions_by_topic?.[selectedTopic.topic]?.length > 0 && (
                <div>
                  <h4 className="font-semibold mb-3 flex items-center gap-2">
                    <FileText className="w-4 h-4" />
                    Questions in this Topic
                  </h4>
                  <div className="space-y-2">
                    {topicMastery.questions_by_topic[selectedTopic.topic].map((q, idx) => (
                      <div key={idx} className="p-3 border rounded-lg bg-muted/30">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-sm">{q.exam_name} - Q{q.question_number}</span>
                          <Badge variant="outline">{q.max_marks} marks</Badge>
                        </div>
                        {q.rubric && (
                          <p className="text-xs text-muted-foreground mt-1">{q.rubric}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Students needing help */}
              {topicMastery?.students_by_topic?.[selectedTopic.topic]?.length > 0 && (
                <div>
                  <h4 className="font-semibold mb-3 flex items-center gap-2 text-red-700">
                    <AlertTriangle className="w-4 h-4" />
                    Students Needing Attention
                  </h4>
                  <div className="space-y-2">
                    {topicMastery.students_by_topic[selectedTopic.topic].map((student, idx) => (
                      <div 
                        key={idx} 
                        className="flex items-center justify-between p-3 border rounded-lg bg-red-50/50 cursor-pointer hover:bg-red-100/50"
                        onClick={() => {
                          setSelectedTopic(null);
                          fetchStudentDeepDive(student.student_id, student.name);
                        }}
                      >
                        <span className="font-medium">{student.name}</span>
                        <div className="flex items-center gap-2">
                          <Badge variant="destructive">{student.avg_score}%</Badge>
                          <Eye className="w-4 h-4 text-muted-foreground" />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Action Items */}
              <div className="p-4 bg-orange-50 border border-orange-200 rounded-lg">
                <h4 className="font-semibold mb-2 text-orange-800">Recommended Actions</h4>
                <ul className="text-sm text-orange-700 space-y-1">
                  {selectedTopic.color === "red" && (
                    <>
                      <li>• Schedule a review session focused on this topic</li>
                      <li>• Create additional practice materials</li>
                      <li>• Consider one-on-one help for struggling students</li>
                    </>
                  )}
                  {selectedTopic.color === "amber" && (
                    <>
                      <li>• Provide extra practice problems</li>
                      <li>• Review common mistakes in class</li>
                    </>
                  )}
                  {selectedTopic.color === "green" && (
                    <li>• Great job! Students have mastered this topic.</li>
                  )}
                </ul>
              </div>

              {filters.exam_id && (
                <Button 
                  className="w-full bg-orange-500 hover:bg-orange-600"
                  onClick={() => {
                    setSelectedTopic(null);
                    generateReviewPacket();
                  }}
                >
                  <Sparkles className="w-4 h-4 mr-2" />
                  Generate Practice Questions for Weak Topics
                </Button>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
