import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Bug, Lightbulb, HelpCircle, CheckCircle, Clock, Filter, Search, ExternalLink } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Badge } from '../../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../../components/ui/dialog';
import { toast } from 'sonner';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const AdminFeedback = () => {
  const navigate = useNavigate();
  const [feedbacks, setFeedbacks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedFeedback, setSelectedFeedback] = useState(null);
  const [filterType, setFilterType] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    fetchFeedbacks();
  }, []);

  const fetchFeedbacks = async () => {
    try {
      const response = await axios.get(`${API}/admin/feedback`, { withCredentials: true });
      setFeedbacks(response.data);
    } catch (error) {
      console.error('Error fetching feedback:', error);
      toast.error('Failed to load feedback');
    } finally {
      setLoading(false);
    }
  };

  const handleMarkResolved = async (feedbackId) => {
    try {
      await axios.put(`${API}/admin/feedback/${feedbackId}/resolve`, {}, { withCredentials: true });
      toast.success('Marked as resolved');
      fetchFeedbacks();
      setSelectedFeedback(null);
    } catch (error) {
      console.error('Error updating feedback:', error);
      toast.error('Failed to update feedback');
    }
  };

  const getTypeIcon = (type) => {
    switch(type) {
      case 'bug': return <Bug className="w-4 h-4 text-red-600" />;
      case 'suggestion': return <Lightbulb className="w-4 h-4 text-purple-600" />;
      case 'question': return <HelpCircle className="w-4 h-4 text-blue-600" />;
      default: return null;
    }
  };

  const getTypeColor = (type) => {
    switch(type) {
      case 'bug': return 'bg-red-100 text-red-700 border-red-200';
      case 'suggestion': return 'bg-purple-100 text-purple-700 border-purple-200';
      case 'question': return 'bg-blue-100 text-blue-700 border-blue-200';
      default: return 'bg-gray-100 text-gray-700';
    }
  };

  const filteredFeedbacks = feedbacks.filter(f => {
    // Type filter
    if (filterType !== 'all' && f.type !== filterType) return false;
    
    // Status filter
    if (filterStatus !== 'all') {
      const isResolved = f.status === 'resolved';
      if (filterStatus === 'resolved' && !isResolved) return false;
      if (filterStatus === 'pending' && isResolved) return false;
    }
    
    // Search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      const title = f.data?.title?.toLowerCase() || f.data?.subject?.toLowerCase() || '';
      const desc = f.data?.description?.toLowerCase() || f.data?.question?.toLowerCase() || '';
      const userName = f.user?.name?.toLowerCase() || '';
      if (!title.includes(query) && !desc.includes(query) && !userName.includes(query)) return false;
    }
    
    return true;
  });

  const stats = {
    total: feedbacks.length,
    bugs: feedbacks.filter(f => f.type === 'bug').length,
    suggestions: feedbacks.filter(f => f.type === 'suggestion').length,
    questions: feedbacks.filter(f => f.type === 'question').length,
    pending: feedbacks.filter(f => f.status !== 'resolved').length,
    resolved: feedbacks.filter(f => f.status === 'resolved').length
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
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <button
          onClick={() => navigate('/teacher/dashboard')}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </button>

        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Feedback Management</h1>
          <p className="text-gray-500">View and manage user feedback, bug reports, and questions</p>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          <Card>
            <CardContent className="p-4">
              <p className="text-sm text-gray-600 mb-1">Total</p>
              <p className="text-2xl font-bold text-gray-900">{stats.total}</p>
            </CardContent>
          </Card>
          <Card className="border-red-200">
            <CardContent className="p-4">
              <p className="text-sm text-red-600 mb-1">Bugs</p>
              <p className="text-2xl font-bold text-red-700">{stats.bugs}</p>
            </CardContent>
          </Card>
          <Card className="border-purple-200">
            <CardContent className="p-4">
              <p className="text-sm text-purple-600 mb-1">Ideas</p>
              <p className="text-2xl font-bold text-purple-700">{stats.suggestions}</p>
            </CardContent>
          </Card>
          <Card className="border-blue-200">
            <CardContent className="p-4">
              <p className="text-sm text-blue-600 mb-1">Questions</p>
              <p className="text-2xl font-bold text-blue-700">{stats.questions}</p>
            </CardContent>
          </Card>
          <Card className="border-orange-200">
            <CardContent className="p-4">
              <p className="text-sm text-orange-600 mb-1">Pending</p>
              <p className="text-2xl font-bold text-orange-700">{stats.pending}</p>
            </CardContent>
          </Card>
          <Card className="border-green-200">
            <CardContent className="p-4">
              <p className="text-sm text-green-600 mb-1">Resolved</p>
              <p className="text-2xl font-bold text-green-700">{stats.resolved}</p>
            </CardContent>
          </Card>
        </div>

        {/* Filters */}
        <Card className="mb-6">
          <CardContent className="p-4">
            <div className="flex flex-col md:flex-row gap-4">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <Input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search feedback..."
                  className="pl-10"
                />
              </div>
              <Select value={filterType} onValueChange={setFilterType}>
                <SelectTrigger className="w-full md:w-[180px]">
                  <SelectValue placeholder="Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="bug">Bugs</SelectItem>
                  <SelectItem value="suggestion">Suggestions</SelectItem>
                  <SelectItem value="question">Questions</SelectItem>
                </SelectContent>
              </Select>
              <Select value={filterStatus} onValueChange={setFilterStatus}>
                <SelectTrigger className="w-full md:w-[180px]">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="resolved">Resolved</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Feedback List */}
        <div className="space-y-4">
          {filteredFeedbacks.length === 0 ? (
            <Card>
              <CardContent className="p-12 text-center">
                <p className="text-gray-500">No feedback found</p>
              </CardContent>
            </Card>
          ) : (
            filteredFeedbacks.map((feedback) => (
              <Card
                key={feedback.feedback_id}
                className="hover:shadow-md transition-shadow cursor-pointer"
                onClick={() => setSelectedFeedback(feedback)}
              >
                <CardContent className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-3">
                        {getTypeIcon(feedback.type)}
                        <Badge className={getTypeColor(feedback.type)}>
                          {feedback.type.toUpperCase()}
                        </Badge>
                        {feedback.status === 'resolved' && (
                          <Badge className="bg-green-100 text-green-700">
                            <CheckCircle className="w-3 h-3 mr-1" />
                            Resolved
                          </Badge>
                        )}
                        {feedback.status !== 'resolved' && (
                          <Badge variant="outline" className="text-orange-600">
                            <Clock className="w-3 h-3 mr-1" />
                            Pending
                          </Badge>
                        )}
                      </div>
                      <h3 className="text-lg font-semibold text-gray-900 mb-2">
                        {feedback.data?.title || feedback.data?.subject}
                      </h3>
                      <p className="text-gray-600 line-clamp-2 mb-3">
                        {feedback.data?.description || feedback.data?.question}
                      </p>
                      <div className="flex items-center gap-4 text-sm text-gray-500">
                        <span>
                          👤 {feedback.user?.name} ({feedback.user?.role})
                        </span>
                        <span>•</span>
                        <span>
                          📅 {new Date(feedback.created_at).toLocaleString()}
                        </span>
                        {feedback.metadata?.page && (
                          <>
                            <span>•</span>
                            <span>📍 {feedback.metadata.page}</span>
                          </>
                        )}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedFeedback(feedback);
                      }}
                    >
                      View Details
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>

      {/* Feedback Detail Dialog */}
      {selectedFeedback && (
        <Dialog open={!!selectedFeedback} onOpenChange={() => setSelectedFeedback(null)}>
          <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <div className="flex items-center gap-3">
                {getTypeIcon(selectedFeedback.type)}
                <DialogTitle className="text-2xl">
                  {selectedFeedback.data?.title || selectedFeedback.data?.subject}
                </DialogTitle>
              </div>
            </DialogHeader>

            <div className="space-y-6 mt-4">
              {/* Status and Meta */}
              <div className="flex items-center gap-2">
                <Badge className={getTypeColor(selectedFeedback.type)}>
                  {selectedFeedback.type.toUpperCase()}
                </Badge>
                {selectedFeedback.status === 'resolved' ? (
                  <Badge className="bg-green-100 text-green-700">
                    <CheckCircle className="w-3 h-3 mr-1" />
                    Resolved
                  </Badge>
                ) : (
                  <Badge variant="outline" className="text-orange-600">
                    <Clock className="w-3 h-3 mr-1" />
                    Pending
                  </Badge>
                )}
              </div>

              {/* User Info */}
              <Card className="bg-gray-50">
                <CardContent className="p-4">
                  <h4 className="font-semibold text-gray-900 mb-2">Submitted By</h4>
                  <div className="space-y-1 text-sm">
                    <p><strong>Name:</strong> {selectedFeedback.user?.name}</p>
                    <p><strong>Email:</strong> {selectedFeedback.user?.email}</p>
                    <p><strong>Role:</strong> {selectedFeedback.user?.role}</p>
                    <p><strong>Date:</strong> {new Date(selectedFeedback.created_at).toLocaleString()}</p>
                  </div>
                </CardContent>
              </Card>

              {/* Content */}
              <div>
                <h4 className="font-semibold text-gray-900 mb-2">Description</h4>
                <p className="text-gray-700 whitespace-pre-wrap">
                  {selectedFeedback.data?.description || selectedFeedback.data?.question}
                </p>
              </div>

              {selectedFeedback.data?.steps && (
                <div>
                  <h4 className="font-semibold text-gray-900 mb-2">Steps to Reproduce</h4>
                  <p className="text-gray-700 whitespace-pre-wrap">{selectedFeedback.data.steps}</p>
                </div>
              )}

              {/* Metadata */}
              <Card className="bg-blue-50">
                <CardContent className="p-4">
                  <h4 className="font-semibold text-blue-900 mb-2">Technical Details</h4>
                  <div className="space-y-1 text-sm text-blue-800">
                    <p><strong>Page:</strong> {selectedFeedback.metadata?.page || 'N/A'}</p>
                    <p className="flex items-center gap-2">
                      <strong>URL:</strong> 
                      <a href={selectedFeedback.metadata?.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline flex items-center gap-1">
                        {selectedFeedback.metadata?.url}
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    </p>
                    {selectedFeedback.metadata?.browser && (
                      <>
                        <p><strong>Browser:</strong> {selectedFeedback.metadata.browser.userAgent}</p>
                        <p><strong>Screen:</strong> {selectedFeedback.metadata.browser.screenResolution} | Viewport: {selectedFeedback.metadata.browser.viewport}</p>
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Actions */}
              <div className="flex gap-3 pt-4 border-t">
                {selectedFeedback.status !== 'resolved' && (
                  <Button
                    onClick={() => handleMarkResolved(selectedFeedback.feedback_id)}
                    className="flex-1"
                  >
                    <CheckCircle className="w-4 h-4 mr-2" />
                    Mark as Resolved
                  </Button>
                )}
                <Button
                  variant="outline"
                  onClick={() => setSelectedFeedback(null)}
                  className="flex-1"
                >
                  Close
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
};

export default AdminFeedback;
