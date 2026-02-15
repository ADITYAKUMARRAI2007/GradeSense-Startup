import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Checkbox } from "../../components/ui/checkbox";
import { ScrollArea } from "../../components/ui/scroll-area";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Progress } from "../../components/ui/progress";
import { toast } from "sonner";
import { useDropzone } from "react-dropzone";
import { 
  FileText,
  Search,
  Trash2,
  Users,
  Calendar,
  BookOpen,
  ChevronRight,
  AlertTriangle,
  CheckCircle,
  Upload,
  Lock,
  LockOpen,
  CheckCircle2,
  Sparkles,
  RefreshCw,
  Tag,
  Brain,
  Edit2,
  Save,
  X,
  RotateCcw,
  RotateCw,
  Plus,
  Loader2,
  AlertCircle as AlertCircleIcon,
  Eye,
  EyeOff
} from "lucide-react";
import QuestionEditor from "../../components/QuestionEditor";

export default function ManageExams({ user }) {
  const [exams, setExams] = useState([]);
  const [batches, setBatches] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedExam, setSelectedExam] = useState(null);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [uploadingPapers, setUploadingPapers] = useState(false);
  const [paperFiles, setPaperFiles] = useState([]);
  const [uploadJobId, setUploadJobId] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState("");
  const [extractingQuestions, setExtractingQuestions] = useState(false);
  const [inferringTopics, setInferringTopics] = useState(false);
  const [submissions, setSubmissions] = useState([]);
  const [loadingSubmissions, setLoadingSubmissions] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [savingEdit, setSavingEdit] = useState(false);
  const [regrading, setRegrading] = useState(false);
  const [regradeDialogOpen, setRegradeDialogOpen] = useState(false);
  const [uploadingModelAnswer, setUploadingModelAnswer] = useState(false);
  const [uploadingQuestionPaper, setUploadingQuestionPaper] = useState(false);
  
  // New state for question editing
  const [editQuestionsDialogOpen, setEditQuestionsDialogOpen] = useState(false);
  const [editingQuestions, setEditingQuestions] = useState([]);
  const [savingQuestions, setSavingQuestions] = useState(false);
  const [reExtracting, setReExtracting] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  
  // Publish settings dialog
  const [publishDialogOpen, setPublishDialogOpen] = useState(false);
  const [publishSettings, setPublishSettings] = useState({
    show_model_answer: false,
    show_answer_sheet: true,
    show_question_paper: true
  });

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
    onDrop: (acceptedFiles) => {
      setPaperFiles(acceptedFiles);
    }
  });

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
    if (selectedExam) {
      fetchSubmissions(selectedExam.exam_id);
    } else {
      setSubmissions([]);
    }
  }, [selectedExam]);

  const fetchSubmissions = async (examId) => {
    try {
      setLoadingSubmissions(true);
      const response = await axios.get(`${API}/exams/${examId}/submissions`);
      setSubmissions(response.data);
    } catch (error) {
      console.error("Error fetching submissions:", error);
      toast.error("Failed to load submissions");
    } finally {
      setLoadingSubmissions(false);
    }
  };

  const fetchData = async () => {
    try {
      const [examsRes, batchesRes, subjectsRes] = await Promise.all([
        axios.get(`${API}/exams`),
        axios.get(`${API}/batches`),
        axios.get(`${API}/subjects`)
      ]);
      setExams(examsRes.data);
      setBatches(batchesRes.data);
      setSubjects(subjectsRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  const publishResults = async (examId) => {
    try {
      await axios.post(`${API}/exams/${examId}/publish-results`, publishSettings);
      toast.success("Results published! Students can now see their scores.");
      fetchData();
      setPublishDialogOpen(false);
    } catch (error) {
      console.error("Publish error:", error);
      toast.error("Failed to publish results");
    }
  };

  const unpublishResults = async (examId) => {
    try {
      await axios.post(`${API}/exams/${examId}/unpublish-results`);
      toast.success("Results hidden from students");
      fetchData();
    } catch (error) {
      console.error("Unpublish error:", error);
      toast.error("Failed to unpublish results");
    }
  };

  const handleUploadMorePapers = async () => {
    if (paperFiles.length === 0) {
      toast.error("Please select PDF files to upload");
      return;
    }

    try {
      setUploadingPapers(true);
      setUploadProgress(0);
      setUploadStatus("Uploading files...");
      
      const formData = new FormData();
      paperFiles.forEach(file => {
        formData.append("files", file);
      });

      // Use background grading endpoint for better progress tracking
      const response = await axios.post(
        `${API}/exams/${selectedExam.exam_id}/grade-papers-bg`, 
        formData, 
        {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 120000 // 2 minute timeout
        }
      );

      // Start polling for job status
      if (response.data.job_id) {
        setUploadJobId(response.data.job_id);
        setUploadStatus("Grading in progress...");
        pollJobStatus(response.data.job_id);
      } else {
        // Fallback to old sync response handling
        handleUploadComplete(response.data);
      }

    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to upload papers");
      setUploadingPapers(false);
      setUploadProgress(0);
      setUploadStatus("");
    }
  };

  const handleCancelGrading = async () => {
    if (!uploadJobId) {
      toast.error("No active grading job found");
      return;
    }

    if (!confirm("Are you sure you want to cancel this grading job? This cannot be undone.")) {
      return;
    }

    try {
      await axios.post(`${API}/grading-jobs/${uploadJobId}/cancel`, {}, {
        withCredentials: true
      });
      
      toast.success("Grading cancelled successfully");
      
      // Reset state
      setUploadingPapers(false);
      setUploadProgress(0);
      setUploadStatus("");
      setUploadJobId(null);
      
    } catch (error) {
      console.error("Error cancelling grading:", error);
      toast.error(error.response?.data?.detail || "Failed to cancel grading");
    }
  };

  const pollJobStatus = async (jobId) => {
    const maxAttempts = 300; // 5 minutes max (300 * 1 second)
    let attempts = 0;

    const checkStatus = async () => {
      try {
        const response = await axios.get(`${API}/grading-jobs/${jobId}`, {
          withCredentials: true
        });
        const job = response.data;

        // Update progress
        const progress = job.total_papers > 0 
          ? Math.round((job.processed_papers / job.total_papers) * 100)
          : 0;
        
        setUploadProgress(progress);
        setUploadStatus(`Grading papers: ${job.processed_papers}/${job.total_papers}`);

        if (job.status === "completed") {
          // Job completed
          handleUploadComplete({
            processed: job.successful,
            errors: job.errors || []
          });
          return;
        } else if (job.status === "failed") {
          toast.error("Grading job failed");
          setUploadingPapers(false);
          setUploadProgress(0);
          setUploadStatus("");
          return;
        } else if (job.status === "cancelled") {
          toast.warning("Grading was cancelled");
          setUploadingPapers(false);
          setUploadProgress(0);
          setUploadStatus("");
          return;
        }

        // Continue polling if still processing
        attempts++;
        if (attempts < maxAttempts) {
          setTimeout(checkStatus, 1000);
        } else {
          toast.error("Grading timeout - please check Review Papers later");
          setUploadingPapers(false);
          setUploadProgress(0);
          setUploadStatus("");
        }
      } catch (error) {
        console.error("Error polling job status:", error);
        attempts++;
        if (attempts < maxAttempts) {
          setTimeout(checkStatus, 1000);
        } else {
          setUploadingPapers(false);
          setUploadProgress(0);
          setUploadStatus("");
        }
      }
    };

    checkStatus();
  };

  const handleUploadComplete = (data) => {
    if (data.errors && data.errors.length > 0) {
      toast.warning(`Uploaded ${data.processed} papers. ${data.errors.length} files had errors.`);
      data.errors.slice(0, 3).forEach(error => {
        toast.error(`${error.filename}: ${error.error}`, { duration: 5000 });
      });
      if (data.errors.length > 3) {
        toast.info(`...and ${data.errors.length - 3} more errors`);
      }
    } else {
      toast.success(`Successfully graded ${data.processed} additional papers!`);
    }

    setUploadDialogOpen(false);
    setPaperFiles([]);
    setUploadingPapers(false);
    setUploadProgress(0);
    setUploadStatus("");
    setUploadJobId(null);
    fetchData();
    if (selectedExam) {
      fetchSubmissions(selectedExam.exam_id);
    }
  };

  const handleCloseExam = async (exam) => {
    if (!confirm(`Close "${exam.exam_name}"? You can reopen it later if needed.`)) {
      return;
    }

    try {
      await axios.put(`${API}/exams/${exam.exam_id}/close`);
      toast.success("Exam closed successfully");
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to close exam");
    }
  };

  const handleReopenExam = async (exam) => {
    if (!confirm(`Reopen "${exam.exam_name}"?`)) {
      return;
    }

    try {
      await axios.put(`${API}/exams/${exam.exam_id}/reopen`);
      toast.success("Exam reopened successfully");
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to reopen exam");
    }
  };

  const handleExtractQuestions = async (exam) => {
    // Check for documents - either in old storage (images array) or new storage (has_* flags)
    const hasModelAnswer = exam.model_answer_images?.length > 0 || exam.has_model_answer;
    const hasQuestionPaper = exam.question_paper_images?.length > 0 || exam.has_question_paper;
    
    if (!hasModelAnswer && !hasQuestionPaper) {
      toast.error("No model answer or question paper uploaded for this exam");
      return;
    }

    setExtractingQuestions(true);
    try {
      const response = await axios.post(`${API}/exams/${exam.exam_id}/extract-questions`);
      toast.success(`Extracted ${response.data.updated_count || response.data.questions?.length || 0} questions from ${response.data.source || 'document'}`);
      fetchData();
      // Refresh selected exam
      const updatedExam = await axios.get(`${API}/exams/${exam.exam_id}`);
      setSelectedExam(updatedExam.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to extract questions");
    } finally {
      setExtractingQuestions(false);
    }
  };

  const handleInferTopics = async (exam) => {
    if (!exam.questions?.length) {
      toast.error("No questions found. Extract questions first.");
      return;
    }

    setInferringTopics(true);
    try {
      const response = await axios.post(`${API}/exams/${exam.exam_id}/infer-topics`);
      toast.success("Topic tags inferred successfully!");
      fetchData();
      // Refresh selected exam
      const updatedExam = await axios.get(`${API}/exams/${exam.exam_id}`);
      setSelectedExam(updatedExam.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to infer topics");
    } finally {
      setInferringTopics(false);
    }
  };

  const handleDeleteSubmission = async (submission) => {
    if (!confirm(`Delete ${submission.student_name}'s paper? This action cannot be undone.`)) {
      return;
    }

    try {
      await axios.delete(`${API}/submissions/${submission.submission_id}`);
      toast.success("Paper deleted successfully");
      
      // Refresh submissions and exam data
      fetchSubmissions(selectedExam.exam_id);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to delete paper");
    }
  };

  const startEditMode = () => {
    setEditForm({
      exam_name: selectedExam.exam_name,
      subject_id: selectedExam.subject_id,
      total_marks: selectedExam.total_marks,
      grading_mode: selectedExam.grading_mode,
      exam_type: selectedExam.exam_type,
      exam_date: selectedExam.exam_date
    });
    setEditMode(true);
  };

  const cancelEditMode = () => {
    setEditMode(false);
    setEditForm({});
  };

  const handleSaveEdit = async () => {
    setSavingEdit(true);
    try {
      await axios.put(`${API}/exams/${selectedExam.exam_id}`, {
        exam_name: editForm.exam_name,
        subject_id: editForm.subject_id,
        total_marks: parseFloat(editForm.total_marks),
        grading_mode: editForm.grading_mode,
        exam_type: editForm.exam_type,
        exam_date: editForm.exam_date
      });
      toast.success("Exam updated successfully");
      
      // Refresh data
      await fetchData();
      const updatedExam = await axios.get(`${API}/exams/${selectedExam.exam_id}`);
      setSelectedExam(updatedExam.data);
      setEditMode(false);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to update exam");
    } finally {
      setSavingEdit(false);
    }
  };

  const handleRegradeAll = async () => {
    setRegrading(true);
    try {
      const response = await axios.post(`${API}/exams/${selectedExam.exam_id}/regrade-all`);
      toast.success(`Successfully regraded ${response.data.regraded_count || 0} papers`);
      setRegradeDialogOpen(false);
      
      // Refresh submissions
      fetchSubmissions(selectedExam.exam_id);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to regrade papers");
    } finally {
      setRegrading(false);
    }
  };

  const handleDelete = async (exam) => {
    if (!confirm(`Are you sure you want to delete "${exam.exam_name}"? This will also delete all submissions and re-evaluation requests associated with this exam.`)) {
      return;
    }
    
    try {
      await axios.delete(`${API}/exams/${exam.exam_id}`);
      toast.success("Exam deleted successfully");
      fetchData();
      if (selectedExam?.exam_id === exam.exam_id) {
        setSelectedExam(null);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to delete exam");
    }
  };

  // Validation function for questions
  const validateQuestions = (questions) => {
    const warnings = [];
    const errors = [];
    let totalMarks = 0;
    const questionNumbers = new Set();
    
    questions.forEach((q, idx) => {
      const qNum = q.question_number;
      
      if (!qNum) {
        errors.push(`Question at index ${idx + 1} is missing question_number`);
        return;
      }
      
      if (questionNumbers.has(qNum)) {
        errors.push(`Duplicate question number: Q${qNum}`);
      }
      questionNumbers.add(qNum);
      
      const qMarks = q.max_marks || 0;
      if (qMarks <= 0) {
        errors.push(`Q${qNum}: Missing or invalid max_marks`);
      }
      
      totalMarks += qMarks;
      
      if (q.sub_questions && q.sub_questions.length > 0) {
        const subTotal = q.sub_questions.reduce((sum, sub) => sum + (sub.max_marks || 0), 0);
        if (Math.abs(subTotal - qMarks) > 0.1) {
          warnings.push(`Q${qNum}: Sub-questions (${subTotal}) ≠ Total (${qMarks})`);
        }
        
        q.sub_questions.forEach(sub => {
          if (sub.sub_questions && sub.sub_questions.length > 0) {
            const nestedTotal = sub.sub_questions.reduce((sum, ssub) => sum + (ssub.max_marks || 0), 0);
            if (Math.abs(nestedTotal - sub.max_marks) > 0.1) {
              warnings.push(`Q${qNum}(${sub.sub_id}): Nested marks (${nestedTotal}) ≠ Parent (${sub.max_marks})`);
            }
          }
        });
      }
    });
    
    if (questionNumbers.size > 0) {
      const maxNum = Math.max(...questionNumbers);
      const expected = new Set(Array.from({length: maxNum}, (_, i) => i + 1));
      const missing = [...expected].filter(n => !questionNumbers.has(n));
      if (missing.length > 0) {
        warnings.push(`Missing question numbers: ${missing.join(', ')}`);
      }
    }
    
    setValidationResult({
      valid: errors.length === 0,
      errors,
      warnings,
      totalMarks,
      questionCount: questions.length
    });
  };

  // Handle edit questions
  const handleEditQuestions = (exam) => {
    setSelectedExam(exam);
    setEditingQuestions(exam.questions || []);
    validateQuestions(exam.questions || []);
    setEditQuestionsDialogOpen(true);
  };

  // Handle re-extract questions
  const handleReExtractQuestions = async (examId) => {
    try {
      setReExtracting(true);
      const response = await axios.post(`${API}/exams/${examId}/re-extract-questions`);
      toast.success(response.data.message);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to re-extract questions");
    } finally {
      setReExtracting(false);
    }
  };

  // Handle save questions
  const handleSaveQuestions = async () => {
    if (!validationResult || validationResult.errors.length > 0) {
      toast.error("Please fix errors before saving");
      return;
    }
    
    try {
      setSavingQuestions(true);
      await axios.put(`${API}/exams/${selectedExam.exam_id}`, {
        questions: editingQuestions,
        total_marks: validationResult.totalMarks
      });
      toast.success("Questions updated successfully");
      setEditQuestionsDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to save questions");
    } finally {
      setSavingQuestions(false);
    }
  };

  // Upload Model Answer Paper
  const handleUploadModelAnswer = async (event) => {
    const file = event.target.files?.[0];
    if (!file || !selectedExam) return;
    
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toast.error("Please upload a PDF file");
      return;
    }

    setUploadingModelAnswer(true);
    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await axios.post(
        `${API}/exams/${selectedExam.exam_id}/upload-model-answer`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );

      toast.success(response.data.message || "Model answer uploaded successfully!");
      
      // Refresh exam data
      const examResponse = await axios.get(`${API}/exams/${selectedExam.exam_id}`);
      setSelectedExam(examResponse.data);
      fetchData();
    } catch (error) {
      console.error("Upload error:", error);
      toast.error(error.response?.data?.detail || "Failed to upload model answer");
    } finally {
      setUploadingModelAnswer(false);
      event.target.value = ""; // Reset file input
    }
  };

  // Upload Question Paper
  const handleUploadQuestionPaper = async (event) => {
    const file = event.target.files?.[0];
    if (!file || !selectedExam) return;
    
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toast.error("Please upload a PDF file");
      return;
    }

    setUploadingQuestionPaper(true);
    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await axios.post(
        `${API}/exams/${selectedExam.exam_id}/upload-question-paper`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );

      toast.success(response.data.message || "Question paper uploaded successfully!");
      
      // Refresh exam data
      const examResponse = await axios.get(`${API}/exams/${selectedExam.exam_id}`);
      setSelectedExam(examResponse.data);
      fetchData();
    } catch (error) {
      console.error("Upload error:", error);
      toast.error(error.response?.data?.detail || "Failed to upload question paper");
    } finally {
      setUploadingQuestionPaper(false);
      event.target.value = ""; // Reset file input
    }
  };

  const getBatchName = (batchId) => {
    const batch = batches.find(b => b.batch_id === batchId);
    return batch?.name || "Unknown";
  };

  const getSubjectName = (subjectId) => {
    const subject = subjects.find(s => s.subject_id === subjectId);
    return subject?.name || "Unknown";
  };

  const getStatusBadge = (status) => {
    const styles = {
      draft: "bg-gray-100 text-gray-700",
      processing: "bg-blue-100 text-blue-700",
      completed: "bg-green-100 text-green-700"
    };
    return (
      <Badge className={styles[status] || styles.draft}>
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </Badge>
    );
  };

  const filteredExams = exams.filter(e => 
    e.exam_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    getBatchName(e.batch_id).toLowerCase().includes(searchQuery.toLowerCase()) ||
    getSubjectName(e.subject_id).toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <Layout user={user}>
      <div className="space-y-4 lg:space-y-6" data-testid="manage-exams-page">
        {/* Header */}
        <div>
          <h1 className="text-xl lg:text-2xl font-bold text-foreground">Manage Exams</h1>
          <p className="text-sm text-muted-foreground">View and manage all your exams</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:gap-6">
          {/* Exams List */}
          <div className="lg:col-span-1">
            <Card>
              <CardHeader className="p-4">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                  <Input 
                    placeholder="Search exams..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9"
                    data-testid="search-input"
                  />
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <ScrollArea className="h-[400px] lg:h-[500px]">
                  {loading ? (
                    <div className="p-4 space-y-2">
                      {[1, 2, 3, 4].map(i => (
                        <div key={i} className="h-20 bg-muted animate-pulse rounded-lg" />
                      ))}
                    </div>
                  ) : filteredExams.length === 0 ? (
                    <div className="text-center py-8 px-4">
                      <FileText className="w-12 h-12 mx-auto text-muted-foreground/50 mb-3" />
                      <p className="text-muted-foreground">No exams found</p>
                    </div>
                  ) : (
                    <div className="p-2 space-y-1">
                      {filteredExams.map((exam) => (
                        <div 
                          key={exam.exam_id}
                          onClick={() => setSelectedExam(exam)}
                          className={`p-3 rounded-lg cursor-pointer transition-all flex items-center justify-between ${
                            selectedExam?.exam_id === exam.exam_id
                              ? "bg-primary/10 border border-primary"
                              : "hover:bg-muted"
                          }`}
                          data-testid={`exam-${exam.exam_id}`}
                        >
                          <div className="flex items-center gap-3 min-w-0 flex-1">
                            <div className="w-10 h-10 rounded-lg bg-orange-50 flex items-center justify-center flex-shrink-0">
                              <FileText className="w-5 h-5 text-orange-600" />
                            </div>
                            <div className="min-w-0">
                              <p className="font-medium truncate">{exam.exam_name}</p>
                              <div className="flex items-center gap-2 text-xs text-muted-foreground truncate">
                                <span>
                                  {getBatchName(exam.batch_id)} • {getSubjectName(exam.subject_id)}
                                  {exam.upsc_paper ? ` • ${exam.upsc_paper}` : ""}
                                </span>
                                {exam.results_published ? (
                                  <Badge variant="success" className="bg-green-500 text-white text-[10px] px-1 py-0">
                                    Published
                                  </Badge>
                                ) : (
                                  <Badge variant="secondary" className="text-[10px] px-1 py-0">
                                    Draft
                                  </Badge>
                                )}
                              </div>
                            </div>
                          </div>
                          <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                        </div>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          </div>

          {/* Exam Details */}
          <div className="lg:col-span-2">
            {!selectedExam ? (
              <Card className="h-full flex items-center justify-center min-h-[400px]">
                <div className="text-center">
                  <FileText className="w-16 h-16 mx-auto text-muted-foreground/30 mb-4" />
                  <p className="text-lg font-medium text-muted-foreground">Select an exam</p>
                  <p className="text-sm text-muted-foreground">Click on an exam to view details</p>
                </div>
              </Card>
            ) : (
              <Card>
                <CardHeader className="flex flex-row items-start justify-between">
                  <div>
                    <CardTitle className="text-xl">{selectedExam.exam_name}</CardTitle>
                    <CardDescription>
                      Created {new Date(selectedExam.created_at).toLocaleDateString()}
                    </CardDescription>
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    {/* Publish/Unpublish Button */}
                    <Button
                      variant={selectedExam.results_published ? "outline" : "default"}
                      size="sm"
                      onClick={() => {
                        if (selectedExam.results_published) {
                          unpublishResults(selectedExam.exam_id);
                        } else {
                          setPublishDialogOpen(true);
                        }
                      }}
                      className={selectedExam.results_published ? "" : "bg-green-500 hover:bg-green-600"}
                    >
                      {selectedExam.results_published ? (
                        <>
                          <EyeOff className="w-4 h-4 mr-1" />
                          Unpublish
                        </>
                      ) : (
                        <>
                          <Eye className="w-4 h-4 mr-1" />
                          Publish
                        </>
                      )}
                    </Button>
                    
                    {getStatusBadge(selectedExam.status)}
                    {!editMode && (
                      <>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={startEditMode}
                          className="text-blue-600 hover:text-blue-700"
                        >
                          <Edit2 className="w-4 h-4 mr-1" />
                          Edit
                        </Button>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => handleEditQuestions(selectedExam)}
                          className="text-green-600 hover:text-green-700"
                        >
                          <Edit2 className="w-4 h-4 mr-1" />
                          Edit Questions
                        </Button>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => handleReExtractQuestions(selectedExam.exam_id)}
                          disabled={reExtracting}
                          className="text-indigo-600 hover:text-indigo-700"
                        >
                          {reExtracting ? (
                            <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                          ) : (
                            <RotateCw className="w-4 h-4 mr-1" />
                          )}
                          Re-extract Questions
                        </Button>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => setRegradeDialogOpen(true)}
                          className="text-purple-600 hover:text-purple-700"
                        >
                          <RotateCcw className="w-4 h-4 mr-1" />
                          Regrade All
                        </Button>
                      </>
                    )}
                    {selectedExam.status !== "closed" && !editMode && (
                      <>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => {
                            setUploadDialogOpen(true);
                            setPaperFiles([]);
                          }}
                          className="text-blue-600 hover:text-blue-700"
                          data-testid="upload-more-btn"
                        >
                          <Upload className="w-4 h-4 mr-1" />
                          Upload More Papers
                        </Button>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={() => handleCloseExam(selectedExam)}
                          className="text-orange-600 hover:text-orange-700"
                          data-testid="close-exam-btn"
                        >
                          <Lock className="w-4 h-4 mr-1" />
                          Close Exam
                        </Button>
                      </>
                    )}
                    {selectedExam.status === "closed" && !editMode && (
                      <Button 
                        variant="outline" 
                        size="sm"
                        onClick={() => handleReopenExam(selectedExam)}
                        className="text-green-600 hover:text-green-700"
                        data-testid="reopen-exam-btn"
                      >
                        <LockOpen className="w-4 h-4 mr-1" />
                        Reopen Exam
                      </Button>
                    )}
                    {!editMode && (
                      <Button 
                        variant="outline" 
                        size="sm"
                        onClick={() => handleDelete(selectedExam)}
                        className="text-destructive hover:text-destructive"
                        data-testid="delete-exam-btn"
                      >
                        <Trash2 className="w-4 h-4 mr-1" />
                        Delete
                      </Button>
                    )}
                    {editMode && (
                      <>
                        <Button 
                          variant="default" 
                          size="sm"
                          onClick={handleSaveEdit}
                          disabled={savingEdit}
                          className="bg-green-600 hover:bg-green-700"
                        >
                          {savingEdit ? (
                            <RefreshCw className="w-4 h-4 mr-1 animate-spin" />
                          ) : (
                            <Save className="w-4 h-4 mr-1" />
                          )}
                          Save Changes
                        </Button>
                        <Button 
                          variant="outline" 
                          size="sm"
                          onClick={cancelEditMode}
                          disabled={savingEdit}
                        >
                          <X className="w-4 h-4 mr-1" />
                          Cancel
                        </Button>
                      </>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* Basic Info - View Mode */}
                  {!editMode ? (
                    <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
                      <div className="p-4 bg-blue-50 rounded-lg">
                        <div className="flex items-center gap-2 mb-1">
                          <BookOpen className="w-4 h-4 text-blue-600" />
                          <span className="text-xs text-blue-600">Batch</span>
                        </div>
                        <p className="font-medium text-sm">{getBatchName(selectedExam.batch_id)}</p>
                      </div>
                      
                      <div className="p-4 bg-orange-50 rounded-lg">
                        <div className="flex items-center gap-2 mb-1">
                          <FileText className="w-4 h-4 text-orange-600" />
                          <span className="text-xs text-orange-600">Subject</span>
                        </div>
                        <p className="font-medium text-sm">{getSubjectName(selectedExam.subject_id)}</p>
                      </div>

                      <div className="p-4 bg-indigo-50 rounded-lg">
                        <div className="flex items-center gap-2 mb-1">
                          <BookOpen className="w-4 h-4 text-indigo-600" />
                          <span className="text-xs text-indigo-600">UPSC Paper</span>
                        </div>
                        <p className="font-medium text-sm">{selectedExam.upsc_paper || "Not set"}</p>
                      </div>

                      <div className="p-4 bg-green-50 rounded-lg">
                        <div className="flex items-center gap-2 mb-1">
                          <CheckCircle className="w-4 h-4 text-green-600" />
                          <span className="text-xs text-green-600">Total Marks</span>
                        </div>
                        <p className="font-medium text-sm">{selectedExam.total_marks}</p>
                      </div>

                      <div className="p-4 bg-purple-50 rounded-lg">
                        <div className="flex items-center gap-2 mb-1">
                          <Calendar className="w-4 h-4 text-purple-600" />
                          <span className="text-xs text-purple-600">Exam Date</span>
                        </div>
                        <p className="font-medium text-sm">{selectedExam.exam_date}</p>
                      </div>
                    </div>
                  ) : (
                    /* Edit Mode Form */
                    <div className="p-4 border-2 border-blue-200 rounded-lg bg-blue-50/30 space-y-4">
                      <h3 className="font-semibold text-blue-700 flex items-center gap-2">
                        <Edit2 className="w-4 h-4" />
                        Edit Exam Details
                      </h3>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <Label htmlFor="exam_name">Exam Name</Label>
                          <Input
                            id="exam_name"
                            value={editForm.exam_name || ""}
                            onChange={(e) => setEditForm({...editForm, exam_name: e.target.value})}
                            placeholder="Enter exam name"
                          />
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="subject_id">Subject</Label>
                          <Select
                            value={editForm.subject_id || ""}
                            onValueChange={(val) => setEditForm({...editForm, subject_id: val})}
                          >
                            <SelectTrigger>
                              <SelectValue placeholder="Select subject" />
                            </SelectTrigger>
                            <SelectContent>
                              {subjects.map(s => (
                                <SelectItem key={s.subject_id} value={s.subject_id}>
                                  {s.subject_name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="total_marks">Total Marks</Label>
                          <Input
                            id="total_marks"
                            type="number"
                            value={editForm.total_marks || ""}
                            onChange={(e) => setEditForm({...editForm, total_marks: e.target.value})}
                            placeholder="Enter total marks"
                          />
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="grading_mode">Grading Mode</Label>
                          <Select
                            value={editForm.grading_mode || "balanced"}
                            onValueChange={(val) => setEditForm({...editForm, grading_mode: val})}
                          >
                            <SelectTrigger>
                              <SelectValue placeholder="Select grading mode" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="strict">🔴 Strict - Maximum rigor</SelectItem>
                              <SelectItem value="balanced">⚖️ Balanced - Fair & reasonable</SelectItem>
                              <SelectItem value="conceptual">🔵 Conceptual - Understanding focused</SelectItem>
                              <SelectItem value="lenient">🟢 Lenient - Reward effort</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="exam_type">Exam Type</Label>
                          <Select
                            value={editForm.exam_type || "unit_test"}
                            onValueChange={(val) => setEditForm({...editForm, exam_type: val})}
                          >
                            <SelectTrigger>
                              <SelectValue placeholder="Select exam type" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="unit_test">Unit Test</SelectItem>
                              <SelectItem value="mid_term">Mid Term</SelectItem>
                              <SelectItem value="final_exam">Final Exam</SelectItem>
                              <SelectItem value="quiz">Quiz</SelectItem>
                              <SelectItem value="assignment">Assignment</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="exam_date">Exam Date</Label>
                          <Input
                            id="exam_date"
                            type="date"
                            value={editForm.exam_date || ""}
                            onChange={(e) => setEditForm({...editForm, exam_date: e.target.value})}
                          />
                        </div>
                      </div>

                      <div className="p-3 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-700">
                        <strong>Note:</strong> Batch cannot be changed. If you update Total Marks or Grading Mode, 
                        consider using "Regrade All" to re-evaluate all submissions with the new settings.
                      </div>
                    </div>
                  )}

                  {/* Additional Details */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="p-4 border rounded-lg">
                      <p className="text-sm text-muted-foreground mb-1">Exam Type</p>
                      <p className="font-medium">{selectedExam.exam_type}</p>
                    </div>
                    <div className="p-4 border rounded-lg">
                      <p className="text-sm text-muted-foreground mb-1">Grading Mode</p>
                      <p className="font-medium capitalize">{selectedExam.grading_mode}</p>
                    </div>
                  </div>

                  {/* AI Tools Section */}
                  <div className="p-4 bg-purple-50 border border-purple-200 rounded-lg">
                    <h3 className="font-semibold mb-3 flex items-center gap-2 text-purple-800">
                      <Brain className="w-4 h-4" />
                      AI Tools & Documents
                    </h3>
                    
                    {/* Document Upload Section */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                      {/* Model Answer Upload */}
                      <div className="p-3 bg-white rounded-lg border border-purple-100">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-medium text-purple-700">Model Answer</span>
                          {(selectedExam.model_answer_images?.length > 0 || selectedExam.has_model_answer) && (
                            <Badge className="bg-green-100 text-green-700 text-xs">
                              <CheckCircle className="w-3 h-3 mr-1" />
                              Uploaded
                            </Badge>
                          )}
                        </div>
                        <label className="cursor-pointer">
                          <input
                            type="file"
                            accept=".pdf"
                            className="hidden"
                            onChange={handleUploadModelAnswer}
                            disabled={uploadingModelAnswer}
                          />
                          <div className={`flex items-center justify-center gap-2 p-2 border-2 border-dashed border-purple-200 rounded-lg hover:border-purple-400 hover:bg-purple-50 transition-colors ${uploadingModelAnswer ? 'opacity-50 cursor-wait' : ''}`}>
                            {uploadingModelAnswer ? (
                              <RefreshCw className="w-4 h-4 animate-spin text-purple-600" />
                            ) : (
                              <Upload className="w-4 h-4 text-purple-600" />
                            )}
                            <span className="text-xs text-purple-600">
                              {uploadingModelAnswer ? "Uploading..." : (selectedExam.model_answer_images?.length > 0 || selectedExam.has_model_answer) ? "Replace PDF" : "Upload PDF"}
                            </span>
                          </div>
                        </label>
                      </div>

                      {/* Question Paper Upload */}
                      <div className="p-3 bg-white rounded-lg border border-purple-100">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-medium text-purple-700">Question Paper</span>
                          {(selectedExam.question_paper_images?.length > 0 || selectedExam.has_question_paper) && (
                            <Badge className="bg-green-100 text-green-700 text-xs">
                              <CheckCircle className="w-3 h-3 mr-1" />
                              Uploaded
                            </Badge>
                          )}
                        </div>
                        <label className="cursor-pointer">
                          <input
                            type="file"
                            accept=".pdf"
                            className="hidden"
                            onChange={handleUploadQuestionPaper}
                            disabled={uploadingQuestionPaper}
                          />
                          <div className={`flex items-center justify-center gap-2 p-2 border-2 border-dashed border-purple-200 rounded-lg hover:border-purple-400 hover:bg-purple-50 transition-colors ${uploadingQuestionPaper ? 'opacity-50 cursor-wait' : ''}`}>
                            {uploadingQuestionPaper ? (
                              <RefreshCw className="w-4 h-4 animate-spin text-purple-600" />
                            ) : (
                              <Upload className="w-4 h-4 text-purple-600" />
                            )}
                            <span className="text-xs text-purple-600">
                              {uploadingQuestionPaper ? "Uploading..." : (selectedExam.question_paper_images?.length > 0 || selectedExam.has_question_paper) ? "Replace PDF" : "Upload PDF"}
                            </span>
                          </div>
                        </label>
                      </div>
                    </div>

                    {/* AI Action Buttons */}
                    <div className="flex flex-wrap gap-2">
                      {(selectedExam.model_answer_images?.length > 0 || selectedExam.has_model_answer || 
                        selectedExam.question_paper_images?.length > 0 || selectedExam.has_question_paper) && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleExtractQuestions(selectedExam)}
                          disabled={extractingQuestions}
                          className="text-purple-600 border-purple-200 hover:bg-purple-100"
                        >
                          {extractingQuestions ? (
                            <RefreshCw className="w-4 h-4 mr-1 animate-spin" />
                          ) : (
                            <Sparkles className="w-4 h-4 mr-1" />
                          )}
                          Extract Questions
                        </Button>
                      )}
                      {selectedExam.questions?.length > 0 && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleInferTopics(selectedExam)}
                          disabled={inferringTopics}
                          className="text-purple-600 border-purple-200 hover:bg-purple-100"
                        >
                          {inferringTopics ? (
                            <RefreshCw className="w-4 h-4 mr-1 animate-spin" />
                          ) : (
                            <Tag className="w-4 h-4 mr-1" />
                          )}
                          Auto-Infer Topic Tags
                        </Button>
                      )}
                    </div>
                    {!(selectedExam.model_answer_images?.length > 0 || selectedExam.has_model_answer || 
                       selectedExam.question_paper_images?.length > 0 || selectedExam.has_question_paper) && (
                      <p className="text-xs text-purple-600 mt-2">
                        Upload a model answer or question paper to enable AI features
                      </p>
                    )}
                  </div>

                  {/* Questions */}
                  <div>
                    <h3 className="font-semibold mb-3 flex items-center gap-2">
                      <FileText className="w-4 h-4" />
                      Questions ({selectedExam.questions?.length || 0})
                    </h3>
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {selectedExam.questions?.length === 0 ? (
                        <p className="text-sm text-muted-foreground text-center py-4">
                          No questions configured. Use &quot;Extract Questions&quot; if you have a model answer.
                        </p>
                      ) : (
                        selectedExam.questions?.map((question, idx) => (
                          <div key={idx} className="p-3 bg-muted/50 rounded-lg">
                            <div className="flex items-center justify-between mb-1">
                              <span className="font-medium text-sm">Question {question.question_number}</span>
                              <Badge variant="outline">{question.max_marks} marks</Badge>
                            </div>
                            {question.rubric && (
                              <p className="text-xs text-muted-foreground mb-2 line-clamp-1">
                                {(() => {
                                  let rubric = question.rubric;
                                  // Handle nested object structure (from new extraction)
                                  if (typeof rubric === 'object' && rubric !== null) {
                                    rubric = rubric.rubric || rubric.question_text || JSON.stringify(rubric);
                                  }
                                  return typeof rubric === 'string' ? rubric : String(rubric || '');
                                })()}
                              </p>
                            )}
                            {question.topic_tags?.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-2">
                                {question.topic_tags.map((tag, tagIdx) => (
                                  <Badge key={tagIdx} variant="secondary" className="text-xs bg-purple-100 text-purple-700">
                                    <Tag className="w-3 h-3 mr-1" />
                                    {tag}
                                  </Badge>
                                ))}
                              </div>
                            )}
                            {question.sub_questions?.length > 0 && (
                              <div className="mt-2 ml-4 space-y-1">
                                {question.sub_questions.map((sq, sqIdx) => (
                                  <div key={sqIdx} className="flex items-center justify-between text-xs">
                                    <span className="text-muted-foreground">Part {sq.sub_id}</span>
                                    <span className="text-muted-foreground">{sq.max_marks} marks</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* Stats */}
                  <div className="p-4 bg-yellow-50 rounded-lg">
                    <div className="flex items-center gap-2 mb-2">
                      <Users className="w-4 h-4 text-yellow-600" />
                      <span className="font-medium text-yellow-800">Submissions</span>
                    </div>
                    <p className="text-sm text-yellow-700">
                      {selectedExam.submission_count || 0} student papers graded
                    </p>
                  </div>

                  {/* Submitted Papers List */}
                  <div>
                    <h3 className="font-semibold mb-3 flex items-center gap-2">
                      <FileText className="w-4 h-4" />
                      Submitted Papers ({submissions.length})
                    </h3>
                    <div className="space-y-2 max-h-80 overflow-y-auto">
                      {loadingSubmissions ? (
                        <div className="space-y-2">
                          {[1, 2, 3].map(i => (
                            <div key={i} className="h-16 bg-muted animate-pulse rounded-lg" />
                          ))}
                        </div>
                      ) : submissions.length === 0 ? (
                        <p className="text-sm text-muted-foreground text-center py-8">
                          No papers submitted yet
                        </p>
                      ) : (
                        submissions.map((submission) => (
                          <div 
                            key={submission.submission_id}
                            className="p-3 bg-muted/50 rounded-lg flex items-center justify-between hover:bg-muted transition-colors"
                          >
                            <div className="flex items-center gap-3 flex-1 min-w-0">
                              <div className="w-10 h-10 rounded-full bg-orange-100 flex items-center justify-center flex-shrink-0">
                                <span className="text-sm font-medium text-orange-700">
                                  {submission.student_name?.charAt(0)?.toUpperCase() || "?"}
                                </span>
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="font-medium text-sm truncate">{submission.student_name}</p>
                                <p className="text-xs text-muted-foreground">
                                  Score: {submission.total_score}/{selectedExam.total_marks} • {submission.percentage}%
                                </p>
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              {submission.status === "ai_graded" ? (
                                <Badge variant="outline" className="text-xs bg-green-50 text-green-700 border-green-200">
                                  <CheckCircle className="w-3 h-3 mr-1" />
                                  Graded
                                </Badge>
                              ) : (
                                <Badge variant="outline" className="text-xs bg-blue-50 text-blue-700 border-blue-200">
                                  Reviewed
                                </Badge>
                              )}
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleDeleteSubmission(submission)}
                                className="text-red-600 hover:text-red-700 hover:bg-red-50 h-8 w-8 p-0"
                                title="Delete paper"
                              >
                                <Trash2 className="w-4 h-4" />
                              </Button>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* Warning */}
                  <div className="p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
                    <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium text-red-800 text-sm">Delete Warning</p>
                      <p className="text-sm text-red-700 mt-1">
                        Deleting this exam will permanently remove all submissions, grades, and re-evaluation requests. This action cannot be undone.
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>

      {/* Upload More Papers Dialog */}
      <Dialog open={uploadDialogOpen} onOpenChange={(open) => {
        if (!uploadingPapers) {
          setUploadDialogOpen(open);
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Additional Papers</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {!uploadingPapers ? (
              <>
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <p className="text-sm text-blue-800">
                    Upload additional student papers that were missed earlier. Papers will be auto-graded immediately.
                  </p>
                </div>
                <div 
                  {...getRootProps()} 
                  className={`dropzone p-8 text-center border-2 border-dashed rounded-xl ${isDragActive ? "border-primary bg-primary/5" : "border-gray-300"}`}
                >
                  <input {...getInputProps()} />
                  <Upload className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
                  <p className="font-medium">Drop student answer PDFs here</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Format: StudentID_StudentName.pdf
                  </p>
                </div>
                {paperFiles.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-sm font-medium">Selected Files ({paperFiles.length})</p>
                    <div className="max-h-32 overflow-y-auto space-y-1">
                      {paperFiles.map((file, idx) => (
                        <div key={idx} className="flex items-center gap-2 text-sm p-2 bg-muted rounded">
                          <FileText className="w-4 h-4" />
                          <span className="truncate">{file.name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="space-y-4">
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
                      <div className="flex-1">
                        <p className="text-sm font-medium text-blue-800">{uploadStatus}</p>
                        <p className="text-xs text-blue-600 mt-1">
                          This may take a few minutes depending on paper count...
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={handleCancelGrading}
                      className="h-8"
                    >
                      <X className="w-4 h-4 mr-1" />
                      Cancel
                    </Button>
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Progress</span>
                    <span className="font-medium">{uploadProgress}%</span>
                  </div>
                  <Progress value={uploadProgress} className="h-2" />
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            {!uploadingPapers ? (
              <>
                <Button variant="outline" onClick={() => setUploadDialogOpen(false)}>
                  Cancel
                </Button>
                <Button 
                  onClick={handleUploadMorePapers} 
                  disabled={paperFiles.length === 0 || uploadingPapers}
                  data-testid="upload-papers-btn"
                >
                  {uploadingPapers ? "Uploading..." : `Upload & Grade ${paperFiles.length} Papers`}
                </Button>
              </>
            ) : (
              <Button variant="outline" disabled>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Grading in Progress...
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Regrade Confirmation Dialog */}
      <Dialog open={regradeDialogOpen} onOpenChange={setRegradeDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <RotateCcw className="w-5 h-5 text-purple-600" />
              Regrade All Papers
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
              <p className="text-sm text-yellow-800">
                <strong>Warning:</strong> This will re-grade all {submissions.length} submitted papers using the current exam settings (grading mode, total marks, etc.).
              </p>
            </div>
            <p className="text-sm text-muted-foreground">
              This is useful when you've:
            </p>
            <ul className="text-sm text-muted-foreground list-disc list-inside space-y-1">
              <li>Changed the grading mode</li>
              <li>Updated the total marks</li>
              <li>Modified question configuration</li>
              <li>Updated the model answer</li>
            </ul>
            <p className="text-sm font-medium">
              Are you sure you want to proceed?
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRegradeDialogOpen(false)} disabled={regrading}>
              Cancel
            </Button>
            <Button 
              onClick={handleRegradeAll} 
              disabled={regrading}
              className="bg-purple-600 hover:bg-purple-700"
            >
              {regrading ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Regrading...
                </>
              ) : (
                <>
                  <RotateCcw className="w-4 h-4 mr-2" />
                  Yes, Regrade All
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Questions Dialog */}
      <Dialog open={editQuestionsDialogOpen} onOpenChange={setEditQuestionsDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>Edit Question Structure - {selectedExam?.exam_name}</DialogTitle>
            <CardDescription>
              Modify question numbers, marks, and sub-questions. Changes are validated automatically.
            </CardDescription>
          </DialogHeader>
          
          {/* Validation Messages */}
          {validationResult && (validationResult.errors.length > 0 || validationResult.warnings.length > 0) && (
            <div className="space-y-2 p-4 bg-gray-50 rounded-lg">
              {validationResult.errors.map((err, i) => (
                <div key={`err-${i}`} className="text-red-600 text-sm flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                  <span>{err}</span>
                </div>
              ))}
              {validationResult.warnings.map((warn, i) => (
                <div key={`warn-${i}`} className="text-yellow-600 text-sm flex items-center gap-2">
                  <AlertCircleIcon className="h-4 w-4 flex-shrink-0" />
                  <span>{warn}</span>
                </div>
              ))}
            </div>
          )}
          
          {/* Summary Stats */}
          <div className="flex items-center gap-4 p-3 bg-blue-50 rounded-lg">
            <div className="text-sm">
              <span className="font-medium">{validationResult?.questionCount || 0}</span> Questions
            </div>
            <div className="text-sm">
              <span className="font-medium">{validationResult?.totalMarks || 0}</span> Total Marks
            </div>
            <div className={`text-sm ${validationResult?.valid ? 'text-green-600' : 'text-red-600'}`}>
              {validationResult?.valid ? '✓ Valid' : '✗ Has Errors'}
            </div>
          </div>
          
          {/* Questions Editor - Scrollable */}
          <div className="flex-1 overflow-y-auto space-y-4 pr-2">
            {editingQuestions.map((q, qIdx) => (
              <QuestionEditor
                key={qIdx}
                question={q}
                onChange={(updated) => {
                  const newQuestions = [...editingQuestions];
                  newQuestions[qIdx] = updated;
                  setEditingQuestions(newQuestions);
                  validateQuestions(newQuestions);
                }}
                onRemove={() => {
                  const newQuestions = editingQuestions.filter((_, i) => i !== qIdx);
                  setEditingQuestions(newQuestions);
                  validateQuestions(newQuestions);
                }}
              />
            ))}
            
            <Button
              variant="outline"
              onClick={() => {
                const newQuestions = [
                  ...editingQuestions,
                  {
                    question_number: editingQuestions.length + 1,
                    max_marks: 10,
                    rubric: "",
                    question_text: "",
                    sub_questions: []
                  }
                ];
                setEditingQuestions(newQuestions);
                validateQuestions(newQuestions);
              }}
              className="w-full"
            >
              <Plus className="h-4 w-4 mr-2" />
              Add New Question
            </Button>
          </div>
          
          {/* Footer Actions */}
          <div className="flex justify-between items-center pt-4 border-t">
            <Button
              variant="outline"
              onClick={() => setEditQuestionsDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSaveQuestions}
              disabled={savingQuestions || (validationResult && validationResult.errors.length > 0)}
            >
              {savingQuestions ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  Save Changes
                </>
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Publish Results Settings Dialog */}
      <Dialog open={publishDialogOpen} onOpenChange={setPublishDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Publish Results - Configure Student Visibility</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <p className="text-sm text-muted-foreground">
              Choose what students can see when viewing their results:
            </p>
            
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div>
                  <Label className="font-medium">Show Question Paper</Label>
                  <p className="text-xs text-muted-foreground">Students can see the original questions</p>
                </div>
                <Checkbox 
                  checked={publishSettings.show_question_paper}
                  onCheckedChange={(checked) => 
                    setPublishSettings(prev => ({...prev, show_question_paper: checked}))
                  }
                />
              </div>

              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div>
                  <Label className="font-medium">Show Answer Sheet</Label>
                  <p className="text-xs text-muted-foreground">Students can see their submitted answer paper</p>
                </div>
                <Checkbox 
                  checked={publishSettings.show_answer_sheet}
                  onCheckedChange={(checked) => 
                    setPublishSettings(prev => ({...prev, show_answer_sheet: checked}))
                  }
                />
              </div>

              <div className="flex items-center justify-between p-3 border rounded-lg">
                <div>
                  <Label className="font-medium">Show Model Answer</Label>
                  <p className="text-xs text-muted-foreground">Students can see the correct model answer</p>
                </div>
                <Checkbox 
                  checked={publishSettings.show_model_answer}
                  onCheckedChange={(checked) => 
                    setPublishSettings(prev => ({...prev, show_model_answer: checked}))
                  }
                />
              </div>
            </div>

            <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm text-blue-800">
                <CheckCircle2 className="inline h-4 w-4 mr-1" />
                <strong>Note:</strong> Feedback and scores are always visible to students
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishDialogOpen(false)}>
              Cancel
            </Button>
            <Button 
              onClick={() => publishResults(selectedExam.exam_id)}
              className="bg-green-500 hover:bg-green-600"
            >
              <Eye className="w-4 h-4 mr-2" />
              Publish Results
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
