import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, BookOpen } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { toast } from 'sonner';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const AddBatch = () => {
  const navigate = useNavigate();
  const [batchName, setBatchName] = useState('');
  const [subject, setSubject] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!batchName.trim()) {
      toast.error('Batch name is required');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(`${API}/batches`, {
        name: batchName,
        subject: subject || undefined
      }, { withCredentials: true });
      
      toast.success('Class created successfully!');
      navigate('/teacher/dashboard');
    } catch (error) {
      console.error('Error creating batch:', error);
      toast.error(error.response?.data?.detail || 'Failed to create class');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <button
          onClick={() => navigate('/teacher/dashboard')}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </button>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-2xl">
              <BookOpen className="w-6 h-6 text-primary" />
              Create New Class
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Batch Name */}
              <div>
                <Label htmlFor="batch-name" className="text-base font-semibold">
                  Class Name *
                </Label>
                <Input
                  id="batch-name"
                  value={batchName}
                  onChange={(e) => setBatchName(e.target.value)}
                  placeholder="e.g., Grade 10-A, Mathematics Advanced, Class 12 Physics"
                  className="mt-2"
                  required
                />
                <p className="text-sm text-gray-500 mt-1">
                  Choose a descriptive name for your class
                </p>
              </div>

              {/* Subject (Optional) */}
              <div>
                <Label htmlFor="subject" className="text-base font-semibold">
                  Subject <span className="text-gray-400">(Optional)</span>
                </Label>
                <Input
                  id="subject"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="e.g., Mathematics, Science, English"
                  className="mt-2"
                />
                <p className="text-sm text-gray-500 mt-1">
                  Specify the subject for better organization
                </p>
              </div>

              {/* Info Box */}
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <h4 className="font-semibold text-blue-900 mb-2">What happens next?</h4>
                <ul className="text-sm text-blue-800 space-y-1">
                  <li>✓ Your class will be created and visible on the dashboard</li>
                  <li>✓ You can add students to this class</li>
                  <li>✓ You can create exams and grade papers for this class</li>
                  <li>✓ Track performance and generate reports</li>
                </ul>
              </div>

              {/* Actions */}
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => navigate('/teacher/dashboard')}
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={loading || !batchName.trim()}
                  className="flex-1"
                >
                  {loading ? 'Creating...' : 'Create Class'}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default AddBatch;
