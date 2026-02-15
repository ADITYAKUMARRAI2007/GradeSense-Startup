import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Settings, Trash2, Archive, LockOpen, Save } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { toast } from 'sonner';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const BatchSettings = () => {
  const { batchId } = useParams();
  const navigate = useNavigate();
  
  const [batch, setBatch] = useState(null);
  const [batchName, setBatchName] = useState('');
  const [subject, setSubject] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchBatch();
  }, [batchId]);

  const fetchBatch = async () => {
    try {
      const response = await axios.get(`${API}/batches/${batchId}`, { withCredentials: true });
      setBatch(response.data);
      setBatchName(response.data.name);
      setSubject(response.data.subject || '');
    } catch (error) {
      console.error('Error fetching batch:', error);
      toast.error('Failed to load class details');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    
    if (!batchName.trim()) {
      toast.error('Class name is required');
      return;
    }

    setSaving(true);
    try {
      await axios.put(`${API}/batches/${batchId}`, {
        name: batchName,
        subject: subject || undefined
      }, { withCredentials: true });
      
      toast.success('Class updated successfully!');
      navigate(`/teacher/batch/${batchId}`);
    } catch (error) {
      console.error('Error updating batch:', error);
      toast.error(error.response?.data?.detail || 'Failed to update class');
    } finally {
      setSaving(false);
    }
  };

  const handleArchive = async () => {
    if (!confirm(`Archive "${batch.name}"?\n\nThis will:\n- Prevent adding new exams\n- Prevent adding/removing students\n- Keep all data accessible\n- You can reopen it later`)) {
      return;
    }

    try {
      await axios.put(`${API}/batches/${batchId}/close`, {}, { withCredentials: true });
      toast.success('Class archived successfully');
      navigate('/teacher/dashboard');
    } catch (error) {
      console.error('Error archiving batch:', error);
      toast.error(error.response?.data?.detail || 'Failed to archive class');
    }
  };

  const handleReopen = async () => {
    if (!confirm(`Reopen "${batch.name}"?`)) {
      return;
    }

    try {
      await axios.put(`${API}/batches/${batchId}/reopen`, {}, { withCredentials: true });
      toast.success('Class reopened successfully');
      fetchBatch();
    } catch (error) {
      console.error('Error reopening batch:', error);
      toast.error(error.response?.data?.detail || 'Failed to reopen class');
    }
  };

  const handleDelete = async () => {
    if (batch.student_count > 0) {
      toast.error(`Cannot delete class with ${batch.student_count} students. Remove students first.`);
      return;
    }

    if (!confirm(`Delete "${batch.name}"?\n\nThis action cannot be undone. All data will be permanently deleted.`)) {
      return;
    }

    try {
      await axios.delete(`${API}/batches/${batchId}`, { withCredentials: true });
      toast.success('Class deleted successfully');
      navigate('/teacher/dashboard');
    } catch (error) {
      console.error('Error deleting batch:', error);
      toast.error(error.response?.data?.detail || 'Failed to delete class');
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
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <button
          onClick={() => navigate(`/teacher/batch/${batchId}`)}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Class
        </button>

        {/* Basic Settings */}
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-2xl">
              <Settings className="w-6 h-6 text-primary" />
              Class Settings
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSave} className="space-y-6">
              {/* Status Badge */}
              {batch?.status === 'closed' && (
                <div className="bg-gray-100 border border-gray-300 rounded-lg p-4">
                  <p className="text-sm font-semibold text-gray-700">
                    ⚠️ This class is currently archived. Reopen it to make changes.
                  </p>
                </div>
              )}

              {/* Batch Name */}
              <div>
                <Label htmlFor="batch-name" className="text-base font-semibold">
                  Class Name *
                </Label>
                <Input
                  id="batch-name"
                  value={batchName}
                  onChange={(e) => setBatchName(e.target.value)}
                  placeholder="e.g., Grade 10-A"
                  className="mt-2"
                  disabled={batch?.status === 'closed'}
                  required
                />
              </div>

              {/* Subject */}
              <div>
                <Label htmlFor="subject" className="text-base font-semibold">
                  Subject <span className="text-gray-400">(Optional)</span>
                </Label>
                <Input
                  id="subject"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="e.g., Mathematics"
                  className="mt-2"
                  disabled={batch?.status === 'closed'}
                />
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-4 pt-4 border-t">
                <div className="bg-blue-50 p-4 rounded-lg">
                  <p className="text-sm text-blue-600 mb-1">Students</p>
                  <p className="text-2xl font-bold text-blue-700">{batch?.student_count || 0}</p>
                </div>
                <div className="bg-green-50 p-4 rounded-lg">
                  <p className="text-sm text-green-600 mb-1">Exams</p>
                  <p className="text-2xl font-bold text-green-700">{batch?.exams?.length || 0}</p>
                </div>
              </div>

              {/* Save Button */}
              {batch?.status !== 'closed' && (
                <Button
                  type="submit"
                  disabled={saving || !batchName.trim()}
                  className="w-full"
                >
                  <Save className="w-4 h-4 mr-2" />
                  {saving ? 'Saving...' : 'Save Changes'}
                </Button>
              )}
            </form>
          </CardContent>
        </Card>

        {/* Danger Zone */}
        <Card className="border-red-200">
          <CardHeader>
            <CardTitle className="text-xl text-red-600">Danger Zone</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Archive/Reopen */}
            {batch?.status === 'closed' ? (
              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
                <div>
                  <p className="font-semibold text-gray-900">Reopen Class</p>
                  <p className="text-sm text-gray-600">Allow adding students and exams again</p>
                </div>
                <Button
                  onClick={handleReopen}
                  variant="outline"
                  className="text-green-600 hover:text-green-700 border-green-300"
                >
                  <LockOpen className="w-4 h-4 mr-2" />
                  Reopen
                </Button>
              </div>
            ) : (
              <div className="flex items-center justify-between p-4 bg-orange-50 rounded-lg">
                <div>
                  <p className="font-semibold text-orange-900">Archive Class</p>
                  <p className="text-sm text-orange-700">Prevent new exams/students, keep data</p>
                </div>
                <Button
                  onClick={handleArchive}
                  variant="outline"
                  className="text-orange-600 hover:text-orange-700 border-orange-300"
                >
                  <Archive className="w-4 h-4 mr-2" />
                  Archive
                </Button>
              </div>
            )}

            {/* Delete */}
            <div className="flex items-center justify-between p-4 bg-red-50 rounded-lg">
              <div>
                <p className="font-semibold text-red-900">Delete Class</p>
                <p className="text-sm text-red-700">Permanently delete this class and all data</p>
                {batch?.student_count > 0 && (
                  <p className="text-xs text-red-600 mt-1">⚠️ Remove all students first</p>
                )}
              </div>
              <Button
                onClick={handleDelete}
                variant="outline"
                disabled={batch?.student_count > 0}
                className="text-red-600 hover:text-red-700 border-red-300 disabled:opacity-50"
              >
                <Trash2 className="w-4 h-4 mr-2" />
                Delete
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default BatchSettings;
