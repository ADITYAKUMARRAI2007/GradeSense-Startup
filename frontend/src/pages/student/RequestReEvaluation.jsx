import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Checkbox } from "../../components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { toast } from "sonner";
import { 
  MessageSquare, 
  Send,
  Clock,
  CheckCircle,
  AlertCircle
} from "lucide-react";

export default function StudentReEvaluation({ user }) {
  const [submissions, setSubmissions] = useState([]);
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSubmission, setSelectedSubmission] = useState("");
  const [selectedSubmissionData, setSelectedSubmissionData] = useState(null);
  const [selectedQuestions, setSelectedQuestions] = useState([]);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [submissionsRes, requestsRes] = await Promise.all([
        axios.get(`${API}/submissions`),
        axios.get(`${API}/re-evaluations`)
      ]);
      setSubmissions(submissionsRes.data);
      setRequests(requestsRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmissionSelect = async (submissionId) => {
    setSelectedSubmission(submissionId);
    setSelectedQuestions([]);
    
    if (submissionId) {
      try {
        const response = await axios.get(`${API}/submissions/${submissionId}`);
        setSelectedSubmissionData(response.data);
      } catch (error) {
        console.error("Error fetching submission:", error);
      }
    } else {
      setSelectedSubmissionData(null);
    }
  };

  const handleSubmit = async () => {
    if (!selectedSubmission || selectedQuestions.length === 0 || !reason.trim()) {
      toast.error("Please fill all required fields");
      return;
    }

    setSubmitting(true);
    try {
      await axios.post(`${API}/re-evaluations`, {
        submission_id: selectedSubmission,
        questions: selectedQuestions,
        reason: reason.trim()
      });
      toast.success("Re-evaluation request submitted");
      setSelectedSubmission("");
      setSelectedSubmissionData(null);
      setSelectedQuestions([]);
      setReason("");
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to submit request");
    } finally {
      setSubmitting(false);
    }
  };

  const getStatusBadge = (status) => {
    const styles = {
      pending: { className: "bg-yellow-100 text-yellow-700", icon: Clock },
      in_review: { className: "bg-blue-100 text-blue-700", icon: AlertCircle },
      resolved: { className: "bg-green-100 text-green-700", icon: CheckCircle }
    };
    const config = styles[status] || styles.pending;
    const Icon = config.icon;
    
    return (
      <Badge className={config.className}>
        <Icon className="w-3 h-3 mr-1" />
        {status === "pending" ? "Pending" : status === "in_review" ? "In Review" : "Resolved"}
      </Badge>
    );
  };

  return (
    <Layout user={user}>
      <div className="space-y-6" data-testid="student-reeval-page">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Request Re-evaluation</h1>
          <p className="text-muted-foreground">Dispute your grades and request a review</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* New Request Form */}
          <Card className="animate-fade-in">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MessageSquare className="w-5 h-5 text-primary" />
                New Request
              </CardTitle>
              <CardDescription>
                Select an exam and the questions you want to dispute
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Select Exam *</Label>
                <Select value={selectedSubmission} onValueChange={handleSubmissionSelect}>
                  <SelectTrigger data-testid="exam-select">
                    <SelectValue placeholder="Choose an exam" />
                  </SelectTrigger>
                  <SelectContent>
                    {submissions.map(sub => (
                      <SelectItem key={sub.submission_id} value={sub.submission_id}>
                        {sub.exam_name || "Exam"} - {sub.percentage}%
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {selectedSubmissionData && (
                <div className="space-y-2">
                  <Label>Select Questions to Dispute *</Label>
                  <div className="grid grid-cols-2 gap-2 p-3 border rounded-lg">
                    {selectedSubmissionData.question_scores?.map((qs) => (
                      <div 
                        key={qs.question_number}
                        className="flex items-center gap-2 p-2 rounded hover:bg-muted transition-colors"
                      >
                        <Checkbox 
                          id={`q-${qs.question_number}`}
                          checked={selectedQuestions.includes(qs.question_number)}
                          onCheckedChange={(checked) => {
                            if (checked) {
                              setSelectedQuestions(prev => [...prev, qs.question_number]);
                            } else {
                              setSelectedQuestions(prev => prev.filter(q => q !== qs.question_number));
                            }
                          }}
                        />
                        <Label 
                          htmlFor={`q-${qs.question_number}`}
                          className="cursor-pointer flex-1"
                        >
                          Q{qs.question_number} ({qs.obtained_marks}/{qs.max_marks})
                        </Label>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <Label>Reason for Re-evaluation *</Label>
                <Textarea 
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Explain why you believe these questions need re-evaluation..."
                  rows={4}
                  data-testid="reason-textarea"
                />
                <p className="text-xs text-muted-foreground">
                  Be specific about which parts you think were graded incorrectly
                </p>
              </div>

              <Button 
                onClick={handleSubmit}
                disabled={!selectedSubmission || selectedQuestions.length === 0 || !reason.trim() || submitting}
                className="w-full"
                data-testid="submit-request-btn"
              >
                <Send className="w-4 h-4 mr-2" />
                {submitting ? "Submitting..." : "Submit Request"}
              </Button>
            </CardContent>
          </Card>

          {/* Request History */}
          <Card className="animate-fade-in stagger-1">
            <CardHeader>
              <CardTitle>My Requests</CardTitle>
              <CardDescription>Track the status of your re-evaluation requests</CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3">
                  {[1, 2, 3].map(i => (
                    <div key={i} className="h-20 bg-muted animate-pulse rounded-lg" />
                  ))}
                </div>
              ) : requests.length === 0 ? (
                <div className="text-center py-8">
                  <MessageSquare className="w-12 h-12 mx-auto text-muted-foreground/50 mb-3" />
                  <p className="text-muted-foreground">No requests submitted yet</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {requests.map((request) => (
                    <div 
                      key={request.request_id}
                      className="p-4 border rounded-lg"
                      data-testid={`my-request-${request.request_id}`}
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <p className="font-medium">Questions: {request.questions.map(q => `Q${q}`).join(", ")}</p>
                          <p className="text-xs text-muted-foreground flex items-center gap-1 mt-1">
                            <Clock className="w-3 h-3" />
                            {new Date(request.created_at).toLocaleDateString()}
                          </p>
                        </div>
                        {getStatusBadge(request.status)}
                      </div>
                      
                      <p className="text-sm text-muted-foreground bg-muted/50 p-2 rounded mt-2">
                        {request.reason}
                      </p>

                      {request.response && (
                        <div className="mt-3 p-3 bg-green-50 rounded-lg">
                          <p className="text-sm text-green-700">
                            <strong>Teacher Response:</strong> {request.response}
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </Layout>
  );
}
