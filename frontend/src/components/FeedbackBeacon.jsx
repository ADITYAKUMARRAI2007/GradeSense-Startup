import { useState } from 'react';
import { MessageSquare, X, Bug, Lightbulb, HelpCircle, Send } from 'lucide-react';
import { Button } from './ui/button';
import { Textarea } from './ui/textarea';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog';
import { toast } from 'sonner';
import axios from 'axios';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const FeedbackBeacon = ({ user }) => {
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('bug');
  const [submitting, setSubmitting] = useState(false);
  
  const [bugForm, setBugForm] = useState({ title: '', description: '', steps: '' });
  const [suggestionForm, setSuggestionForm] = useState({ title: '', description: '' });
  const [questionForm, setQuestionForm] = useState({ subject: '', question: '' });

  const getBrowserInfo = () => {
    return {
      userAgent: navigator.userAgent,
      language: navigator.language,
      platform: navigator.platform,
      screenResolution: `${window.screen.width}x${window.screen.height}`,
      viewport: `${window.innerWidth}x${window.innerHeight}`
    };
  };

  const handleSubmit = async (type) => {
    let data = {};
    
    switch(type) {
      case 'bug':
        if (!bugForm.title || !bugForm.description) {
          toast.error('Please fill in all required fields');
          return;
        }
        data = { title: bugForm.title, description: bugForm.description, steps: bugForm.steps };
        break;
      case 'suggestion':
        if (!suggestionForm.title || !suggestionForm.description) {
          toast.error('Please fill in all required fields');
          return;
        }
        data = { title: suggestionForm.title, description: suggestionForm.description };
        break;
      case 'question':
        if (!questionForm.subject || !questionForm.question) {
          toast.error('Please fill in all required fields');
          return;
        }
        data = { subject: questionForm.subject, question: questionForm.question };
        break;
    }

    setSubmitting(true);
    try {
      await axios.post(`${API}/feedback`, {
        type,
        data,
        metadata: {
          page: window.location.pathname,
          url: window.location.href,
          browser: getBrowserInfo(),
          timestamp: new Date().toISOString()
        }
      }, { withCredentials: true });
      
      toast.success('Thank you! Your feedback has been submitted.');
      
      // Reset forms
      setBugForm({ title: '', description: '', steps: '' });
      setSuggestionForm({ title: '', description: '' });
      setQuestionForm({ subject: '', question: '' });
      setOpen(false);
    } catch (error) {
      console.error('Error submitting feedback:', error);
      toast.error(error.response?.data?.detail || 'Failed to submit feedback');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      {/* Floating Beacon Button */}
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 w-14 h-14 bg-primary hover:bg-primary/90 text-white rounded-full shadow-lg hover:shadow-xl transition-all duration-200 flex items-center justify-center group z-50"
        aria-label="Open feedback"
      >
        <MessageSquare className="w-6 h-6" />
        <span className="absolute right-full mr-3 bg-gray-900 text-white text-sm px-3 py-2 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
          💬 Feedback & Help
        </span>
      </button>

      {/* Feedback Dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-2xl font-bold">We'd Love Your Feedback!</DialogTitle>
            <p className="text-sm text-gray-500 mt-1">
              Report bugs, suggest features, or ask questions. We're here to help!
            </p>
          </DialogHeader>

          <Tabs value={activeTab} onValueChange={setActiveTab} className="mt-4">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="bug" className="flex items-center gap-2">
                <Bug className="w-4 h-4" />
                <span className="hidden sm:inline">Bug Report</span>
                <span className="sm:hidden">Bug</span>
              </TabsTrigger>
              <TabsTrigger value="suggestion" className="flex items-center gap-2">
                <Lightbulb className="w-4 h-4" />
                <span className="hidden sm:inline">Suggestion</span>
                <span className="sm:hidden">Idea</span>
              </TabsTrigger>
              <TabsTrigger value="question" className="flex items-center gap-2">
                <HelpCircle className="w-4 h-4" />
                <span className="hidden sm:inline">Ask Us</span>
                <span className="sm:hidden">Help</span>
              </TabsTrigger>
            </TabsList>

            {/* Bug Report Tab */}
            <TabsContent value="bug" className="space-y-4 mt-4">
              <div>
                <Label htmlFor="bug-title">What's broken? *</Label>
                <Input
                  id="bug-title"
                  value={bugForm.title}
                  onChange={(e) => setBugForm({...bugForm, title: e.target.value})}
                  placeholder="e.g., Dashboard not loading"
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor="bug-description">Describe the issue *</Label>
                <Textarea
                  id="bug-description"
                  value={bugForm.description}
                  onChange={(e) => setBugForm({...bugForm, description: e.target.value})}
                  placeholder="What happened? What did you expect to happen?"
                  className="mt-1 min-h-[100px]"
                />
              </div>
              <div>
                <Label htmlFor="bug-steps">Steps to reproduce (optional)</Label>
                <Textarea
                  id="bug-steps"
                  value={bugForm.steps}
                  onChange={(e) => setBugForm({...bugForm, steps: e.target.value})}
                  placeholder="1. Go to...\n2. Click on...\n3. See error"
                  className="mt-1 min-h-[80px]"
                />
              </div>
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm">
                <p className="text-blue-800">
                  📍 We'll automatically capture: Current page, browser info, and your account details
                </p>
              </div>
              <Button
                onClick={() => handleSubmit('bug')}
                disabled={submitting || !bugForm.title || !bugForm.description}
                className="w-full"
              >
                <Send className="w-4 h-4 mr-2" />
                {submitting ? 'Submitting...' : 'Submit Bug Report'}
              </Button>
            </TabsContent>

            {/* Suggestion Tab */}
            <TabsContent value="suggestion" className="space-y-4 mt-4">
              <div>
                <Label htmlFor="suggestion-title">Feature idea *</Label>
                <Input
                  id="suggestion-title"
                  value={suggestionForm.title}
                  onChange={(e) => setSuggestionForm({...suggestionForm, title: e.target.value})}
                  placeholder="e.g., Bulk student import"
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor="suggestion-description">Tell us more *</Label>
                <Textarea
                  id="suggestion-description"
                  value={suggestionForm.description}
                  onChange={(e) => setSuggestionForm({...suggestionForm, description: e.target.value})}
                  placeholder="I wish GradeSense could... because it would help me..."
                  className="mt-1 min-h-[150px]"
                />
              </div>
              <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-sm">
                <p className="text-purple-800">
                  💡 Your ideas help us build a better GradeSense! We review every suggestion.
                </p>
              </div>
              <Button
                onClick={() => handleSubmit('suggestion')}
                disabled={submitting || !suggestionForm.title || !suggestionForm.description}
                className="w-full"
              >
                <Send className="w-4 h-4 mr-2" />
                {submitting ? 'Submitting...' : 'Submit Suggestion'}
              </Button>
            </TabsContent>

            {/* Question Tab */}
            <TabsContent value="question" className="space-y-4 mt-4">
              <div>
                <Label htmlFor="question-subject">Subject *</Label>
                <Input
                  id="question-subject"
                  value={questionForm.subject}
                  onChange={(e) => setQuestionForm({...questionForm, subject: e.target.value})}
                  placeholder="e.g., How do I grade sub-questions?"
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor="question-description">Your question *</Label>
                <Textarea
                  id="question-description"
                  value={questionForm.question}
                  onChange={(e) => setQuestionForm({...questionForm, question: e.target.value})}
                  placeholder="Please explain in detail..."
                  className="mt-1 min-h-[150px]"
                />
              </div>
              <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm">
                <p className="text-green-800">
                  ❓ We'll get back to you soon! Check your email for our response.
                </p>
              </div>
              <Button
                onClick={() => handleSubmit('question')}
                disabled={submitting || !questionForm.subject || !questionForm.question}
                className="w-full"
              >
                <Send className="w-4 h-4 mr-2" />
                {submitting ? 'Submitting...' : 'Send Question'}
              </Button>
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default FeedbackBeacon;
