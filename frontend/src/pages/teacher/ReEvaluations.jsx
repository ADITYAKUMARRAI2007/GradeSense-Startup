import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Textarea } from "../../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { toast } from "sonner";
import { 
  MessageSquare, 
  Clock, 
  CheckCircle,
  XCircle,
  Eye
} from "lucide-react";

export default function ReEvaluations({ user }) {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedRequest, setSelectedRequest] = useState(null);
  const [response, setResponse] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    fetchRequests();
  }, []);

  const fetchRequests = async () => {
    try {
      const res = await axios.get(`${API}/re-evaluations`);
      setRequests(res.data);
    } catch (error) {
      console.error("Error fetching requests:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleResponse = async (status) => {
    if (!selectedRequest) return;
    
    try {
      await axios.put(`${API}/re-evaluations/${selectedRequest.request_id}`, {
        status,
        response
      });
      toast.success(`Request ${status}`);
      setDialogOpen(false);
      setSelectedRequest(null);
      setResponse("");
      fetchRequests();
    } catch (error) {
      toast.error("Failed to update request");
    }
  };

  const openReviewDialog = (request) => {
    setSelectedRequest(request);
    setResponse(request.response || "");
    setDialogOpen(true);
  };

  const getStatusBadge = (status) => {
    const styles = {
      pending: "bg-yellow-100 text-yellow-700",
      in_review: "bg-blue-100 text-blue-700",
      resolved: "bg-green-100 text-green-700"
    };
    return (
      <Badge className={styles[status] || styles.pending}>
        {status === "pending" ? "Pending" : status === "in_review" ? "In Review" : "Resolved"}
      </Badge>
    );
  };

  return (
    <Layout user={user}>
      <div className="space-y-6" data-testid="re-evaluations-page">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Re-evaluation Requests</h1>
          <p className="text-muted-foreground">Review and respond to student grade disputes</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageSquare className="w-5 h-5 text-primary" />
              Pending Requests ({requests.filter(r => r.status === "pending").length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {[1, 2, 3].map(i => (
                  <div key={i} className="h-24 bg-muted animate-pulse rounded-lg" />
                ))}
              </div>
            ) : requests.length === 0 ? (
              <div className="text-center py-12">
                <CheckCircle className="w-12 h-12 mx-auto text-green-500 mb-3" />
                <p className="text-muted-foreground">No pending re-evaluation requests</p>
              </div>
            ) : (
              <div className="space-y-4">
                {requests.map((request) => (
                  <div 
                    key={request.request_id}
                    className="p-4 border rounded-lg hover:border-primary/50 transition-colors"
                    data-testid={`request-${request.request_id}`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3 mb-2">
                          <span className="font-semibold">{request.student_name}</span>
                          {getStatusBadge(request.status)}
                        </div>
                        <p className="text-sm text-muted-foreground mb-2">
                          Questions: {request.questions.map(q => `Q${q}`).join(", ")}
                        </p>
                        <p className="text-sm bg-muted/50 p-3 rounded-lg">
                          <strong>Reason:</strong> {request.reason}
                        </p>
                        <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
                          <Clock className="w-3 h-3" />
                          {new Date(request.created_at).toLocaleDateString()}
                        </div>
                      </div>
                      
                      <Button 
                        variant="outline" 
                        size="sm"
                        onClick={() => openReviewDialog(request)}
                        data-testid={`review-btn-${request.request_id}`}
                      >
                        <Eye className="w-4 h-4 mr-2" />
                        Review
                      </Button>
                    </div>

                    {request.response && (
                      <div className="mt-3 p-3 bg-green-50 rounded-lg">
                        <p className="text-sm text-green-700">
                          <strong>Response:</strong> {request.response}
                        </p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Review Dialog */}
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>Review Re-evaluation Request</DialogTitle>
            </DialogHeader>
            
            {selectedRequest && (
              <div className="space-y-4 py-4">
                <div className="p-4 bg-muted/50 rounded-lg">
                  <p className="font-medium mb-1">{selectedRequest.student_name}</p>
                  <p className="text-sm text-muted-foreground">
                    Questions: {selectedRequest.questions.map(q => `Q${q}`).join(", ")}
                  </p>
                </div>

                <div>
                  <p className="text-sm font-medium mb-2">Student's Reason:</p>
                  <p className="text-sm bg-yellow-50 p-3 rounded-lg">{selectedRequest.reason}</p>
                </div>

                <div>
                  <p className="text-sm font-medium mb-2">Your Response:</p>
                  <Textarea 
                    value={response}
                    onChange={(e) => setResponse(e.target.value)}
                    placeholder="Explain your decision..."
                    rows={4}
                    data-testid="response-textarea"
                  />
                </div>
              </div>
            )}

            <DialogFooter className="gap-2">
              <Button 
                variant="destructive" 
                onClick={() => handleResponse("resolved")}
                data-testid="reject-btn"
              >
                <XCircle className="w-4 h-4 mr-2" />
                Reject Request
              </Button>
              <Button 
                onClick={() => handleResponse("resolved")}
                data-testid="approve-btn"
              >
                <CheckCircle className="w-4 h-4 mr-2" />
                Approve Change
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </Layout>
  );
}
