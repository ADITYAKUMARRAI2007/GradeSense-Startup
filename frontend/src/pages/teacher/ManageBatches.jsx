import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "../../components/ui/dialog";
import { ScrollArea } from "../../components/ui/scroll-area";
import { Checkbox } from "../../components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { toast } from "sonner";
import { 
  Plus, 
  Search, 
  Edit2, 
  Trash2, 
  Users,
  BookOpen,
  FileText,
  ChevronRight,
  AlertTriangle,
  Lock,
  LockOpen,
  Archive,
  UserPlus,
  UserMinus,
  X
} from "lucide-react";

export default function ManageBatches({ user }) {
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingBatch, setEditingBatch] = useState(null);
  const [batchName, setBatchName] = useState("");
  const [selectedBatch, setSelectedBatch] = useState(null);
  const [batchDetails, setBatchDetails] = useState(null);
  const navigate = useNavigate();

  const [showClosed, setShowClosed] = useState(false);
  
  // New state for add student dialog
  const [addStudentDialogOpen, setAddStudentDialogOpen] = useState(false);
  const [availableStudents, setAvailableStudents] = useState([]);
  const [selectedStudentToAdd, setSelectedStudentToAdd] = useState("");
  const [newStudentForm, setNewStudentForm] = useState({ name: "", email: "", student_id: "" });
  const [addingStudent, setAddingStudent] = useState(false);
  const [addStudentMode, setAddStudentMode] = useState("existing"); // "existing" or "new"

  useEffect(() => {
    fetchBatches();
  }, []);

  const fetchBatches = async () => {
    try {
      const response = await axios.get(`${API}/batches`);
      setBatches(response.data);
    } catch (error) {
      console.error("Error fetching batches:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchBatchDetails = async (batchId) => {
    try {
      const response = await axios.get(`${API}/batches/${batchId}`);
      setBatchDetails(response.data);
      setSelectedBatch(batchId);
    } catch (error) {
      toast.error("Failed to load batch details");
    }
  };

  const handleSubmit = async () => {
    if (!batchName.trim()) {
      toast.error("Batch name is required");
      return;
    }

    try {
      if (editingBatch) {
        await axios.put(`${API}/batches/${editingBatch.batch_id}`, { name: batchName });
        toast.success("Batch updated");
      } else {
        await axios.post(`${API}/batches`, { name: batchName });
        toast.success("Batch created");
      }
      setDialogOpen(false);
      setEditingBatch(null);
      setBatchName("");
      fetchBatches();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to save batch");
    }
  };

  const handleDelete = async (batch) => {
    if (batch.student_count > 0) {
      toast.error(`Cannot delete batch with ${batch.student_count} students. Remove students first.`);
      return;
    }
    
    if (!confirm(`Are you sure you want to delete "${batch.name}"?`)) return;
    
    try {
      await axios.delete(`${API}/batches/${batch.batch_id}`);
      toast.success("Batch deleted");
      fetchBatches();
      if (selectedBatch === batch.batch_id) {
        setSelectedBatch(null);
        setBatchDetails(null);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to delete batch");
    }
  };

  const openEditDialog = (batch) => {
    setEditingBatch(batch);
    setBatchName(batch.name);
    setDialogOpen(true);
  };

  const openNewDialog = () => {
    setEditingBatch(null);
    setBatchName("");
    setDialogOpen(true);
  };

  const filteredBatches = batches.filter(b => {
    // Filter by search query
    if (!b.name.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    // Filter by closed status
    if (!showClosed && b.status === "closed") return false;
    return true;
  });


  const handleCloseBatch = async (batch) => {
    if (!confirm(`Close/archive "${batch.name}"?\n\nThis will:\n- Prevent adding new exams\n- Prevent adding/removing students\n- Keep all data accessible\n- You can reopen it later if needed`)) {
      return;
    }

    try {
      await axios.put(`${API}/batches/${batch.batch_id}/close`);
      toast.success("Batch closed successfully");
      fetchBatches();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to close batch");
    }
  };

  const handleReopenBatch = async (batch) => {
    if (!confirm(`Reopen "${batch.name}"?`)) {
      return;
    }

    try {
      await axios.put(`${API}/batches/${batch.batch_id}/reopen`);
      toast.success("Batch reopened successfully");
      fetchBatches();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to reopen batch");
    }
  };

  // Fetch available students (not in the current batch)
  const fetchAvailableStudents = async () => {
    try {
      const response = await axios.get(`${API}/students`);
      // Filter out students already in the batch
      const batchStudentIds = batchDetails?.students_list?.map(s => s.user_id) || [];
      const available = response.data.filter(s => !batchStudentIds.includes(s.user_id));
      setAvailableStudents(available);
    } catch (error) {
      console.error("Error fetching students:", error);
    }
  };

  // Open add student dialog
  const openAddStudentDialog = () => {
    setAddStudentMode("existing");
    setSelectedStudentToAdd("");
    setNewStudentForm({ name: "", email: "", student_id: "" });
    fetchAvailableStudents();
    setAddStudentDialogOpen(true);
  };

  // Add existing student to batch
  const handleAddExistingStudent = async () => {
    if (!selectedStudentToAdd) {
      toast.error("Please select a student");
      return;
    }

    setAddingStudent(true);
    try {
      await axios.post(`${API}/batches/${batchDetails.batch_id}/students`, {
        student_id: selectedStudentToAdd
      });
      toast.success("Student added to batch");
      setAddStudentDialogOpen(false);
      fetchBatchDetails(batchDetails.batch_id);
      fetchBatches();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to add student");
    } finally {
      setAddingStudent(false);
    }
  };

  // Create and add new student to batch
  const handleAddNewStudent = async () => {
    if (!newStudentForm.name.trim() || !newStudentForm.email.trim()) {
      toast.error("Name and email are required");
      return;
    }

    setAddingStudent(true);
    try {
      // Create new student
      const createResponse = await axios.post(`${API}/students`, {
        name: newStudentForm.name,
        email: newStudentForm.email,
        student_id: newStudentForm.student_id || undefined,
        batch_id: batchDetails.batch_id
      });
      
      toast.success("Student created and added to batch");
      setAddStudentDialogOpen(false);
      fetchBatchDetails(batchDetails.batch_id);
      fetchBatches();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to create student");
    } finally {
      setAddingStudent(false);
    }
  };

  // Remove student from batch
  const handleRemoveStudent = async (student) => {
    if (!confirm(`Remove "${student.name}" from this batch?`)) {
      return;
    }

    try {
      await axios.delete(`${API}/batches/${batchDetails.batch_id}/students/${student.user_id}`);
      toast.success("Student removed from batch");
      fetchBatchDetails(batchDetails.batch_id);
      fetchBatches();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to remove student");
    }
  };

  // Delete exam from batch
  const handleDeleteExam = async (exam) => {
    if (!confirm(`Delete exam "${exam.exam_name}"?\n\nThis will also delete all submissions and grades for this exam. This action cannot be undone.`)) {
      return;
    }

    try {
      await axios.delete(`${API}/exams/${exam.exam_id}`);
      toast.success("Exam deleted successfully");
      fetchBatchDetails(batchDetails.batch_id);
      fetchBatches();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to delete exam");
    }
  };


  return (
    <Layout user={user}>
      <div className="space-y-4 lg:space-y-6" data-testid="manage-batches-page">
        {/* Header */}
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-xl lg:text-2xl font-bold text-foreground">Manage Batches</h1>
            <p className="text-sm text-muted-foreground">Create and manage class batches</p>
          </div>
          
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button onClick={openNewDialog} data-testid="add-batch-btn">
                <Plus className="w-4 h-4 mr-2" />
                New Batch
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{editingBatch ? "Edit Batch" : "Create New Batch"}</DialogTitle>
              </DialogHeader>
              <form onSubmit={(e) => {
                e.preventDefault();
                handleSubmit();
              }}>
                <div className="py-4">
                  <Label htmlFor="batch-name-field">Batch Name *</Label>
                  <Input 
                    id="batch-name-field"
                    name="batchName"
                    value={batchName}
                    onChange={(e) => setBatchName(e.target.value)}
                    placeholder="e.g., Class 10-A, Grade 5 Science"
                    className="mt-2"
                    data-testid="batch-name-input"
                    required
                  />
                </div>
                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
                  <Button type="submit" disabled={!batchName.trim()} data-testid="save-batch-btn">
                    {editingBatch ? "Save Changes" : "Create Batch"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:gap-6">
          {/* Batches List */}
          <div className="lg:col-span-1">
            <Card>
              <CardHeader className="p-4">
                <div className="space-y-3">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input 
                      placeholder="Search batches..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                  <div className="flex items-center space-x-2">
                    <Checkbox 
                      id="show-closed"
                      checked={showClosed}
                      onCheckedChange={setShowClosed}
                    />
                    <label 
                      htmlFor="show-closed"
                      className="text-sm text-muted-foreground cursor-pointer"
                    >
                      Show archived batches
                    </label>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <ScrollArea className="h-[400px] lg:h-[500px]">
                  {loading ? (
                    <div className="p-4 space-y-2">
                      {[1, 2, 3, 4].map(i => (
                        <div key={i} className="h-16 bg-muted animate-pulse rounded-lg" />
                      ))}
                    </div>
                  ) : filteredBatches.length === 0 ? (
                    <div className="text-center py-8 px-4">
                      <BookOpen className="w-12 h-12 mx-auto text-muted-foreground/50 mb-3" />
                      <p className="text-muted-foreground">No batches found</p>
                      <Button variant="outline" className="mt-3" onClick={openNewDialog}>
                        <Plus className="w-4 h-4 mr-2" />
                        Create first batch
                      </Button>
                    </div>
                  ) : (
                    <div className="p-2 space-y-1">
                      {filteredBatches.map((batch) => (
                        <div 
                          key={batch.batch_id}
                          onClick={() => fetchBatchDetails(batch.batch_id)}
                          className={`p-3 rounded-lg cursor-pointer transition-all flex items-center justify-between ${
                            selectedBatch === batch.batch_id
                              ? "bg-primary/10 border border-primary"
                              : "hover:bg-muted"
                          }`}
                          data-testid={`batch-${batch.batch_id}`}
                        >
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                              <BookOpen className="w-5 h-5 text-primary" />
                            </div>
                            <div>
                              <p className="font-medium">{batch.name}</p>
                              <p className="text-xs text-muted-foreground">
                                {batch.student_count || 0} students
                              </p>
                            </div>
                          </div>
                          <ChevronRight className="w-4 h-4 text-muted-foreground" />
                        </div>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          </div>

          {/* Batch Details */}
          <div className="lg:col-span-2">
            {!batchDetails ? (
              <Card className="h-full flex items-center justify-center min-h-[400px]">
                <div className="text-center">
                  <BookOpen className="w-16 h-16 mx-auto text-muted-foreground/30 mb-4" />
                  <p className="text-lg font-medium text-muted-foreground">Select a batch</p>
                  <p className="text-sm text-muted-foreground">Click on a batch to view details</p>
                </div>
              </Card>
            ) : (
              <Card>
                <CardHeader className="flex flex-row items-start justify-between">
                  <div>
                    <CardTitle className="text-xl">{batchDetails.name}</CardTitle>
                    <CardDescription>
                      Created {new Date(batchDetails.created_at).toLocaleDateString()}
                    </CardDescription>
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    {batchDetails.status === "closed" && (
                      <Badge className="bg-gray-500">Archived</Badge>
                    )}
                    {batchDetails.status !== "closed" ? (
                      <>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => openEditDialog(batchDetails)}
                        >
                          <Edit2 className="w-4 h-4 mr-1" />
                          Edit
                        </Button>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => handleCloseBatch(batchDetails)}
                          className="text-orange-600 hover:text-orange-700"
                        >
                          <Archive className="w-4 h-4 mr-1" />
                          Archive Batch
                        </Button>
                      </>
                    ) : (
                      <Button 
                        variant="outline" 
                        size="sm"
                        onClick={() => handleReopenBatch(batchDetails)}
                        className="text-green-600 hover:text-green-700"
                      >
                        <LockOpen className="w-4 h-4 mr-1" />
                        Reopen Batch
                      </Button>
                    )}
                    <Button 
                      variant="outline" 
                      size="sm"
                      onClick={() => handleDelete(batchDetails)}
                      className="text-destructive hover:text-destructive"
                      disabled={batchDetails.student_count > 0}
                    >
                      <Trash2 className="w-4 h-4 mr-1" />
                      Delete
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* Stats */}
                  <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                    <div className="p-4 bg-blue-50 rounded-lg">
                      <div className="flex items-center gap-2">
                        <Users className="w-5 h-5 text-blue-600" />
                        <span className="text-2xl font-bold text-blue-700">
                          {batchDetails.student_count || 0}
                        </span>
                      </div>
                      <p className="text-sm text-blue-600 mt-1">Students</p>
                    </div>
                    <div className="p-4 bg-orange-50 rounded-lg">
                      <div className="flex items-center gap-2">
                        <FileText className="w-5 h-5 text-orange-600" />
                        <span className="text-2xl font-bold text-orange-700">
                          {batchDetails.exams?.length || 0}
                        </span>
                      </div>
                      <p className="text-sm text-orange-600 mt-1">Exams</p>
                    </div>
                  </div>

                  {/* Warning if empty */}
                  {batchDetails.student_count === 0 && (
                    <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg flex items-start gap-3">
                      <AlertTriangle className="w-5 h-5 text-yellow-600 flex-shrink-0" />
                      <div>
                        <p className="font-medium text-yellow-800">Empty Batch</p>
                        <p className="text-sm text-yellow-700">This batch has no students. Add students or delete this batch.</p>
                        <Button 
                          variant="outline" 
                          size="sm" 
                          className="mt-2"
                          onClick={() => navigate("/teacher/students")}
                        >
                          Add Students
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Students List */}
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="font-semibold flex items-center gap-2">
                        <Users className="w-4 h-4" />
                        Students ({batchDetails.students_list?.length || 0})
                      </h3>
                      {batchDetails.status !== "closed" && (
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={openAddStudentDialog}
                          className="text-green-600 hover:text-green-700"
                        >
                          <UserPlus className="w-4 h-4 mr-1" />
                          Add Student
                        </Button>
                      )}
                    </div>
                    {batchDetails.students_list?.length > 0 ? (
                      <div className="space-y-2 max-h-48 overflow-y-auto">
                        {batchDetails.students_list.map((student) => (
                          <div 
                            key={student.user_id}
                            className="flex items-center justify-between p-3 bg-muted/50 rounded-lg group"
                          >
                            <div className="flex items-center gap-3">
                              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                                <span className="text-sm font-medium text-primary">
                                  {student.name?.charAt(0)}
                                </span>
                              </div>
                              <div>
                                <p className="font-medium text-sm">{student.name}</p>
                                <p className="text-xs text-muted-foreground">{student.email}</p>
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {student.student_id && (
                                <Badge variant="outline" className="text-xs">
                                  {student.student_id}
                                </Badge>
                              )}
                              {batchDetails.status !== "closed" && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => handleRemoveStudent(student)}
                                  className="opacity-0 group-hover:opacity-100 text-red-500 hover:text-red-700 hover:bg-red-50 h-8 w-8 p-0"
                                >
                                  <UserMinus className="w-4 h-4" />
                                </Button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-4 text-muted-foreground text-sm">
                        No students in this batch
                      </div>
                    )}
                  </div>

                  {/* Exams List */}
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="font-semibold flex items-center gap-2">
                        <FileText className="w-4 h-4" />
                        Exams ({batchDetails.exams?.length || 0})
                      </h3>
                      {batchDetails.status !== "closed" && (
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => navigate("/teacher/upload-grade", { state: { preselectedBatch: batchDetails.batch_id } })}
                          className="text-blue-600 hover:text-blue-700"
                        >
                          <Plus className="w-4 h-4 mr-1" />
                          Add Exam
                        </Button>
                      )}
                    </div>
                    {batchDetails.exams?.length > 0 ? (
                      <div className="space-y-2">
                        {batchDetails.exams.map((exam) => (
                          <div 
                            key={exam.exam_id}
                            className="flex items-center justify-between p-3 bg-muted/50 rounded-lg group"
                          >
                            <div className="flex items-center gap-3 flex-1">
                              <span className="font-medium text-sm">{exam.exam_name}</span>
                              <Badge 
                                className={
                                  exam.status === "completed" 
                                    ? "bg-green-100 text-green-700" 
                                    : exam.status === "closed"
                                    ? "bg-gray-100 text-gray-700"
                                    : "bg-yellow-100 text-yellow-700"
                                }
                              >
                                {exam.status}
                              </Badge>
                            </div>
                            <div className="flex items-center gap-2">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => navigate("/teacher/manage-exams", { state: { selectedExamId: exam.exam_id } })}
                                className="text-blue-600 hover:text-blue-700 hover:bg-blue-50 h-8"
                              >
                                View
                              </Button>
                              {batchDetails.status !== "closed" && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => handleDeleteExam(exam)}
                                  className="opacity-0 group-hover:opacity-100 text-red-500 hover:text-red-700 hover:bg-red-50 h-8 w-8 p-0"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </Button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-4 text-muted-foreground text-sm">
                        No exams in this batch
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>

      {/* Add Student Dialog */}
      <Dialog open={addStudentDialogOpen} onOpenChange={setAddStudentDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <UserPlus className="w-5 h-5 text-green-600" />
              Add Student to {batchDetails?.name}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {/* Mode Selection */}
            <div className="flex gap-2">
              <Button
                variant={addStudentMode === "existing" ? "default" : "outline"}
                size="sm"
                onClick={() => setAddStudentMode("existing")}
                className="flex-1"
              >
                Existing Student
              </Button>
              <Button
                variant={addStudentMode === "new" ? "default" : "outline"}
                size="sm"
                onClick={() => setAddStudentMode("new")}
                className="flex-1"
              >
                New Student
              </Button>
            </div>

            {addStudentMode === "existing" ? (
              /* Add Existing Student */
              <div className="space-y-3">
                <Label>Select Student</Label>
                {availableStudents.length > 0 ? (
                  <Select value={selectedStudentToAdd} onValueChange={setSelectedStudentToAdd}>
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
                  <p className="text-sm text-muted-foreground text-center py-4">
                    No available students. All students are already in this batch or no students exist.
                  </p>
                )}
              </div>
            ) : (
              /* Create New Student */
              <div className="space-y-3">
                <div>
                  <Label htmlFor="new-student-name">Name *</Label>
                  <Input
                    id="new-student-name"
                    value={newStudentForm.name}
                    onChange={(e) => setNewStudentForm({...newStudentForm, name: e.target.value})}
                    placeholder="Student name"
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label htmlFor="new-student-email">Email *</Label>
                  <Input
                    id="new-student-email"
                    type="email"
                    value={newStudentForm.email}
                    onChange={(e) => setNewStudentForm({...newStudentForm, email: e.target.value})}
                    placeholder="student@example.com"
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label htmlFor="new-student-id">Student ID (Optional)</Label>
                  <Input
                    id="new-student-id"
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
            <Button variant="outline" onClick={() => setAddStudentDialogOpen(false)}>
              Cancel
            </Button>
            {addStudentMode === "existing" ? (
              <Button 
                onClick={handleAddExistingStudent}
                disabled={!selectedStudentToAdd || addingStudent}
              >
                {addingStudent ? "Adding..." : "Add to Batch"}
              </Button>
            ) : (
              <Button 
                onClick={handleAddNewStudent}
                disabled={!newStudentForm.name.trim() || !newStudentForm.email.trim() || addingStudent}
              >
                {addingStudent ? "Creating..." : "Create & Add"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
