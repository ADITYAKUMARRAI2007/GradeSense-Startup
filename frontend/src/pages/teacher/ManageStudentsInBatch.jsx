import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, UserPlus, UserMinus, Mail, Search } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../../components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { Badge } from '../../components/ui/badge';
import { toast } from 'sonner';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const ManageStudentsInBatch = () => {
  const { batchId } = useParams();
  const navigate = useNavigate();
  
  const [batch, setBatch] = useState(null);
  const [students, setStudents] = useState([]);
  const [availableStudents, setAvailableStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  
  // Add student dialog
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [addMode, setAddMode] = useState('existing'); // 'existing' or 'new'
  const [selectedStudentId, setSelectedStudentId] = useState('');
  const [newStudentForm, setNewStudentForm] = useState({ name: '', email: '', student_id: '' });
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    fetchData();
  }, [batchId]);

  const fetchData = async () => {
    try {
      // Fetch batch details
      const batchRes = await axios.get(`${API}/batches/${batchId}`, { withCredentials: true });
      setBatch(batchRes.data);

      // Fetch students in this batch
      const studentsRes = await axios.get(`${API}/batches/${batchId}/students`, { withCredentials: true });
      setStudents(studentsRes.data);
    } catch (error) {
      console.error('Error fetching data:', error);
      toast.error('Failed to load student data');
    } finally {
      setLoading(false);
    }
  };

  const fetchAvailableStudents = async () => {
    try {
      const response = await axios.get(`${API}/students`, { withCredentials: true });
      // Filter out students already in the batch
      const batchStudentIds = students.map(s => s.student_id);
      const available = response.data.filter(s => !batchStudentIds.includes(s.user_id));
      setAvailableStudents(available);
    } catch (error) {
      console.error('Error fetching available students:', error);
    }
  };

  const openAddDialog = () => {
    setAddMode('existing');
    setSelectedStudentId('');
    setNewStudentForm({ name: '', email: '', student_id: '' });
    fetchAvailableStudents();
    setAddDialogOpen(true);
  };

  const handleAddExisting = async () => {
    if (!selectedStudentId) {
      toast.error('Please select a student');
      return;
    }

    setAdding(true);
    try {
      await axios.post(`${API}/batches/${batchId}/students`, {
        student_id: selectedStudentId
      }, { withCredentials: true });
      
      toast.success('Student added successfully');
      setAddDialogOpen(false);
      fetchData();
    } catch (error) {
      console.error('Error adding student:', error);
      toast.error(error.response?.data?.detail || 'Failed to add student');
    } finally {
      setAdding(false);
    }
  };

  const handleAddNew = async () => {
    if (!newStudentForm.name.trim() || !newStudentForm.email.trim()) {
      toast.error('Name and email are required');
      return;
    }

    setAdding(true);
    try {
      await axios.post(`${API}/students`, {
        name: newStudentForm.name,
        email: newStudentForm.email,
        student_id: newStudentForm.student_id || undefined,
        batch_id: batchId
      }, { withCredentials: true });
      
      toast.success('Student created and added successfully');
      setAddDialogOpen(false);
      fetchData();
    } catch (error) {
      console.error('Error creating student:', error);
      toast.error(error.response?.data?.detail || 'Failed to create student');
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (student) => {
    if (!confirm(`Remove "${student.name}" from this class?`)) {
      return;
    }

    try {
      await axios.delete(`${API}/batches/${batchId}/students/${student.student_id}`, { withCredentials: true });
      toast.success('Student removed successfully');
      fetchData();
    } catch (error) {
      console.error('Error removing student:', error);
      toast.error(error.response?.data?.detail || 'Failed to remove student');
    }
  };

  const filteredStudents = students.filter(s =>
    s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.roll_number?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <button
          onClick={() => navigate(`/teacher/batch/${batchId}`)}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Class
        </button>

        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">{batch?.name}</h1>
            <p className="text-gray-500 mt-1">Manage Students</p>
          </div>
          <Button onClick={openAddDialog}>
            <UserPlus className="w-4 h-4 mr-2" />
            Add Student
          </Button>
        </div>

        {/* Search */}
        <Card className="mb-6">
          <CardContent className="p-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search students by name, email, or roll number..."
                className="pl-10"
              />
            </div>
          </CardContent>
        </Card>

        {/* Students List */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Students ({students.length})</span>
              {batch?.status === 'closed' && (
                <Badge variant="outline" className="bg-gray-100">Archived</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {filteredStudents.length === 0 ? (
              <div className="text-center py-12">
                <UserPlus className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-gray-600 mb-2">
                  {students.length === 0 ? 'No Students Yet' : 'No matching students'}
                </h3>
                <p className="text-gray-500 mb-6">
                  {students.length === 0 ? 'Add students to start tracking their performance' : 'Try a different search term'}
                </p>
                {students.length === 0 && batch?.status !== 'closed' && (
                  <Button onClick={openAddDialog}>
                    <UserPlus className="w-4 h-4 mr-2" />
                    Add First Student
                  </Button>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                {filteredStudents.map((student) => (
                  <div
                    key={student.student_id}
                    className="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
                  >
                    <div className="flex items-center gap-4 flex-1">
                      <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                        <span className="text-lg font-semibold text-primary">
                          {student.name?.charAt(0).toUpperCase()}
                        </span>
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-gray-900">{student.name}</p>
                          {student.roll_number && (
                            <Badge variant="outline" className="text-xs">
                              {student.roll_number}
                            </Badge>
                          )}
                        </div>
                        <p className="text-sm text-gray-500">{student.email}</p>
                      </div>
                      {student.average !== undefined && (
                        <div className="text-right">
                          <p className={`text-lg font-bold ${
                            student.average >= 75 ? 'text-green-600' :
                            student.average >= 40 ? 'text-yellow-600' :
                            'text-red-600'
                          }`}>
                            {student.average}%
                          </p>
                          <p className="text-xs text-gray-500">Average</p>
                        </div>
                      )}
                    </div>
                    <div className="flex gap-2 ml-4">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => window.location.href = `mailto:${student.email}`}
                      >
                        <Mail className="w-4 h-4" />
                      </Button>
                      {batch?.status !== 'closed' && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleRemove(student)}
                          className="text-red-600 hover:text-red-700"
                        >
                          <UserMinus className="w-4 h-4" />
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Add Student Dialog */}
      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <UserPlus className="w-5 h-5 text-green-600" />
              Add Student to {batch?.name}
            </DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4">
            {/* Mode Selection */}
            <div className="flex gap-2">
              <Button
                variant={addMode === 'existing' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAddMode('existing')}
                className="flex-1"
              >
                Existing Student
              </Button>
              <Button
                variant={addMode === 'new' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAddMode('new')}
                className="flex-1"
              >
                New Student
              </Button>
            </div>

            {addMode === 'existing' ? (
              <div className="space-y-3">
                <Label>Select Student</Label>
                {availableStudents.length > 0 ? (
                  <Select value={selectedStudentId} onValueChange={setSelectedStudentId}>
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a student..." />
                    </SelectTrigger>
                    <SelectContent>
                      {availableStudents.map(student => (
                        <SelectItem key={student.user_id} value={student.user_id}>
                          {student.name} ({student.email})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <p className="text-sm text-gray-500 text-center py-4">
                    No available students. All students are already in this class.
                  </p>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <Label htmlFor="new-name">Name *</Label>
                  <Input
                    id="new-name"
                    value={newStudentForm.name}
                    onChange={(e) => setNewStudentForm({...newStudentForm, name: e.target.value})}
                    placeholder="Student name"
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label htmlFor="new-email">Email *</Label>
                  <Input
                    id="new-email"
                    type="email"
                    value={newStudentForm.email}
                    onChange={(e) => setNewStudentForm({...newStudentForm, email: e.target.value})}
                    placeholder="student@example.com"
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label htmlFor="new-id">Roll Number (Optional)</Label>
                  <Input
                    id="new-id"
                    value={newStudentForm.student_id}
                    onChange={(e) => setNewStudentForm({...newStudentForm, student_id: e.target.value})}
                    placeholder="e.g., STU001"
                    className="mt-1"
                  />
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              Cancel
            </Button>
            {addMode === 'existing' ? (
              <Button 
                onClick={handleAddExisting}
                disabled={!selectedStudentId || adding}
              >
                {adding ? 'Adding...' : 'Add Student'}
              </Button>
            ) : (
              <Button 
                onClick={handleAddNew}
                disabled={!newStudentForm.name.trim() || !newStudentForm.email.trim() || adding}
              >
                {adding ? 'Creating...' : 'Create & Add'}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ManageStudentsInBatch;
