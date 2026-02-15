import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Badge } from "../../components/ui/badge";
import { Progress } from "../../components/ui/progress";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { ScrollArea } from "../../components/ui/scroll-area";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { 
  Lightbulb, 
  TrendingUp, 
  TrendingDown, 
  CheckCircle,
  AlertTriangle,
  BookOpen,
  Target,
  RefreshCw,
  Sparkles,
  Users,
  FileText,
  ArrowRight,
  Brain,
  Zap,
  Download
} from "lucide-react";

export default function ClassInsights({ user }) {
  const [insights, setInsights] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exams, setExams] = useState([]);
  const [batches, setBatches] = useState([]);
  const [selectedExam, setSelectedExam] = useState("");
  const [selectedBatch, setSelectedBatch] = useState("");
  const [generatingPacket, setGeneratingPacket] = useState(false);
  const [reviewPacket, setReviewPacket] = useState(null);
  const [actionDialogOpen, setActionDialogOpen] = useState(false);
  const [selectedAction, setSelectedAction] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchFilters();
  }, []);

  useEffect(() => {
    fetchInsights();
  }, [selectedExam, selectedBatch]);

  const fetchFilters = async () => {
    try {
      const [examsRes, batchesRes] = await Promise.all([
        axios.get(`${API}/exams`),
        axios.get(`${API}/batches`)
      ]);
      setExams(examsRes.data);
      setBatches(batchesRes.data);
    } catch (error) {
      console.error("Error fetching filters:", error);
    }
  };

  const fetchInsights = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedExam) params.append("exam_id", selectedExam);
      if (selectedBatch) params.append("batch_id", selectedBatch);
      const response = await axios.get(`${API}/analytics/insights?${params}`);
      setInsights(response.data);
    } catch (error) {
      console.error("Error fetching insights:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateReviewPacket = async () => {
    if (!selectedExam) {
      toast.error("Please select an exam first");
      return;
    }
    setGeneratingPacket(true);
    try {
      const response = await axios.post(`${API}/analytics/generate-review-packet?exam_id=${selectedExam}`);
      setReviewPacket(response.data);
      setActionDialogOpen(true);
      setSelectedAction("review-packet");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to generate review packet");
    } finally {
      setGeneratingPacket(false);
    }
  };

  const handleActionClick = (action, data) => {
    setSelectedAction(action);
    if (action === "view-reports") {
      navigate("/teacher/reports");
    } else if (action === "review-papers") {
      navigate("/teacher/review");
    } else if (action === "manage-students") {
      navigate("/teacher/students");
    } else {
      setActionDialogOpen(true);
    }
  };

  const downloadReviewPacket = () => {
    if (!reviewPacket?.practice_questions) return;
    const content = reviewPacket.practice_questions.map((q, i) => 
      `Q${i+1}. (${q.marks} marks - ${q.difficulty})\n${q.question}\n${q.hint ? `Hint: ${q.hint}\n` : ''}`
    ).join('\n\n');
    const blob = new Blob([`Review Packet: ${reviewPacket.exam_name}\n\n${content}`], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `review_packet_${reviewPacket.exam_name || 'exam'}.txt`;
    a.click();
  };

  const getScoreColor = (score) => {
    if (score >= 70) return "text-green-600";
    if (score >= 50) return "text-amber-600";
    return "text-red-600";
  };

  const getScoreBg = (score) => {
    if (score >= 70) return "bg-green-50 border-green-200";
    if (score >= 50) return "bg-amber-50 border-amber-200";
    return "bg-red-50 border-red-200";
  };

  return (
    <Layout user={user}>
      <div className="space-y-6" data-testid="class-insights-page">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Class Feedback & Insights</h1>
            <p className="text-muted-foreground">AI-generated analysis and actionable recommendations</p>
          </div>
          
          <div className="flex flex-wrap items-center gap-3">
            <Select value={selectedBatch || "all"} onValueChange={(v) => setSelectedBatch(v === "all" ? "" : v)}>
              <SelectTrigger className="w-40">
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
            
            <Select value={selectedExam || "all"} onValueChange={(v) => setSelectedExam(v === "all" ? "" : v)}>
              <SelectTrigger className="w-48">
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
            
            <Button variant="outline" onClick={fetchInsights} disabled={loading}>
              <RefreshCw className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </div>

        {/* Quick Actions */}
        <Card className="border-orange-200 bg-gradient-to-r from-orange-50 to-white">
          <CardContent className="p-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h3 className="font-semibold flex items-center gap-2">
                  <Zap className="w-5 h-5 text-orange-500" />
                  Quick Actions
                </h3>
                <p className="text-sm text-muted-foreground">Take action based on insights</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button 
                  variant="outline"
                  onClick={() => handleActionClick("review-papers")}
                  className="text-sm"
                >
                  <FileText className="w-4 h-4 mr-2" />
                  Review Papers
                </Button>
                <Button 
                  variant="outline"
                  onClick={() => handleActionClick("view-reports")}
                  className="text-sm"
                >
                  <TrendingUp className="w-4 h-4 mr-2" />
                  View Reports
                </Button>
                <Button 
                  onClick={handleGenerateReviewPacket}
                  disabled={generatingPacket || !selectedExam}
                  className="bg-orange-500 hover:bg-orange-600 text-sm"
                >
                  {generatingPacket ? (
                    <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Sparkles className="w-4 h-4 mr-2" />
                  )}
                  Generate Practice Questions
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {[1, 2, 3, 4].map(i => (
              <Card key={i} className="animate-pulse">
                <CardContent className="p-6">
                  <div className="h-32 bg-muted rounded" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <>
            {/* Summary */}
            {insights?.summary && (
              <Card className="border-l-4 border-l-primary">
                <CardContent className="p-4">
                  <p className="text-sm">{insights.summary}</p>
                </CardContent>
              </Card>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Strengths - Clickable */}
              <Card className="hover:shadow-md transition-shadow cursor-pointer" onClick={() => handleActionClick("view-reports")}>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-green-700">
                    <CheckCircle className="w-5 h-5" />
                    Strengths
                  </CardTitle>
                  <CardDescription>Areas where students excel</CardDescription>
                </CardHeader>
                <CardContent>
                  {insights?.strengths?.length === 0 ? (
                    <p className="text-muted-foreground text-sm">No data available yet</p>
                  ) : (
                    <div className="space-y-3">
                      {insights?.strengths?.map((strength, idx) => (
                        <div key={idx} className="flex items-start gap-3 p-3 bg-green-50 rounded-lg">
                          <TrendingUp className="w-4 h-4 text-green-600 mt-0.5 flex-shrink-0" />
                          <div>
                            <p className="font-medium text-sm text-green-800">{strength.topic || strength}</p>
                            {strength.percentage && (
                              <p className="text-xs text-green-600">{strength.percentage}% average</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="mt-4 flex items-center text-sm text-muted-foreground">
                    <span>Click to view detailed reports</span>
                    <ArrowRight className="w-4 h-4 ml-1" />
                  </div>
                </CardContent>
              </Card>

              {/* Weaknesses - Clickable with Action */}
              <Card className="hover:shadow-md transition-shadow cursor-pointer" onClick={() => selectedExam ? handleGenerateReviewPacket() : toast.info("Select an exam to generate practice questions")}>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-red-700">
                    <AlertTriangle className="w-5 h-5" />
                    Areas for Improvement
                  </CardTitle>
                  <CardDescription>Topics that need more attention</CardDescription>
                </CardHeader>
                <CardContent>
                  {insights?.weaknesses?.length === 0 ? (
                    <p className="text-muted-foreground text-sm">No weaknesses identified</p>
                  ) : (
                    <div className="space-y-3">
                      {insights?.weaknesses?.map((weakness, idx) => (
                        <div key={idx} className="flex items-start gap-3 p-3 bg-red-50 rounded-lg">
                          <TrendingDown className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" />
                          <div>
                            <p className="font-medium text-sm text-red-800">{weakness.topic || weakness}</p>
                            {weakness.percentage && (
                              <p className="text-xs text-red-600">{weakness.percentage}% average</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="mt-4 flex items-center text-sm text-orange-600 font-medium">
                    <Sparkles className="w-4 h-4 mr-1" />
                    <span>Click to generate practice questions</span>
                  </div>
                </CardContent>
              </Card>

              {/* Recommendations - Actionable */}
              <Card className="md:col-span-2">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2">
                    <Lightbulb className="w-5 h-5 text-amber-500" />
                    AI Recommendations
                  </CardTitle>
                  <CardDescription>Suggested actions to improve class performance</CardDescription>
                </CardHeader>
                <CardContent>
                  {insights?.recommendations?.length === 0 ? (
                    <p className="text-muted-foreground text-sm">No recommendations available</p>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {insights?.recommendations?.map((rec, idx) => {
                        const isActionable = typeof rec === 'object' && rec.action;
                        const recText = typeof rec === 'string' ? rec : rec.text || rec.description || JSON.stringify(rec);
                        
                        return (
                          <div 
                            key={idx} 
                            className={`p-4 rounded-lg border ${isActionable ? 'cursor-pointer hover:shadow-md transition-shadow' : ''} ${
                              idx % 3 === 0 ? 'bg-blue-50 border-blue-200' :
                              idx % 3 === 1 ? 'bg-purple-50 border-purple-200' :
                              'bg-amber-50 border-amber-200'
                            }`}
                            onClick={() => isActionable && handleActionClick(rec.action)}
                          >
                            <div className="flex items-start gap-3">
                              <Target className={`w-5 h-5 mt-0.5 flex-shrink-0 ${
                                idx % 3 === 0 ? 'text-blue-600' :
                                idx % 3 === 1 ? 'text-purple-600' :
                                'text-amber-600'
                              }`} />
                              <div>
                                <p className="text-sm font-medium">{recText}</p>
                                {isActionable && (
                                  <p className="text-xs text-muted-foreground mt-1 flex items-center">
                                    Click to take action <ArrowRight className="w-3 h-3 ml-1" />
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Weak Topics Quick View */}
              {insights?.weak_topics?.length > 0 && (
                <Card className="md:col-span-2">
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center gap-2">
                      <Brain className="w-5 h-5 text-purple-600" />
                      Topic Performance Overview
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                      {insights.weak_topics.map((topic, idx) => (
                        <div 
                          key={idx}
                          className={`p-3 rounded-lg border text-center cursor-pointer hover:scale-105 transition-transform ${getScoreBg(topic.avg_percentage || 50)}`}
                          onClick={() => {
                            toast.info(`${topic.topic || topic}: Focus on this area`);
                          }}
                        >
                          <p className="text-xs font-medium truncate" title={topic.topic || topic}>
                            {topic.topic || topic}
                          </p>
                          {topic.avg_percentage && (
                            <p className={`text-lg font-bold ${getScoreColor(topic.avg_percentage)}`}>
                              {topic.avg_percentage}%
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </>
        )}
      </div>

      {/* Review Packet Dialog */}
      <Dialog open={actionDialogOpen && selectedAction === "review-packet"} onOpenChange={setActionDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-primary" />
              AI-Generated Practice Questions
            </DialogTitle>
          </DialogHeader>
          
          {reviewPacket && (
            <ScrollArea className="max-h-[60vh] pr-4">
              <div className="space-y-4">
                <div className="p-3 bg-orange-50 border border-orange-200 rounded-lg">
                  <p className="text-sm text-orange-800">
                    <strong>{reviewPacket.weak_areas_identified || 0}</strong> weak areas identified. 
                    These questions target concepts students struggled with.
                  </p>
                </div>
                
                {reviewPacket.practice_questions?.map((q, idx) => (
                  <div key={idx} className="p-4 border rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-semibold">Question {q.question_number || idx + 1}</span>
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
                
                <Button className="w-full" onClick={downloadReviewPacket}>
                  <Download className="w-4 h-4 mr-2" />
                  Download Practice Questions
                </Button>
              </div>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
