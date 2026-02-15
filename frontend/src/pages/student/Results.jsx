import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { ScrollArea } from "../../components/ui/scroll-area";
import { 
  FileText, 
  Download, 
  Eye,
  ChevronDown,
  ChevronUp,
  ZoomIn,
  ZoomOut,
  Maximize2
} from "lucide-react";

export default function StudentResults({ user }) {
  const [submissions, setSubmissions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState([]);
  const [showModelAnswer, setShowModelAnswer] = useState(false);
  const [modelAnswerImages, setModelAnswerImages] = useState([]);
  const [zoomedImage, setZoomedImage] = useState(null);
  const [imageZoom, setImageZoom] = useState(100);

  useEffect(() => {
    fetchSubmissions();
  }, []);

  const fetchSubmissions = async () => {
    try {
      const response = await axios.get(`${API}/submissions`);
      setSubmissions(response.data);
    } catch (error) {
      console.error("Error fetching submissions:", error);
    } finally {
      setLoading(false);
    }
  };

  const viewDetails = async (submissionId) => {
    try {
      const response = await axios.get(`${API}/submissions/${submissionId}`);
      setSelectedSubmission(response.data);
      setDialogOpen(true);
      
      // Note: Students no longer have access to model answers
    } catch (error) {
      console.error("Error fetching details:", error);
    }
  };

  const toggleExpand = (id) => {
    setExpandedIds(prev => 
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    );
  };

  const getGradeBadgeColor = (percentage) => {
    if (percentage >= 80) return "bg-green-100 text-green-700";
    if (percentage >= 60) return "bg-blue-100 text-blue-700";
    if (percentage >= 40) return "bg-yellow-100 text-yellow-700";
    return "bg-red-100 text-red-700";
  };

  return (
    <Layout user={user}>
      <div className="space-y-6" data-testid="student-results-page">
        <div>
          <h1 className="text-2xl font-bold text-foreground">My Results</h1>
          <p className="text-muted-foreground">View your exam results and feedback</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="w-5 h-5 text-primary" />
              Exam Results ({submissions.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {[1, 2, 3, 4].map(i => (
                  <div key={i} className="h-20 bg-muted animate-pulse rounded-lg" />
                ))}
              </div>
            ) : submissions.length === 0 ? (
              <div className="text-center py-12">
                <FileText className="w-12 h-12 mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-muted-foreground">No results available yet</p>
              </div>
            ) : (
              <div className="space-y-4">
                {submissions.map((submission) => (
                  <div 
                    key={submission.submission_id}
                    className="border rounded-lg overflow-hidden"
                    data-testid={`result-${submission.submission_id}`}
                  >
                    <div 
                      className="flex items-center justify-between p-4 cursor-pointer hover:bg-muted/50 transition-colors"
                      onClick={() => toggleExpand(submission.submission_id)}
                    >
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                          <span className="text-lg font-bold text-primary">
                            {submission.percentage}%
                          </span>
                        </div>
                        <div>
                          <p className="font-medium">{submission.exam_name || "Exam"}</p>
                          <p className="text-sm text-muted-foreground">
                            {submission.subject_name || "Subject"} • Score: {submission.total_score}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <Badge className={getGradeBadgeColor(submission.percentage)}>
                          {submission.percentage >= 80 ? "Excellent" :
                           submission.percentage >= 60 ? "Good" :
                           submission.percentage >= 40 ? "Average" : "Needs Improvement"}
                        </Badge>
                        {expandedIds.includes(submission.submission_id) ? (
                          <ChevronUp className="w-5 h-5 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="w-5 h-5 text-muted-foreground" />
                        )}
                      </div>
                    </div>

                    {expandedIds.includes(submission.submission_id) && (
                      <div className="border-t p-4 bg-muted/30">
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                          {submission.question_scores?.slice(0, 6).map((qs, idx) => (
                            <div key={idx} className="p-3 bg-white rounded-lg border">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-sm font-medium">Q{qs.question_number}</span>
                                <span className="text-sm">
                                  {qs.obtained_marks}/{qs.max_marks}
                                </span>
                              </div>
                              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                                <div 
                                  className="h-full bg-primary rounded-full transition-all"
                                  style={{ width: `${(qs.obtained_marks / qs.max_marks) * 100}%` }}
                                />
                              </div>
                            </div>
                          ))}
                        </div>
                        
                        <div className="flex justify-end mt-4">
                          <Button 
                            variant="outline" 
                            size="sm"
                            onClick={() => viewDetails(submission.submission_id)}
                          >
                            <Eye className="w-4 h-4 mr-2" />
                            View Full Details
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Detail Dialog */}
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent className="max-w-6xl max-h-[90vh] overflow-hidden flex flex-col p-0">
            <DialogHeader className="p-4 border-b">
              <DialogTitle>
                Result Details - {selectedSubmission?.exam_name || "Exam"}
              </DialogTitle>
            </DialogHeader>
            
            {selectedSubmission && (
              <div className="flex-1 overflow-hidden flex flex-col">
                {/* Summary */}
                <div className="flex items-center gap-4 p-4 bg-primary/5 border-b">
                  <div className="text-center">
                    <p className="text-3xl font-bold text-primary">
                      {selectedSubmission.percentage}%
                    </p>
                    <p className="text-xs text-muted-foreground">Overall Score</p>
                  </div>
                  <div className="flex-1 grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-sm text-muted-foreground">Total Marks</p>
                      <p className="font-medium">{selectedSubmission.total_score}</p>
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">Status</p>
                      <Badge className={
                        selectedSubmission.status === "teacher_reviewed" 
                          ? "bg-green-100 text-green-700" 
                          : "bg-yellow-100 text-yellow-700"
                      }>
                        {selectedSubmission.status === "teacher_reviewed" ? "Reviewed" : "AI Graded"}
                      </Badge>
                    </div>
                  </div>
                </div>

                {/* Two-Panel Layout: Answer Sheet | Questions */}
                <div className="flex-1 overflow-hidden flex">
                  {/* Left Panel - Answer Sheets (Student + Model) */}
                  {selectedSubmission.file_images?.length > 0 && (
                    <ScrollArea className="w-1/2 border-r bg-muted/30 p-4">
                      <div className="space-y-3">
                        {/* Toggle Controls */}
                        <div className="sticky top-0 bg-muted/30 py-2 z-10 space-y-2">
                          <div className="flex items-center justify-between">
                            <h3 className="font-semibold">Your Answer Sheet</h3>
                          </div>
                        </div>
                        
                        {/* Your Answer */}
                        <div className="space-y-2">
                          <h4 className="text-sm font-semibold text-blue-700 border-b pb-1">Your Answer</h4>
                          <div className="space-y-4">
                            {selectedSubmission.file_images.map((img, idx) => (
                              <div key={idx} className="relative group">
                                <div 
                                  className="relative cursor-zoom-in hover:shadow-xl transition-shadow"
                                  onClick={() => setZoomedImage({ src: `data:image/jpeg;base64,${img}`, title: `Your Answer - Page ${idx + 1}` })}
                                >
                                  <img 
                                    src={`data:image/jpeg;base64,${img}`}
                                    alt={`Page ${idx + 1}`}
                                    className="w-full rounded-lg shadow-md"
                                    style={{ minHeight: '500px', objectFit: 'contain' }}
                                  />
                                  {/* Zoom Overlay */}
                                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-all rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100">
                                    <div className="bg-white/90 px-3 py-2 rounded-lg flex items-center gap-2">
                                      <Maximize2 className="w-4 h-4" />
                                      <span className="text-sm font-medium">Click to enlarge</span>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                        
                        {/* Question Paper Section */}
                        {selectedSubmission.question_paper_images && selectedSubmission.question_paper_images.length > 0 && (
                          <div className="space-y-2 mt-6">
                            <h4 className="text-sm font-semibold text-green-700 border-b pb-1">Question Paper</h4>
                            <div className="space-y-4">
                              {selectedSubmission.question_paper_images.map((img, idx) => (
                                <div key={idx} className="border rounded-lg overflow-hidden shadow-sm">
                                  <img 
                                    src={`data:image/jpeg;base64,${img}`}
                                    alt={`Question page ${idx + 1}`}
                                    className="w-full cursor-pointer hover:shadow-lg transition-shadow"
                                    onClick={() => setZoomedImage({ src: `data:image/jpeg;base64,${img}`, title: `Question Paper - Page ${idx + 1}` })}
                                  />
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </ScrollArea>
                  )}

                  {/* Right Panel - Questions & Feedback */}
                  <ScrollArea className={selectedSubmission.file_images?.length > 0 ? "w-1/2 p-4" : "w-full p-4"}>
                    <div className="space-y-3">
                      <h3 className="font-semibold sticky top-0 bg-background py-2">Question-wise Breakdown</h3>
                      {selectedSubmission.question_scores?.map((qs, idx) => (
                        <div key={idx} className="p-4 border rounded-lg bg-white">
                          <div className="flex items-center justify-between mb-2">
                            <span className="font-medium">Question {qs.question_number}</span>
                            <Badge variant="outline">
                              {qs.obtained_marks} / {qs.max_marks}
                            </Badge>
                          </div>
                          
                          {/* Full Question Text */}
                          {qs.question_text && (
                            <div className="mb-3 p-3 bg-blue-50 rounded-lg border-l-4 border-blue-400">
                              <p className="text-sm text-blue-800 whitespace-pre-wrap">
                                <strong>Q{qs.question_number}.</strong> {qs.question_text}
                              </p>
                            </div>
                          )}
                          
                          <div className="h-2 bg-gray-100 rounded-full overflow-hidden mb-3">
                            <div 
                              className={`h-full rounded-full transition-all ${
                                (qs.obtained_marks / qs.max_marks) >= 0.8 ? "bg-green-500" :
                                (qs.obtained_marks / qs.max_marks) >= 0.5 ? "bg-yellow-500" : "bg-red-500"
                              }`}
                              style={{ width: `${(qs.obtained_marks / qs.max_marks) * 100}%` }}
                            />
                          </div>
                          <div className="bg-muted/50 p-3 rounded-lg">
                            <p className="text-sm text-muted-foreground mb-1">Feedback:</p>
                            <p className="text-sm">{qs.ai_feedback}</p>
                          </div>
                          {qs.teacher_comment && (
                            <div className="bg-blue-50 p-3 rounded-lg mt-2">
                              <p className="text-sm text-blue-700">
                                <strong>Teacher Note:</strong> {qs.teacher_comment}
                              </p>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                </div>
              </div>
            )}
          </DialogContent>
        </Dialog>

        {/* Image Zoom Modal */}
        <Dialog open={!!zoomedImage} onOpenChange={() => setZoomedImage(null)}>
          <DialogContent className="max-w-[95vw] max-h-[95vh] p-0">
            <DialogHeader className="p-4 border-b">
              <div className="flex items-center justify-between">
                <DialogTitle>{zoomedImage?.title || "Image Viewer"}</DialogTitle>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setImageZoom(Math.max(50, imageZoom - 25))}
                  >
                    <ZoomOut className="w-4 h-4" />
                  </Button>
                  <span className="text-sm font-medium min-w-[60px] text-center">{imageZoom}%</span>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setImageZoom(Math.min(200, imageZoom + 25))}
                  >
                    <ZoomIn className="w-4 h-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setImageZoom(100)}
                  >
                    Reset
                  </Button>
                </div>
              </div>
            </DialogHeader>
            <div className="overflow-auto p-4" style={{ maxHeight: 'calc(95vh - 80px)' }}>
              {zoomedImage && (
                <img 
                  src={zoomedImage.src}
                  alt={zoomedImage.title}
                  className="mx-auto"
                  style={{ 
                    width: `${imageZoom}%`,
                    transition: 'width 0.2s'
                  }}
                />
              )}
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </Layout>
  );
}
