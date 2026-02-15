import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Badge } from "../../components/ui/badge";
import { Checkbox } from "../../components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { ScrollArea } from "../../components/ui/scroll-area";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../../components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../../components/ui/dialog";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { toast } from "sonner";
import { jsPDF } from "jspdf";
import VoiceInput from "../../components/VoiceInput";
import HandwrittenOverlay from "../../components/HandwrittenOverlay";
import { Skeleton } from "../../components/ui/skeleton";
import { 
  Search, 
  ChevronLeft, 
  ChevronRight, 
  Save, 
  CheckCircle,
  CheckCircle2,
  AlertCircle,
  FileText,
  RefreshCw,
  X,
  Eye,
  EyeOff,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Download,
  MessageSquarePlus,
  Send,
  Lightbulb,
  Sparkles,
  Brain,
  Trash2,
  Plus,
  PartyPopper
} from "lucide-react";

function AnnotationImage({
  imageBase64,
  pageIndex,
  annotations,
  onClick,
  showAnnotations,
  interactive = true
}) {
  const imgRef = useRef(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });

  return (
    <div
      className={interactive ? "relative cursor-pointer" : "relative"}
      onClick={interactive ? onClick : undefined}
    >
      <img
        ref={imgRef}
        src={`data:image/jpeg;base64,${imageBase64}`}
        alt={`Page ${pageIndex + 1}`}
        className="w-full rounded-lg shadow-md hover:shadow-lg transition-shadow"
        onLoad={() => {
          const img = imgRef.current;
          if (!img) return;
          setImageSize({
            width: img.naturalWidth || img.width,
            height: img.naturalHeight || img.height
          });
        }}
      />
      <HandwrittenOverlay
        annotations={annotations}
        width={imageSize.width}
        height={imageSize.height}
        show={showAnnotations}
      />
    </div>
  );
}

export default function ReviewPapers({ user }) {
  const [submissions, setSubmissions] = useState([]);
  const [exams, setExams] = useState([]);
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSubmission, setSelectedSubmission] = useState(null);
  const [filters, setFilters] = useState({
    exam_id: "",
    batch_id: "",
    search: ""
  });
  const [searchInput, setSearchInput] = useState(""); // Separate state for input
  const [saving, setSaving] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [showModelAnswer, setShowModelAnswer] = useState(true);
  const [showQuestionPaper, setShowQuestionPaper] = useState(true);
  const [showAnnotations, setShowAnnotations] = useState(true); // NEW: Toggle for annotated view
  const [modelAnswerImages, setModelAnswerImages] = useState([]);
  const [questionPaperImages, setQuestionPaperImages] = useState([]);
  const [examQuestions, setExamQuestions] = useState([]);
  const [zoomedImage, setZoomedImage] = useState(null);
  const [zoomedImages, setZoomedImages] = useState(null); // For multi-page continuous scrolling
  const [isModalOpen, setIsModalOpen] = useState(false); // Explicit open state for reliable modal control
  const [modalKey, setModalKey] = useState(0); // Forces Dialog remount to fix stale closure issue
  
  // Auto-publish dialog state
  const [autoPublishDialogOpen, setAutoPublishDialogOpen] = useState(false);
  const [publishSettings, setPublishSettings] = useState({
    show_model_answer: false,
    show_answer_sheet: true,
    show_question_paper: true
  });
  const [imageZoom, setImageZoom] = useState(120);
  const [feedbackDialogOpen, setFeedbackDialogOpen] = useState(false);
  const [feedbackQuestion, setFeedbackQuestion] = useState(null);
  const [feedbackCorrections, setFeedbackCorrections] = useState([
    {
      id: 1,
      selected_sub_question: "all",
      teacher_expected_grade: "",
      teacher_correction: ""
    }
  ]); // Array of corrections for multiple sub-questions
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const [applyToBatch, setApplyToBatch] = useState(false);
  const [applyToAllPapers, setApplyToAllPapers] = useState(false);
  const [extractingQuestions, setExtractingQuestions] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);

  const getDownloadImages = useCallback(() => {
    if (!selectedSubmission) return [];
    const baseImages = selectedSubmission.file_images?.length
      ? selectedSubmission.file_images
      : (selectedSubmission.annotated_images || []);
    if (showAnnotations && selectedSubmission.annotated_images?.length) {
      return selectedSubmission.annotated_images;
    }
    return baseImages;
  }, [selectedSubmission, showAnnotations]);

  const handleDownloadPdf = useCallback(async () => {
    const images = getDownloadImages();
    if (!images.length) {
      toast.error("No answer sheet images available to download.");
      return;
    }

    const doc = new jsPDF({ orientation: "portrait", unit: "px", format: "a4" });
    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const margin = 24;
    const maxW = pageWidth - margin * 2;
    const maxH = pageHeight - margin * 2;

    const loadImage = (src) => new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = src;
    });

    try {
      for (let i = 0; i < images.length; i += 1) {
        if (i > 0) doc.addPage();
        const dataUrl = `data:image/jpeg;base64,${images[i]}`;
        const img = await loadImage(dataUrl);
        const scale = Math.min(maxW / img.width, maxH / img.height);
        const drawW = img.width * scale;
        const drawH = img.height * scale;
        const x = (pageWidth - drawW) / 2;
        const y = (pageHeight - drawH) / 2;
        doc.addImage(dataUrl, "JPEG", x, y, drawW, drawH);
      }

      const safeName = (selectedSubmission?.student_name || "submission").replace(/[^a-z0-9_-]+/gi, "_");
      const fileName = `${safeName}-${selectedSubmission?.submission_id || "answers"}.pdf`;
      doc.save(fileName);
    } catch (error) {
      console.error("PDF download failed:", error);
      toast.error("Failed to generate PDF. Please try again.");
    }
  }, [getDownloadImages, selectedSubmission]);

  useEffect(() => {
    fetchData();
  }, []);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setFilters(prev => ({ ...prev, search: searchInput }));
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Debug: Monitor modal state changes
  useEffect(() => {
    console.log('🔄 isModalOpen changed to:', isModalOpen, '| modalKey:', modalKey);
  }, [isModalOpen, modalKey]);

  useEffect(() => {
    console.log('🔄 zoomedImages changed:', zoomedImages ? `${zoomedImages.images?.length} pages` : 'null');
  }, [zoomedImages]);

  const annotationsByPage = useMemo(() => {
    const map = {};
    if (!selectedSubmission?.question_scores) return map;
    const addAnn = (ann) => {
      if (!ann) return;
      const hasBox = Array.isArray(ann.box_2d) && ann.box_2d.length === 4;
      const hasPoint = (ann.x && ann.x > 0) || (ann.y && ann.y > 0);
      const hasPercent = ann.x_percent !== undefined || ann.y_percent !== undefined;
      const hasAnchors = ann.anchor_x !== undefined || ann.margin_x !== undefined;
      const hasBracket = ann.y_start_percent !== undefined || ann.y_end_percent !== undefined || ann.y_start !== undefined || ann.y_end !== undefined;
      if (!hasBox && !hasPoint && !hasPercent && !hasAnchors && !hasBracket) return;
      const page = ann.page_index ?? -1;
      if (page < 0) return;
      if (!map[page]) map[page] = [];
      map[page].push(ann);
    };
    selectedSubmission.question_scores.forEach((qs) => {
      (qs.annotations || []).forEach(addAnn);
      (qs.sub_scores || []).forEach((sub) => {
        (sub.annotations || []).forEach(addAnn);
      });
    });
    return map;
  }, [selectedSubmission]);

  const hasOverlayAnnotations = useMemo(
    () => Object.keys(annotationsByPage).length > 0,
    [annotationsByPage]
  );

  const fetchData = async () => {
    try {
      const [submissionsRes, examsRes, batchesRes] = await Promise.all([
        axios.get(`${API}/submissions`),
        axios.get(`${API}/exams`),
        axios.get(`${API}/batches`)
      ]);
      setSubmissions(submissionsRes.data);
      setExams(examsRes.data);
      setBatches(batchesRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchSubmissionDetails = useCallback(async (submissionId) => {
    // Open dialog immediately with loading skeleton
    setDetailLoading(true);
    setSelectedSubmission(null);
    setModelAnswerImages([]);
    setQuestionPaperImages([]);
    setExamQuestions([]);
    setDialogOpen(true);

    try {
      const response = await axios.get(`${API}/submissions/${submissionId}`);
      
      // CRITICAL FIX: Deduplicate question_scores by question_number
      // This prevents display bugs where questions appear multiple times
      if (response.data.question_scores && Array.isArray(response.data.question_scores)) {
        const uniqueScores = [];
        const seenQuestions = new Map();

        for (const qs of response.data.question_scores) {
          const existing = seenQuestions.get(qs.question_number);
          if (!existing) {
            seenQuestions.set(qs.question_number, qs);
            uniqueScores.push(qs);
          } else {
            // Merge annotations and sub-scores to preserve overlay data
            const mergedAnnotations = [
              ...(existing.annotations || []),
              ...(qs.annotations || [])
            ];
            existing.annotations = mergedAnnotations;

            if (qs.sub_scores?.length) {
              const subMap = new Map((existing.sub_scores || []).map((s) => [s.sub_id, s]));
              qs.sub_scores.forEach((sub) => {
                const existingSub = subMap.get(sub.sub_id);
                if (!existingSub) {
                  subMap.set(sub.sub_id, sub);
                } else {
                  existingSub.annotations = [
                    ...(existingSub.annotations || []),
                    ...(sub.annotations || [])
                  ];
                }
              });
              existing.sub_scores = Array.from(subMap.values());
            }
          }
        }

        response.data.question_scores = uniqueScores;
        
        // Recalculate total if deduplication occurred
        if (uniqueScores.length !== response.data.question_scores.length) {
          const newTotal = uniqueScores.reduce((sum, qs) => sum + (qs.obtained_marks || 0), 0);
          response.data.obtained_marks = newTotal;
          response.data.percentage = response.data.total_marks 
            ? Math.round((newTotal / response.data.total_marks) * 100) 
            : 0;
          console.warn(`Deduplicated ${response.data.question_scores.length - uniqueScores.length} duplicate questions`);
        }
      }
      
      setSelectedSubmission(response.data);
      
      // Fetch exam to get model answer, question paper and questions
      if (response.data.exam_id) {
        const examResponse = await axios.get(`${API}/exams/${response.data.exam_id}`);
        setModelAnswerImages(examResponse.data.model_answer_images || []);
        setQuestionPaperImages(examResponse.data.question_paper_images || []);
        setExamQuestions(examResponse.data.questions || []);
      }
    } catch (error) {
      toast.error("Failed to load submission details");
      setDialogOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // Check if all questions are reviewed
  const areAllQuestionsReviewed = () => {
    if (!selectedSubmission?.question_scores) return false;
    const allReviewed = selectedSubmission.question_scores.every(qs => qs.is_reviewed === true);
    return allReviewed;
  };

  // Get count of reviewed vs total questions
  const getReviewedCount = () => {
    if (!selectedSubmission?.question_scores) return { reviewed: 0, total: 0 };
    const reviewed = selectedSubmission.question_scores.filter(qs => qs.is_reviewed === true).length;
    const total = selectedSubmission.question_scores.length;
    return { reviewed, total };
  };

  // Check if all questions are graded and listed before showing final result
  const isGradingComplete = useMemo(() => {
    if (!selectedSubmission?.question_scores || selectedSubmission.question_scores.length === 0) return false;

    // If exam questions are known, ensure every question exists in scores
    if (examQuestions && examQuestions.length > 0) {
      const scoreNums = new Set(selectedSubmission.question_scores.map(qs => qs.question_number));
      const allPresent = examQuestions.every(q => scoreNums.has(q.question_number));
      if (!allPresent) return false;
    }

    // If any question is marked not_found, grading is incomplete
    const anyNotFound = selectedSubmission.question_scores.some(qs => qs.status === "not_found");
    if (anyNotFound) return false;

    return true;
  }, [selectedSubmission, examQuestions]);

  const handleSaveChanges = async () => {
    if (!selectedSubmission) return;
    
    // Check if all questions are reviewed
    const { reviewed, total } = getReviewedCount();
    if (reviewed < total) {
      toast.error(`Please review all questions first! (${reviewed}/${total} reviewed)`);
      return;
    }
    
    setSaving(true);
    try {
      await axios.put(`${API}/submissions/${selectedSubmission.submission_id}`, {
        question_scores: selectedSubmission.question_scores,
        obtained_marks: selectedSubmission.obtained_marks,
        total_marks: selectedSubmission.total_marks,
        percentage: selectedSubmission.percentage,
        teacher_edited: true,
        final_decision: "approved"
      });
      toast.success("Changes saved and approved!");
      
      // Refresh data from backend to get latest state
      await fetchData();
      
      // Check if this was the last paper to review (after data refresh)
      setTimeout(() => {
        checkAndShowPublishDialog();
      }, 300); // Small delay to ensure state is updated
      
    } catch (error) {
      toast.error("Failed to save changes");
    } finally {
      setSaving(false);
    }
  };

  const checkAndShowPublishDialog = () => {
    if (!filters.exam_id) return;
    
    // Check if popup already shown for this exam in this session
    const shownKey = `publish_popup_shown_${filters.exam_id}`;
    if (sessionStorage.getItem(shownKey)) {
      return; // Already shown in this session
    }
    
    // Get all submissions for this exam
    const examSubmissions = submissions.filter(s => s.exam_id === filters.exam_id);
    
    // Check if all papers are reviewed (have teacher_edited or final_decision)
    const allReviewed = examSubmissions.every(s => 
      s.teacher_edited === true || s.final_decision === "approved"
    );
    
    console.log('Auto-publish check:', {
      exam_id: filters.exam_id,
      totalSubmissions: examSubmissions.length,
      allReviewed,
      shownBefore: !!sessionStorage.getItem(shownKey)
    });
    
    if (allReviewed && examSubmissions.length > 0) {
      // Check if already published
      const exam = exams.find(e => e.exam_id === filters.exam_id);
      if (exam && !exam.results_published) {
        // Mark as shown for this session BEFORE showing dialog
        sessionStorage.setItem(shownKey, 'true');
        
        // Show auto-publish dialog
        setTimeout(() => {
          setAutoPublishDialogOpen(true);
        }, 500); // Small delay for better UX
      } else {
        console.log('Not showing publish dialog - exam already published or not found');
      }
    } else {
      console.log('Not all papers reviewed yet');
    }
  };

  const handlePublishFromDialog = async () => {
    if (!filters.exam_id) return;
    
    try {
      await axios.post(`${API}/exams/${filters.exam_id}/publish-results`, publishSettings, {
        withCredentials: true
      });
      toast.success("🎉 Results published! Students can now see their scores.");
      setAutoPublishDialogOpen(false);
      await fetchData(); // Refresh to update published status
    } catch (error) {
      console.error("Publish error:", error);
      toast.error("Failed to publish results");
    }
  };

  const updateQuestionScore = (index, field, value) => {
    setSelectedSubmission(prev => {
      const newScores = [...prev.question_scores];
      newScores[index] = { ...newScores[index], [field]: value };
      
      // Recalculate obtained_marks from sub_scores if they exist
      if (newScores[index].sub_scores?.length > 0) {
        newScores[index].obtained_marks = newScores[index].sub_scores.reduce(
          (sum, ss) => sum + (ss.obtained_marks || 0), 0
        );
      }
      
      const totalScore = newScores.reduce((sum, qs) => sum + qs.obtained_marks, 0);
      const exam = exams.find(e => e.exam_id === prev.exam_id);
      const totalMarks = exam?.total_marks || newScores.reduce((sum, q) => sum + q.max_marks, 0) || 100;
      
      return {
        ...prev,
        question_scores: newScores,
        obtained_marks: totalScore,
        total_score: totalScore,  // Keep for backward compatibility
        total_marks: totalMarks,
        percentage: Math.round((totalScore / totalMarks) * 100 * 100) / 100
      };
    });
  };

  // Function to update sub-question scores
  const updateSubQuestionScore = (questionIndex, subIndex, field, value) => {
    setSelectedSubmission(prev => {
      const newScores = [...prev.question_scores];
      const newSubScores = [...(newScores[questionIndex].sub_scores || [])];
      newSubScores[subIndex] = { ...newSubScores[subIndex], [field]: value };
      
      // Recalculate parent question's obtained_marks from sub_scores
      const totalSubMarks = newSubScores.reduce((sum, ss) => sum + (ss.obtained_marks || 0), 0);
      newScores[questionIndex] = { 
        ...newScores[questionIndex], 
        sub_scores: newSubScores,
        obtained_marks: totalSubMarks
      };
      
      const totalScore = newScores.reduce((sum, qs) => sum + qs.obtained_marks, 0);
      const exam = exams.find(e => e.exam_id === prev.exam_id);
      const totalMarks = exam?.total_marks || newScores.reduce((sum, q) => sum + q.max_marks, 0) || 100;
      
      return {
        ...prev,
        question_scores: newScores,
        obtained_marks: totalScore,
        total_score: totalScore,  // Keep for backward compatibility
        total_marks: totalMarks,
        percentage: Math.round((totalScore / totalMarks) * 100 * 100) / 100
      };
    });
  };

  const filteredSubmissions = useMemo(() => {
    return submissions.filter(s => {
      // Filter by batch
      if (filters.batch_id) {
        const exam = exams.find(e => e.exam_id === s.exam_id);
        if (!exam || exam.batch_id !== filters.batch_id) return false;
      }
      // Filter by exam
      if (filters.exam_id && s.exam_id !== filters.exam_id) return false;
      // Filter by search
      if (filters.search && !s.student_name.toLowerCase().includes(filters.search.toLowerCase())) return false;
      return true;
    });
  }, [submissions, filters, exams]);

  const handleBulkApprove = async () => {
    if (!filters.exam_id) {
      toast.error("Please select an exam first");
      return;
    }

    const unreviewedCount = filteredSubmissions.filter(s => s.status !== "teacher_reviewed").length;
    
    if (unreviewedCount === 0) {
      toast.info("All papers are already reviewed");
      return;
    }

    if (!confirm(`Mark ${unreviewedCount} unreviewed papers as approved?\n\nThis will:\n- Mark all papers as "teacher_reviewed"\n- Keep existing scores and feedback\n- Skip papers already reviewed`)) {
      return;
    }

    try {
      const response = await axios.post(`${API}/exams/${filters.exam_id}/bulk-approve`);
      toast.success(response.data.message || "Papers approved successfully");
      await fetchData(); // Refresh all data
      
      // Check if all papers are now reviewed and show publish dialog
      setTimeout(() => {
        checkAndShowPublishDialog();
      }, 300); // Small delay to ensure state is updated
    } catch (error) {
      console.error("Bulk approve error:", error);
      const errorMessage = error.response?.data?.detail || error.message || "Failed to bulk approve";
      toast.error(errorMessage);
    }
  };

  const currentIndex = selectedSubmission 
    ? filteredSubmissions.findIndex(s => s.submission_id === selectedSubmission.submission_id)
    : -1;

  const handleUnapprove = async () => {
    if (!selectedSubmission) return;
    
    try {
      await axios.put(`${API}/submissions/${selectedSubmission.submission_id}/unapprove`);
      toast.success("Submission reverted to pending review");
      
      // Refresh data
      await fetchData();
      
      // Update current submission
      setSelectedSubmission(prev => ({
        ...prev,
        status: "pending_review",
        is_reviewed: false
      }));
    } catch (error) {
      console.error("Unapprove error:", error);
      toast.error(error.response?.data?.detail || "Failed to unapprove");
    }
  };

  const navigatePaper = (direction) => {
    const newIndex = currentIndex + direction;
    if (newIndex >= 0 && newIndex < filteredSubmissions.length) {
      fetchSubmissionDetails(filteredSubmissions[newIndex].submission_id);
    }
  };

  const openFeedbackDialog = (questionScore) => {
    setFeedbackQuestion(questionScore);
    setFeedbackCorrections([
      {
        id: 1,
        selected_sub_question: "all",
        teacher_expected_grade: questionScore.obtained_marks.toString(),
        teacher_correction: ""
      }
    ]);
    setApplyToAllPapers(false);
    setFeedbackDialogOpen(true);
  };

  const addNewCorrection = () => {
    const newId = Math.max(...feedbackCorrections.map(c => c.id)) + 1;
    setFeedbackCorrections([...feedbackCorrections, {
      id: newId,
      selected_sub_question: "all",
      teacher_expected_grade: "",
      teacher_correction: ""
    }]);
  };

  const removeCorrection = (id) => {
    if (feedbackCorrections.length > 1) {
      setFeedbackCorrections(feedbackCorrections.filter(c => c.id !== id));
    }
  };

  const updateCorrection = (id, field, value) => {
    setFeedbackCorrections(feedbackCorrections.map(correction => 
      correction.id === id ? { ...correction, [field]: value } : correction
    ));
  };

  const handleSubmitFeedback = async () => {
    // Validate: at least one correction must have feedback
    const validCorrections = feedbackCorrections.filter(c => c.teacher_correction.trim());
    
    if (!feedbackQuestion || validCorrections.length === 0) {
      toast.error("Please provide feedback for at least one part");
      return;
    }

    setSubmittingFeedback(true);
    try {
      // Submit all corrections
      const feedbackIds = [];
      
      for (const correction of validCorrections) {
        const response = await axios.post(`${API}/feedback/submit`, {
          submission_id: selectedSubmission?.submission_id,
          exam_id: selectedSubmission?.exam_id,
          question_number: feedbackQuestion.question_number,
          sub_question_id: correction.selected_sub_question !== "all" ? correction.selected_sub_question : null,
          feedback_type: "question_grading",
          question_text: feedbackQuestion.question_text || "",
          ai_grade: feedbackQuestion.obtained_marks,
          ai_feedback: feedbackQuestion.ai_feedback,
          teacher_expected_grade: parseFloat(correction.teacher_expected_grade) || 0,
          teacher_correction: correction.teacher_correction,
          apply_to_all_papers: false // Will handle bulk after all submissions
        });
        
        if (response.data.feedback_id) {
          feedbackIds.push({
            feedback_id: response.data.feedback_id,
            sub_question_id: correction.selected_sub_question
          });
        }
      }
      
      // If "Apply to All Papers" is checked, trigger bulk update with all feedback IDs
      if (applyToAllPapers && feedbackIds.length > 0) {
        toast.info(`🤖 AI is intelligently re-grading all papers for ${validCorrections.length} part(s)...`, { duration: 5000 });
        try {
          const bulkResponse = await axios.post(
            `${API}/feedback/apply-multiple-to-all-papers`,
            { feedback_ids: feedbackIds.map(f => f.feedback_id) },
            { timeout: 300000 } // 5 minutes
          );
          const { updated_count, failed_count } = bulkResponse.data;
          
          if (failed_count > 0) {
            toast.warning(`✓ Re-graded ${updated_count} papers. ${failed_count} failed to process.`);
          } else {
            toast.success(`✓ Successfully re-graded all ${updated_count} papers with AI for ${validCorrections.length} part(s)!`);
          }
          
          fetchData();
        } catch (bulkError) {
          console.error("Bulk update error:", bulkError);
          if (bulkError.code === 'ECONNABORTED') {
            toast.error("Re-grading is taking longer than expected. Please check back in a few minutes.");
          } else {
            toast.error("Failed to apply to all papers. Feedback saved but bulk update failed.");
          }
        }
      } else {
        toast.success(`Feedback submitted successfully for ${validCorrections.length} part(s)!`);
      }
      
      setFeedbackDialogOpen(false);
      setFeedbackQuestion(null);
      setFeedbackCorrections([{
        id: 1,
        selected_sub_question: "all",
        teacher_expected_grade: "",
        teacher_correction: ""
      }]);
      setApplyToBatch(false);
      setApplyToAllPapers(false);
    } catch (error) {
      toast.error("Failed to submit feedback: " + (error.response?.data?.detail || error.message));
    } finally {
      setSubmittingFeedback(false);
    }
  };

  const handleExtractQuestions = async () => {
    // Use selectedSubmission.exam_id when viewing a paper, otherwise use filters.exam_id
    const examId = selectedSubmission?.exam_id || filters.exam_id;
    
    if (!examId) {
      toast.error("Please select an exam first");
      return;
    }

    const selectedExam = exams.find(e => e.exam_id === examId);
    if (!selectedExam) {
      toast.error("Exam not found");
      return;
    }

    // Check for documents - either in old storage (images array) or new storage (has_* flags)
    const hasModelAnswer = selectedExam.model_answer_images?.length > 0 || selectedExam.has_model_answer;
    const hasQuestionPaper = selectedExam.question_paper_images?.length > 0 || selectedExam.has_question_paper;
    
    if (!hasModelAnswer && !hasQuestionPaper) {
      toast.error("No model answer or question paper found. Upload one first in Manage Exams.");
      return;
    }

    setExtractingQuestions(true);
    try {
      const response = await axios.post(`${API}/exams/${examId}/extract-questions`);
      toast.success(`Successfully extracted ${response.data.updated_count || 0} questions from ${response.data.source || 'document'}`);
      
      // Refresh exams to get updated questions
      const examsRes = await axios.get(`${API}/exams`);
      setExams(examsRes.data);
      
      // If we have a selected submission, refresh its exam questions
      if (selectedSubmission) {
        const examResponse = await axios.get(`${API}/exams/${selectedSubmission.exam_id}`);
        setExamQuestions(examResponse.data.questions || []);
      }
    } catch (error) {
      console.error("Extract questions error:", error);
      toast.error(error.response?.data?.detail || "Failed to extract questions");
    } finally {
      setExtractingQuestions(false);
    }
  };

  // DetailContent renderer (no useMemo to avoid hook dependency warnings)
  const renderDetailContent = () => {
    if (!selectedSubmission) {
      if (detailLoading) {
        return (
          <>
            {/* Skeleton Header */}
            <div className="p-4 md:p-5 border-b bg-muted/50">
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
                <div className="min-w-0 flex-1 space-y-3">
                  <Skeleton className="h-7 w-56" />
                  <Skeleton className="h-4 w-40" />
                </div>
                <div className="flex items-center gap-3">
                  <Skeleton className="h-7 w-24 rounded-full" />
                  <Skeleton className="h-9 w-28 rounded-md" />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <Skeleton className="h-9 w-28" />
                <Skeleton className="h-5 w-36" />
                <Skeleton className="h-9 w-28" />
              </div>
            </div>
            {/* Skeleton Body */}
            <div className="flex-1 overflow-hidden flex">
              {/* Left panel - image area */}
              <div className="flex-1 p-5 flex flex-col items-center justify-center gap-4">
                <Skeleton className="w-[90%] max-w-2xl h-[55vh] rounded-xl" />
                <div className="flex gap-2 mt-2">
                  <Skeleton className="h-3 w-3 rounded-full" />
                  <Skeleton className="h-3 w-3 rounded-full" />
                  <Skeleton className="h-3 w-3 rounded-full" />
                </div>
                <p className="text-sm text-muted-foreground animate-pulse mt-1">Loading submission...</p>
              </div>
              {/* Right panel - score cards */}
              <div className="w-80 border-l bg-muted/30 p-4 space-y-4">
                <Skeleton className="h-6 w-40 mb-4" />
                {[1, 2, 3, 4, 5].map(i => (
                  <div key={i} className="space-y-2.5 p-4 border rounded-xl bg-background">
                    <div className="flex justify-between items-center">
                      <Skeleton className="h-5 w-28" />
                      <Skeleton className="h-5 w-16 rounded-full" />
                    </div>
                    <Skeleton className="h-3 w-full" />
                    <Skeleton className="h-3 w-5/6" />
                    <Skeleton className="h-3 w-2/3" />
                  </div>
                ))}
              </div>
            </div>
          </>
        );
      }
      return null;
    }

    return (
    <>
      {/* Header */}
      <div className="p-3 md:p-4 border-b bg-gradient-to-r from-primary/5 to-transparent">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-3">
          <div className="min-w-0 flex-1">
            <h3 className="text-lg md:text-xl font-semibold truncate">{selectedSubmission.student_name}</h3>
            <p className="text-xs md:text-sm text-muted-foreground">
              {isGradingComplete ? (
                <>Score: {(selectedSubmission.obtained_marks || selectedSubmission.total_score || 0).toFixed(1)} / {selectedSubmission.total_marks || exams.find(e => e.exam_id === selectedSubmission.exam_id)?.total_marks || "?"} ({(selectedSubmission.percentage || 0).toFixed(1)}%)</>
              ) : (
                <>Score: Pending (all questions must be graded)</>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge 
              className={
                selectedSubmission.status === "teacher_reviewed" 
                  ? "bg-green-100 text-green-700" 
                  : "bg-yellow-100 text-yellow-700"
              }
            >
              {selectedSubmission.status === "teacher_reviewed" ? "Reviewed" : "AI Graded"}
            </Badge>
            {selectedSubmission.status === "teacher_reviewed" && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleUnapprove}
                className="text-orange-600 border-orange-300 hover:bg-orange-50"
              >
                <RefreshCw className="w-3 h-3 mr-1" />
                Unapprove
              </Button>
            )}
            {modelAnswerImages.length > 0 && (
              <Button
                variant={showModelAnswer ? "default" : "outline"}
                size="sm"
                onClick={() => setShowModelAnswer(!showModelAnswer)}
              >
                <FileText className="w-3 h-3 md:w-4 md:h-4 mr-1" />
                <span className="hidden sm:inline">{showModelAnswer ? "Hide" : "Show"} Model</span>
                <span className="sm:hidden">Model</span>
              </Button>
            )}
          </div>
        </div>
        
        {/* Navigation */}
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigatePaper(-1)}
            disabled={currentIndex === 0}
          >
            <ChevronLeft className="w-4 h-4 mr-1" />
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            {currentIndex + 1} of {filteredSubmissions.length}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigatePaper(1)}
            disabled={currentIndex === filteredSubmissions.length - 1}
          >
            Next
            <ChevronRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </div>

      {/* Content - Resizable Panels for Desktop */}
      <div className="flex-1 overflow-hidden flex flex-col lg:hidden">
        {/* Mobile: Stack vertically without resize */}
        <div className="h-48 border-b overflow-auto bg-muted/30 p-2">
          {selectedSubmission.file_images?.length > 0 ? (
            <div className="space-y-3">
              {/* Toggle Controls */}
              <div className="flex items-center justify-between sticky top-0 bg-muted/30 py-2 z-10 gap-2 flex-wrap">
                <span className="text-sm font-medium">Answer Sheet</span>
                <div className="flex items-center gap-3">
                  {/* Annotations Toggle - NEW */}
                  {selectedSubmission.annotated_images?.length > 0 && (
                    <div className="flex items-center gap-2">
                      <Checkbox 
                        id="show-annotations-mobile"
                        checked={showAnnotations}
                        onCheckedChange={setShowAnnotations}
                      />
                      <Label htmlFor="show-annotations-mobile" className="text-xs cursor-pointer flex items-center gap-1">
                        <Sparkles className="w-3 h-3" />
                        Annotations
                      </Label>
                    </div>
                  )}
                  {/* Model Answer Toggle */}
                  {modelAnswerImages.length > 0 && (
                    <div className="flex items-center gap-2">
                      <Checkbox 
                        id="show-model-answer-mobile"
                        checked={showModelAnswer}
                        onCheckedChange={setShowModelAnswer}
                      />
                      <Label htmlFor="show-model-answer-mobile" className="text-xs cursor-pointer flex items-center gap-1">
                        <FileText className="w-3 h-3" />
                        Model
                      </Label>
                    </div>
                  )}
                  
                </div>
              </div>
              
              {/* Answer Sheets */}
              <div className="space-y-4">
                {/* Show annotated images if available and toggle is on */}
                {(() => {
                  const baseImages = (selectedSubmission.file_images?.length
                    ? selectedSubmission.file_images
                    : (selectedSubmission.annotated_images || []));
                  const useOverlay = showAnnotations && hasOverlayAnnotations;
                  const displayImages = baseImages;

                  return displayImages.map((img, idx) => (
                    <div key={idx} className="relative">
                      <AnnotationImage
                        imageBase64={img}
                        pageIndex={idx}
                        annotations={annotationsByPage[idx] || []}
                        showAnnotations={useOverlay}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setImageZoom(120);
                          setZoomedImage({
                            imageBase64: img,
                            title: `Page ${idx + 1}`,
                            pageIndex: idx,
                            annotations: annotationsByPage[idx] || [],
                            useOverlay
                          });
                        }}
                      />
                      {showAnnotations && (useOverlay || selectedSubmission.annotated_images?.length > 0) && (
                        <Badge className="absolute top-2 right-2 bg-green-500 text-white">
                          With Annotations
                        </Badge>
                      )}
                    </div>
                  ));
                })()}
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center">
              <p className="text-muted-foreground text-sm">No preview available</p>
            </div>
          )}
        </div>
        
        {/* Mobile: Questions Section */}
        <ScrollArea className="flex-1">
          <div className="p-4 space-y-3">
            {selectedSubmission.question_scores?.map((qs, index) => {
              const hasSubQuestions = qs.sub_scores && qs.sub_scores.length > 0;
              const examQuestion = examQuestions.find(q => q.question_number === qs.question_number);
              
              return (
              <div 
                key={index}
                className={`p-3 rounded-lg border question-card ${qs.is_reviewed ? "reviewed" : ""}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-semibold text-sm">Question {qs.question_number}</h4>
                  <div className="flex items-center gap-1">
                    {hasSubQuestions ? (
                      <span className="text-sm font-medium text-orange-600">{qs.obtained_marks}</span>
                    ) : (
                      <Input 
                        type="number"
                        value={qs.obtained_marks}
                        onChange={(e) => updateQuestionScore(index, "obtained_marks", parseFloat(e.target.value) || 0)}
                        className="w-16 text-center text-sm"
                      />
                    )}
                    <span className="text-muted-foreground text-sm">/ {qs.max_marks}</span>
                  </div>
                </div>

                {qs.question_text && (
                  <div className="mb-3 p-2 bg-muted/50 rounded border-l-2 border-primary">
                    <p className="text-xs text-foreground whitespace-pre-wrap">
                      <strong>Q{qs.question_number}.</strong> {(() => {
                        let text = qs.question_text;
                        // Handle nested object structure
                        if (typeof text === 'object' && text !== null) {
                          text = text.rubric || text.question_text || JSON.stringify(text);
                        }
                        return typeof text === 'string' ? text : String(text || '');
                      })()}
                    </p>
                  </div>
                )}

                {/* Sub-Questions Section for Mobile */}
                {hasSubQuestions ? (
                  <div className="space-y-3 mt-3">
                    {qs.sub_scores.map((subScore, subIndex) => {
                      const examSubQuestion = examQuestion?.sub_questions?.find(sq => sq.sub_id === subScore.sub_id);
                      let subQuestionText = examSubQuestion?.rubric || examSubQuestion?.question_text || "";
                      
                      // CRITICAL FIX: Handle nested sub-question objects
                      if (typeof subQuestionText === 'object' && subQuestionText !== null) {
                        subQuestionText = subQuestionText.rubric || subQuestionText.question_text || JSON.stringify(subQuestionText);
                      }
                      
                      // Ensure it's a string
                      const subQuestionTextString = typeof subQuestionText === 'string' ? subQuestionText : String(subQuestionText || '');
                      
                      return (
                        <div 
                          key={subScore.sub_id}
                          className="ml-2 p-2 bg-gradient-to-r from-orange-50 to-amber-50/30 rounded border border-orange-200"
                        >
                          {/* Sub-question Header with Score */}
                          <div className="flex items-center justify-between mb-2">
                            <span className="font-semibold text-xs text-orange-700">
                              Part {subScore.sub_id}
                            </span>
                            <div className="flex items-center gap-1">
                              <Input 
                                type="number"
                                value={subScore.obtained_marks}
                                onChange={(e) => updateSubQuestionScore(index, subIndex, "obtained_marks", parseFloat(e.target.value) || 0)}
                                className="w-12 text-center text-xs"
                                step="0.5"
                              />
                              <span className="text-muted-foreground text-xs">/ {subScore.max_marks}</span>
                            </div>
                          </div>
                          
                          {/* Sub-question Text */}
                          {subQuestionTextString && (
                            <div className="mb-2 p-1.5 bg-white/80 rounded border-l-2 border-orange-400">
                              <p className="text-xs text-gray-700">
                                <strong className="text-orange-600">{subScore.sub_id})</strong> {subQuestionTextString}
                              </p>
                            </div>
                          )}
                          
                          {/* Sub-question AI Feedback */}
                          <div>
                            <Label className="text-xs text-muted-foreground">Feedback</Label>
                            <Textarea 
                              value={subScore.ai_feedback || ""}
                              onChange={(e) => updateSubQuestionScore(index, subIndex, "ai_feedback", e.target.value)}
                              className="mt-1 text-xs"
                              rows={2}
                            />
                          </div>
                        </div>
                      );
                    })}
                    
                    {/* Overall feedback AFTER all sub-questions */}
                    <div className="ml-2 mt-3 p-2 bg-blue-50 rounded border border-blue-200">
                      <Label className="text-xs font-medium text-blue-700">Overall Feedback for Q{qs.question_number}</Label>
                      <Textarea 
                        value={qs.ai_feedback || ""}
                        onChange={(e) => updateQuestionScore(index, "ai_feedback", e.target.value)}
                        className="mt-1 text-xs"
                        rows={2}
                        placeholder="Overall feedback..."
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div>
                      <Label className="text-xs text-muted-foreground">AI Feedback</Label>
                      <Textarea 
                        value={qs.ai_feedback}
                        onChange={(e) => updateQuestionScore(index, "ai_feedback", e.target.value)}
                        className="mt-1 text-xs"
                        rows={2}
                      />
                    </div>
                  </div>
                )}

                {/* Teacher Comment - always shown */}
                <div className="mt-2">
                  <Label className="text-xs text-muted-foreground">Teacher Comment</Label>
                  <Textarea 
                    value={qs.teacher_comment || ""}
                    onChange={(e) => updateQuestionScore(index, "teacher_comment", e.target.value)}
                    placeholder="Add your comments..."
                    className="mt-1 text-xs"
                    rows={2}
                  />
                </div>

                {/* Rubric / Evaluator Preference */}
                <div className="mt-2">
                  <Label className="text-xs text-muted-foreground">Rubric / Evaluator Preference</Label>
                  <Textarea 
                    value={qs.rubric_preference || ""}
                    onChange={(e) => updateQuestionScore(index, "rubric_preference", e.target.value)}
                    placeholder="Add rubric notes or evaluator preferences..."
                    className="mt-1 text-xs"
                    rows={2}
                  />
                </div>

                <div className="flex items-center justify-between gap-2 flex-wrap mt-2">
                  <div className="flex items-center gap-2">
                    <Checkbox 
                      id={`reviewed-mobile-${index}`}
                      checked={qs.is_reviewed}
                      onCheckedChange={(checked) => updateQuestionScore(index, "is_reviewed", checked)}
                    />
                    <Label htmlFor={`reviewed-mobile-${index}`} className="text-xs cursor-pointer">
                      Mark as reviewed
                    </Label>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => openFeedbackDialog(qs)}
                    className="text-xs text-orange-600 hover:text-orange-700 hover:bg-orange-50"
                  >
                    <MessageSquarePlus className="w-3 h-3 mr-1" />
                    Improve AI
                  </Button>
                </div>
              </div>
            );})}
          </div>
        </ScrollArea>
      </div>

      {/* Desktop: Resizable Panels */}
      <div className="hidden lg:flex flex-1 overflow-hidden" style={{ height: 'calc(100% - 60px)' }}>
        <PanelGroup direction="horizontal" className="h-full">
          {/* Left Panel - Answer Sheets */}
          <Panel defaultSize={55} minSize={30} maxSize={70} collapsible={false} className="h-full">
            <div className="h-full overflow-auto bg-muted/30 p-4">
              {selectedSubmission.file_images?.length > 0 ? (
                <div className="space-y-3">
                  {/* Toggle Controls */}
                  <div className="flex items-center justify-between sticky top-0 bg-muted/30 py-2 z-10 gap-2 flex-wrap">
                    <span className="text-sm font-medium">Answer Sheet</span>
                    <div className="flex items-center gap-3">
                      {/* Question Paper Toggle */}
                      {questionPaperImages.length > 0 && (
                        <div className="flex items-center gap-2">
                          <Checkbox 
                            id="show-question-paper"
                            checked={showQuestionPaper}
                            onCheckedChange={setShowQuestionPaper}
                          />
                          <Label htmlFor="show-question-paper" className="text-xs cursor-pointer flex items-center gap-1">
                            <FileText className="w-3 h-3 text-blue-600" />
                            Questions
                          </Label>
                        </div>
                      )}
                      
                      {/* Annotations Toggle - NEW */}
                      {selectedSubmission.annotated_images?.length > 0 && (
                        <div className="flex items-center gap-2">
                          <Checkbox 
                            id="show-annotations-desktop"
                            checked={showAnnotations}
                            onCheckedChange={setShowAnnotations}
                          />
                          <Label htmlFor="show-annotations-desktop" className="text-xs cursor-pointer flex items-center gap-1">
                            <Sparkles className="w-3 h-3 text-green-600" />
                            Annotations
                          </Label>
                        </div>
                      )}
                      
                      {/* Model Answer Toggle */}
                      {modelAnswerImages.length > 0 && (
                        <div className="flex items-center gap-2">
                          <Checkbox 
                            id="show-model-answer"
                            checked={showModelAnswer}
                            onCheckedChange={setShowModelAnswer}
                          />
                          <Label htmlFor="show-model-answer" className="text-xs cursor-pointer flex items-center gap-1">
                            <FileText className="w-3 h-3" />
                            Model Answer
                          </Label>
                        </div>
                      )}
                      
                    </div>
                  </div>
                  
                  {/* Answer Sheets Display */}
                  <div className={showModelAnswer ? "grid grid-cols-2 gap-4" : ""}>
                    {/* Student Answer */}
                    <div className="space-y-2">
                      {showModelAnswer && (
                        <h3 className="text-xs font-semibold text-blue-700 sticky top-0 bg-muted/30 py-1">Student&apos;s Answer</h3>
                      )}
                      <div className="space-y-4">
                        {(() => {
                          const baseImages = (selectedSubmission.file_images?.length
                            ? selectedSubmission.file_images
                            : (selectedSubmission.annotated_images || []));
                          const useOverlay = showAnnotations && hasOverlayAnnotations && !(selectedSubmission.annotated_images?.length > 0);
                          const displayImages = useOverlay
                            ? baseImages
                            : (showAnnotations && selectedSubmission.annotated_images?.length > 0
                                ? selectedSubmission.annotated_images
                                : baseImages);

                          return displayImages.map((img, idx) => (
                            <div key={idx} className="relative group">
                              <AnnotationImage
                                imageBase64={img}
                                pageIndex={idx}
                                annotations={annotationsByPage[idx] || []}
                                showAnnotations={useOverlay}
                                onClick={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  const allImages = displayImages.map((image, index) => ({
                                    imageBase64: image,
                                    title: `Page ${index + 1}`
                                  }));
                                  // Update key first to force Dialog remount, then set state
                                  setModalKey(prev => prev + 1);
                                  setImageZoom(120);
                                  setZoomedImages({ 
                                    images: allImages, 
                                    title: "Student Answer", 
                                    initialIndex: idx,
                                    annotationsByPage,
                                    useOverlay
                                  });
                                  setIsModalOpen(true);
                                }}
                              />
                              {showAnnotations && (useOverlay || selectedSubmission.annotated_images?.length > 0) && (
                                <Badge className="absolute top-2 right-2 bg-green-500 text-white">
                                  With Annotations
                                </Badge>
                              )}
                              {/* Zoom Overlay */}
                              <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-all rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 rounded-lg pointer-events-none">
                                <div className="bg-white/90 px-3 py-2 rounded-lg flex items-center gap-2">
                                  <Maximize2 className="w-4 h-4" />
                                  <span className="text-sm font-medium">Click to enlarge</span>
                                </div>
                              </div>
                            </div>
                          ));
                        })()}
                      </div>
                    </div>

                    {/* Model Answer */}
                    {showModelAnswer && modelAnswerImages.length > 0 && (
                      <div className="space-y-2">
                        <h3 className="text-xs font-semibold text-green-700 sticky top-0 bg-muted/30 py-1">Model Answer (Correct)</h3>
                        <div className="space-y-4">
                          {modelAnswerImages.map((img, idx) => (
                            <div key={idx} className="relative group">
                              <div 
                                className="relative cursor-zoom-in hover:shadow-xl transition-shadow"
                                onClick={() => {
                                  const allImages = modelAnswerImages.map((image, index) => ({
                                    imageBase64: image,
                                    title: `Page ${index + 1}`
                                  }));
                                  setModalKey(prev => prev + 1);
                                  setImageZoom(120);
                                  setZoomedImages({ 
                                    images: allImages, 
                                    title: "Model Answer", 
                                    initialIndex: idx,
                                    annotationsByPage: {},
                                    useOverlay: false
                                  });
                                  setIsModalOpen(true);
                                }}
                              >
                                <img 
                                  src={`data:image/jpeg;base64,${img}`}
                                  alt={`Model Page ${idx + 1}`}
                                  className="w-full rounded-lg shadow-md border-2 border-green-200"
                                  style={{ minHeight: '400px', objectFit: 'contain' }}
                                />
                                {/* Zoom Overlay */}
                                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-all rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 pointer-events-none">
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
                    )}
                    
                    {/* Question Paper */}
                    {showQuestionPaper && questionPaperImages.length > 0 && (
                      <div className="space-y-2">
                        <h3 className="text-xs font-semibold text-blue-700 sticky top-0 bg-muted/30 py-1">Question Paper</h3>
                        <div className="space-y-4">
                          {questionPaperImages.map((img, idx) => (
                            <div key={idx} className="relative group">
                              <div 
                                className="relative cursor-zoom-in hover:shadow-xl transition-shadow"
                                onClick={() => {
                                  const allImages = questionPaperImages.map((image, index) => ({
                                    imageBase64: image,
                                    title: `Page ${index + 1}`
                                  }));
                                  setModalKey(prev => prev + 1);
                                  setImageZoom(120);
                                  setZoomedImages({ 
                                    images: allImages, 
                                    title: "Question Paper", 
                                    initialIndex: idx,
                                    annotationsByPage: {},
                                    useOverlay: false
                                  });
                                  setIsModalOpen(true);
                                }}
                              >
                                <img 
                                  src={`data:image/jpeg;base64,${img}`}
                                  alt={`Question Paper Page ${idx + 1}`}
                                  className="w-full rounded-lg shadow-md border-2 border-blue-200"
                                  style={{ minHeight: '400px', objectFit: 'contain' }}
                                />
                                {/* Zoom Overlay */}
                                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-all rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 pointer-events-none">
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
                    )}
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center">
                  <p className="text-muted-foreground text-sm">No preview available</p>
                </div>
              )}
            </div>
          </Panel>

          {/* Resize Handle */}
          <PanelResizeHandle className="w-2 bg-gray-200 hover:bg-orange-400 transition-colors cursor-col-resize" />

          {/* Right Panel - Questions Breakdown */}
          <Panel defaultSize={45} minSize={30} maxSize={70} collapsible={false}>
            <ScrollArea className="h-full">
              <div className="p-4 space-y-3">
                {/* Review Status Banner */}
                <div className={`p-3 rounded-lg border-2 sticky top-0 z-10 ${ areAllQuestionsReviewed()
                    ? "bg-green-50 border-green-300"
                    : "bg-amber-50 border-amber-300"
                  }`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {areAllQuestionsReviewed() ? (
                        <>
                          <CheckCircle2 className="w-5 h-5 text-green-600" />
                          <div>
                            <p className="text-sm font-semibold text-green-700">All Questions Reviewed</p>
                            <p className="text-xs text-green-600">Ready to approve and move to next paper</p>
                          </div>
                        </>
                      ) : (
                        <>
                          <AlertCircle className="w-5 h-5 text-amber-600" />
                          <div>
                            <p className="text-sm font-semibold text-amber-700">Review Incomplete</p>
                            <p className="text-xs text-amber-600">
                              {getReviewedCount().total - getReviewedCount().reviewed} of {getReviewedCount().total} questions need review
                            </p>
                          </div>
                        </>
                      )}
                    </div>
                    <Badge variant="secondary" className="text-sm font-bold">
                      {getReviewedCount().reviewed}/{getReviewedCount().total}
                    </Badge>
                  </div>
                </div>

                {selectedSubmission.question_scores?.map((qs, index) => {
                  const hasSubQuestions = qs.sub_scores && qs.sub_scores.length > 0;
                  const examQuestion = examQuestions.find(q => q.question_number === qs.question_number);
                  
                  return (
                  <div 
                    key={index}
                    className={`p-3 lg:p-4 rounded-lg border question-card ${
                      qs.is_reviewed ? "reviewed border-green-300 bg-green-50" : "border-orange-200 bg-orange-50/30"
                    }`}
                  >
                    {/* Question Header with Total Score */}
                    <div className="flex items-center justify-between mb-2 lg:mb-3">
                      <h4 className="font-semibold text-sm lg:text-base">Question {qs.question_number}</h4>
                      <div className="flex items-center gap-1 lg:gap-2">
                        {hasSubQuestions ? (
                          // Show total as read-only for questions with sub-questions
                          <span className="text-sm font-medium text-orange-600">{qs.obtained_marks}</span>
                        ) : (
                          <Input 
                            type="number"
                            value={qs.obtained_marks}
                            onChange={(e) => updateQuestionScore(index, "obtained_marks", parseFloat(e.target.value) || 0)}
                            className="w-16 lg:w-20 text-center text-sm"
                            data-testid={`score-q${qs.question_number}`}
                          />
                        )}
                        <span className="text-muted-foreground text-sm">/ {qs.max_marks}</span>
                      </div>
                    </div>

                    {/* Full Question Text - from exam questions or submission */}
                    {(() => {
                      let questionText = qs.question_text || examQuestion?.rubric || examQuestion?.question_text;
                      
                      // CRITICAL FIX: Handle nested question objects
                      // If questionText is an object, extract the actual text from it
                      if (typeof questionText === 'object' && questionText !== null) {
                        // Try to extract text from nested structure
                        questionText = questionText.rubric || questionText.question_text || JSON.stringify(questionText);
                      }
                      
                      // Ensure final questionText is a string
                      const questionTextString = typeof questionText === 'string' ? questionText : String(questionText || '');
                      
                      // If no question text, show AI's assessment as a fallback
                      if (!questionTextString && qs.ai_feedback && !hasSubQuestions) {
                        return (
                          <div className="mb-3 p-3 bg-blue-50/50 rounded border-l-4 border-blue-300">
                            <p className="text-xs font-medium text-blue-800 mb-1">Question {qs.question_number} (from AI assessment):</p>
                            <p className="text-xs text-gray-700 line-clamp-3">{qs.ai_feedback.slice(0, 200)}...</p>
                            <p className="text-xs text-muted-foreground italic mt-1">
                              Note: View model answer or use &quot;Extract Questions&quot; in Manage Exams for full question text
                            </p>
                          </div>
                        );
                      }
                      
                      return questionTextString ? (
                        <div className="mb-3 p-2 bg-blue-50 rounded border-l-4 border-blue-500">
                          <p className="text-xs lg:text-sm text-foreground whitespace-pre-wrap">
                            <strong className="text-blue-700">Q{qs.question_number}:</strong> {questionTextString}
                          </p>
                        </div>
                      ) : !hasSubQuestions ? (
                        <div className="mb-3 p-2 bg-amber-50 rounded border-l-2 border-amber-400">
                          <p className="text-xs text-amber-800 font-medium">⚠️ Question {qs.question_number}</p>
                          <p className="text-xs text-muted-foreground mt-1">
                            Question text not available. Upload model answer or question paper to auto-extract questions.
                          </p>
                        </div>
                      ) : null;
                    })()}

                    {/* Sub-Questions Section */}
                    {hasSubQuestions ? (
                      <div className="space-y-4 mt-3">
                        {qs.sub_scores.map((subScore, subIndex) => {
                          const examSubQuestion = examQuestion?.sub_questions?.find(sq => sq.sub_id === subScore.sub_id);
                          let subQuestionText = examSubQuestion?.rubric || examSubQuestion?.question_text || "";
                          
                          // CRITICAL FIX: Handle nested sub-question objects
                          if (typeof subQuestionText === 'object' && subQuestionText !== null) {
                            subQuestionText = subQuestionText.rubric || subQuestionText.question_text || JSON.stringify(subQuestionText);
                          }
                          
                          // Ensure it's a string
                          const subQuestionTextString = typeof subQuestionText === 'string' ? subQuestionText : String(subQuestionText || '');
                          
                          return (
                            <div 
                              key={subScore.sub_id}
                              className="ml-4 p-3 bg-gradient-to-r from-orange-50 to-amber-50/30 rounded-lg border border-orange-200 shadow-sm"
                            >
                              {/* Sub-question Header with Score */}
                              <div className="flex items-center justify-between mb-2">
                                <span className="font-semibold text-sm text-orange-700">
                                  Part {subScore.sub_id}
                                </span>
                                <div className="flex items-center gap-1 bg-white px-2 py-1 rounded border">
                                  <Input 
                                    type="number"
                                    value={subScore.obtained_marks}
                                    onChange={(e) => updateSubQuestionScore(index, subIndex, "obtained_marks", parseFloat(e.target.value) || 0)}
                                    className="w-14 text-center text-sm font-medium border-0 p-0 h-6"
                                    step="0.5"
                                  />
                                  <span className="text-muted-foreground text-sm">/ {subScore.max_marks}</span>
                                </div>
                              </div>
                              
                              {/* Sub-question Text */}
                              {subQuestionTextString && (
                                <div className="mb-3 p-2 bg-white/80 rounded border-l-3 border-orange-400">
                                  <p className="text-xs text-gray-700 whitespace-pre-wrap">
                                    <strong className="text-orange-600">{subScore.sub_id})</strong> {subQuestionTextString}
                                  </p>
                                </div>
                              )}
                              
                              {/* Sub-question AI Feedback */}
                              <div className="bg-white/50 rounded p-2">
                                <Label className="text-xs font-medium text-gray-600 flex items-center gap-1">
                                  <Sparkles className="w-3 h-3 text-orange-500" />
                                  Feedback for Part {subScore.sub_id}
                                </Label>
                                <div className="flex gap-2 mt-1">
                                  <Textarea 
                                    value={subScore.ai_feedback || ""}
                                    onChange={(e) => updateSubQuestionScore(index, subIndex, "ai_feedback", e.target.value)}
                                    className="text-xs bg-white flex-1"
                                    rows={2}
                                    placeholder={`AI feedback for part ${subScore.sub_id}...`}
                                  />
                                  <VoiceInput
                                    onTranscript={(text) => {
                                      const currentValue = subScore.ai_feedback || "";
                                      updateSubQuestionScore(index, subIndex, "ai_feedback", currentValue + (currentValue ? " " : "") + text);
                                    }}
                                  />
                                </div>
                              </div>
                            </div>
                          );
                        })}
                        
                        {/* Overall AI Feedback for the question - AFTER all sub-questions */}
                        <div className="ml-4 mt-4 p-3 bg-gradient-to-r from-blue-50 to-indigo-50/30 rounded-lg border border-blue-200">
                          <Label className="text-sm font-medium text-blue-700 flex items-center gap-1 mb-2">
                            <Brain className="w-4 h-4" />
                            Overall Feedback for Question {qs.question_number}
                          </Label>
                          <div className="flex gap-2">
                            <Textarea 
                              value={qs.ai_feedback || ""}
                              onChange={(e) => updateQuestionScore(index, "ai_feedback", e.target.value)}
                              className="text-sm bg-white flex-1"
                              rows={3}
                              placeholder={`Overall feedback for question ${qs.question_number}...`}
                            />
                            <VoiceInput
                              onTranscript={(text) => {
                                const currentValue = qs.ai_feedback || "";
                                updateQuestionScore(index, "ai_feedback", currentValue + (currentValue ? " " : "") + text);
                              }}
                            />
                          </div>
                        </div>
                      </div>
                    ) : (
                      /* No sub-questions - show regular feedback */
                      <div className="space-y-2 lg:space-y-3">
                        <div>
                          <Label className="text-xs lg:text-sm text-muted-foreground">AI Feedback</Label>
                          <div className="flex gap-2 mt-1">
                            <Textarea 
                              value={qs.ai_feedback}
                              onChange={(e) => updateQuestionScore(index, "ai_feedback", e.target.value)}
                              className="text-xs lg:text-sm flex-1"
                              rows={2}
                            />
                            <VoiceInput
                              onTranscript={(text) => {
                                const currentValue = qs.ai_feedback || "";
                                updateQuestionScore(index, "ai_feedback", currentValue + (currentValue ? " " : "") + text);
                              }}
                            />
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Teacher Comment - always shown */}
                    <div className="mt-3">
                      <Label className="text-xs lg:text-sm text-muted-foreground">Teacher Comment</Label>
                      <div className="flex gap-2 mt-1">
                        <Textarea 
                          value={qs.teacher_comment || ""}
                          onChange={(e) => updateQuestionScore(index, "teacher_comment", e.target.value)}
                          placeholder="Add your comments..."
                          className="text-xs lg:text-sm flex-1"
                          rows={2}
                        />
                        <VoiceInput
                          onTranscript={(text) => {
                            const currentValue = qs.teacher_comment || "";
                            updateQuestionScore(index, "teacher_comment", currentValue + (currentValue ? " " : "") + text);
                          }}
                        />
                      </div>
                    </div>

                    {/* Rubric / Evaluator Preference */}
                    <div className="mt-3">
                      <Label className="text-xs lg:text-sm text-muted-foreground">Rubric / Evaluator Preference</Label>
                      <div className="flex gap-2 mt-1">
                        <Textarea 
                          value={qs.rubric_preference || ""}
                          onChange={(e) => updateQuestionScore(index, "rubric_preference", e.target.value)}
                          placeholder="Add rubric notes or evaluator preferences..."
                          className="text-xs lg:text-sm flex-1"
                          rows={2}
                        />
                        <VoiceInput
                          onTranscript={(text) => {
                            const currentValue = qs.rubric_preference || "";
                            updateQuestionScore(index, "rubric_preference", currentValue + (currentValue ? " " : "") + text);
                          }}
                        />
                      </div>
                    </div>

                    {/* Footer Actions */}
                    <div className="flex items-center justify-between gap-2 flex-wrap mt-3">
                      <div className="flex items-center gap-2">
                        <Checkbox 
                          id={`reviewed-desktop-${index}`}
                          checked={qs.is_reviewed}
                          onCheckedChange={(checked) => updateQuestionScore(index, "is_reviewed", checked)}
                        />
                        <Label htmlFor={`reviewed-desktop-${index}`} className="text-xs lg:text-sm cursor-pointer">
                          Mark as reviewed
                        </Label>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openFeedbackDialog(qs)}
                        className="text-xs text-orange-600 hover:text-orange-700 hover:bg-orange-50"
                        title="Submit feedback to improve AI grading"
                      >
                        <MessageSquarePlus className="w-3 h-3 mr-1" />
                        Improve AI
                      </Button>
                    </div>
                  </div>
                );
                })}
              </div>
            </ScrollArea>
          </Panel>
        </PanelGroup>
      </div>

      {/* Footer Actions */}
      <div className="border-t p-3 lg:p-4 flex items-center justify-between bg-muted/30">
        <div className="flex items-center gap-1 lg:gap-2">
          <Button 
            variant="outline" 
            size="sm"
            onClick={() => navigatePaper(-1)}
            disabled={currentIndex <= 0}
            className="px-2 lg:px-3"
          >
            <ChevronLeft className="w-4 h-4" />
            <span className="hidden sm:inline ml-1">Prev</span>
          </Button>
          <Button 
            variant="outline" 
            size="sm"
            onClick={() => navigatePaper(1)}
            disabled={currentIndex >= filteredSubmissions.length - 1}
            className="px-2 lg:px-3"
          >
            <span className="hidden sm:inline mr-1">Next</span>
            <ChevronRight className="w-4 h-4" />
          </Button>
          <span className="text-xs lg:text-sm text-muted-foreground ml-1 lg:ml-2">
            {currentIndex + 1}/{filteredSubmissions.length}
          </span>
        </div>

        <div className="flex items-center gap-1 lg:gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownloadPdf}
            disabled={!selectedSubmission}
            className="text-xs lg:text-sm"
            title="Download answer sheet as PDF"
          >
            <Download className="w-3 h-3 lg:w-4 lg:h-4" />
            <span className="ml-1 lg:ml-2">Download PDF</span>
          </Button>
          <Button 
            variant="outline"
            size="sm"
            onClick={handleSaveChanges}
            disabled={saving}
            data-testid="save-changes-btn"
            className="text-xs lg:text-sm"
          >
            {saving ? <RefreshCw className="w-3 h-3 lg:w-4 lg:h-4 animate-spin" /> : <Save className="w-3 h-3 lg:w-4 lg:h-4" />}
            <span className="ml-1 lg:ml-2">Save</span>
          </Button>
          <Button 
            size="sm"
            onClick={() => {
              const { reviewed, total } = getReviewedCount();
              if (!isGradingComplete) {
                toast.error("Cannot approve! All questions must be graded and listed first.");
                return;
              }
              if (reviewed < total) {
                toast.error(`Cannot approve! ${total - reviewed} question(s) not reviewed.`);
                return;
              }
              handleSaveChanges();
              if (currentIndex < filteredSubmissions.length - 1) {
                navigatePaper(1);
              }
            }}
            disabled={saving || !areAllQuestionsReviewed() || !isGradingComplete}
            data-testid="approve-finalize-btn"
            className={`text-xs lg:text-sm ${
              areAllQuestionsReviewed() && isGradingComplete
                ? "" 
                : "opacity-50 cursor-not-allowed"
            }`}
            title={
              !isGradingComplete
                ? "All questions must be graded and listed before approval"
                : areAllQuestionsReviewed()
                  ? "Approve this submission"
                  : `Please review all ${getReviewedCount().total} questions first`
            }
          >
            <CheckCircle className="w-3 h-3 lg:w-4 lg:h-4" />
            <span className="ml-1 lg:ml-2 hidden sm:inline">
              Approve {!areAllQuestionsReviewed() && `(${getReviewedCount().reviewed}/${getReviewedCount().total})`}
            </span>
          </Button>
        </div>
      </div>

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
              <div
                className="mx-auto"
                style={{ width: `${imageZoom}%`, maxWidth: "none", transition: "width 0.2s" }}
              >
                <AnnotationImage
                  imageBase64={zoomedImage.imageBase64}
                  pageIndex={zoomedImage.pageIndex}
                  annotations={zoomedImage.annotations || []}
                  showAnnotations={!!zoomedImage.useOverlay}
                  interactive={false}
                />
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* AI Feedback Dialog */}
      <Dialog open={feedbackDialogOpen} onOpenChange={setFeedbackDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Lightbulb className="w-5 h-5 text-orange-500" />
              Improve AI Grading
            </DialogTitle>
          </DialogHeader>
          
          {feedbackQuestion && (
            <div className="space-y-4 pb-4">
              {/* Question Header */}
              <div className="p-3 bg-muted/50 rounded-lg">
                <p className="text-sm font-medium mb-1">Question {feedbackQuestion.question_number}</p>
                {feedbackQuestion.question_text && (
                  <p className="text-xs text-muted-foreground line-clamp-2">
                    {(() => {
                      let text = feedbackQuestion.question_text;
                      if (typeof text === 'object' && text !== null) {
                        text = text.rubric || text.question_text || JSON.stringify(text);
                      }
                      return typeof text === 'string' ? text : String(text || '');
                    })()}
                  </p>
                )}
              </div>

              {/* Multiple Corrections */}
              {feedbackCorrections.map((correction, index) => (
                <div key={correction.id} className="p-4 border-2 border-orange-200 rounded-lg bg-orange-50/30 space-y-3">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-sm font-semibold text-orange-700">
                      Correction {index + 1}
                    </h4>
                    {feedbackCorrections.length > 1 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => removeCorrection(correction.id)}
                        className="h-7 w-7 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    )}
                  </div>

                  {/* Sub-Question Selector */}
                  {feedbackQuestion.sub_scores && feedbackQuestion.sub_scores.length > 0 && (
                    <div>
                      <Label className="text-xs">Select Part/Sub-Question</Label>
                      <Select 
                        value={correction.selected_sub_question}
                        onValueChange={(v) => {
                          updateCorrection(correction.id, 'selected_sub_question', v);
                          if (v === "all") {
                            updateCorrection(correction.id, 'teacher_expected_grade', feedbackQuestion.obtained_marks.toString());
                          } else {
                            const subScore = feedbackQuestion.sub_scores.find(s => s.sub_id === v);
                            if (subScore) {
                              updateCorrection(correction.id, 'teacher_expected_grade', subScore.obtained_marks.toString());
                            }
                          }
                        }}
                      >
                        <SelectTrigger className="text-sm">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">
                            <span className="font-medium">Whole Question</span>
                            <span className="text-xs text-muted-foreground ml-2">
                              ({feedbackQuestion.obtained_marks}/{feedbackQuestion.max_marks} marks)
                            </span>
                          </SelectItem>
                          {feedbackQuestion.sub_scores.map((subScore, idx) => {
                            const examQuestion = examQuestions.find(q => q.question_number === feedbackQuestion.question_number);
                            const examSubQuestion = examQuestion?.sub_questions?.find(sq => sq.sub_id === subScore.sub_id);
                            const subLabel = examSubQuestion?.sub_label || `Part ${idx + 1}`;
                            
                            return (
                              <SelectItem key={subScore.sub_id} value={subScore.sub_id}>
                                <span className="font-medium">{subLabel}</span>
                                <span className="text-xs text-muted-foreground ml-2">
                                  ({subScore.obtained_marks}/{subScore.max_marks} marks)
                                </span>
                              </SelectItem>
                            );
                          })}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label className="text-xs">AI Grade</Label>
                      <div className="p-2 bg-white rounded text-center font-medium border">
                        {(() => {
                          if (correction.selected_sub_question === "all") {
                            return `${feedbackQuestion.obtained_marks} / ${feedbackQuestion.max_marks}`;
                          } else {
                            const subScore = feedbackQuestion.sub_scores?.find(
                              s => s.sub_id === correction.selected_sub_question
                            );
                            return subScore 
                              ? `${subScore.obtained_marks} / ${subScore.max_marks}`
                              : `${feedbackQuestion.obtained_marks} / ${feedbackQuestion.max_marks}`;
                          }
                        })()}
                      </div>
                    </div>
                    <div>
                      <Label className="text-xs">Your Expected Grade</Label>
                      <Input 
                        type="number"
                        min="0"
                        max={(() => {
                          if (correction.selected_sub_question === "all") {
                            return feedbackQuestion.max_marks;
                          } else {
                            const subScore = feedbackQuestion.sub_scores?.find(
                              s => s.sub_id === correction.selected_sub_question
                            );
                            return subScore?.max_marks || feedbackQuestion.max_marks;
                          }
                        })()}
                        step="0.5"
                        value={correction.teacher_expected_grade}
                        onChange={(e) => updateCorrection(correction.id, 'teacher_expected_grade', e.target.value)}
                        className="text-center"
                      />
                    </div>
                  </div>

                  <div>
                    <Label className="text-xs">AI&apos;s Feedback</Label>
                    <div className="p-2 bg-white rounded text-xs text-muted-foreground max-h-16 overflow-y-auto border">
                      {(() => {
                        if (correction.selected_sub_question === "all") {
                          return feedbackQuestion.ai_feedback || "No AI feedback available";
                        } else {
                          const subScore = feedbackQuestion.sub_scores?.find(
                            s => s.sub_id === correction.selected_sub_question
                          );
                          return subScore?.ai_feedback || feedbackQuestion.ai_feedback || "No AI feedback available";
                        }
                      })()}
                    </div>
                  </div>

                  <div>
                    <Label className="text-xs">Your Correction / Feedback *</Label>
                    <div className="flex gap-2 mt-1">
                      <Textarea 
                        value={correction.teacher_correction}
                        onChange={(e) => updateCorrection(correction.id, 'teacher_correction', e.target.value)}
                        placeholder="Explain what the AI got wrong and how it should grade this type of answer..."
                        rows={3}
                        className="text-sm flex-1"
                      />
                      <VoiceInput
                        onTranscript={(text) => {
                          const currentValue = correction.teacher_correction || "";
                          updateCorrection(correction.id, 'teacher_correction', currentValue + (currentValue ? " " : "") + text);
                        }}
                      />
                    </div>
                  </div>
                </div>
              ))}

              {/* Add Another Correction Button */}
              <Button
                type="button"
                variant="outline"
                onClick={addNewCorrection}
                className="w-full border-dashed border-2 border-orange-300 text-orange-600 hover:bg-orange-50 hover:text-orange-700"
              >
                <Plus className="w-4 h-4 mr-2" />
                Add Another Sub-Question Correction
              </Button>

              {/* Apply to All Papers Option */}
              <div className="flex items-start space-x-3 p-3 bg-orange-50 border border-orange-200 rounded-lg">
                <Checkbox 
                  id="apply-to-all"
                  checked={applyToAllPapers}
                  onCheckedChange={setApplyToAllPapers}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <label
                    htmlFor="apply-to-all"
                    className="text-sm font-medium leading-none cursor-pointer flex items-center gap-2"
                  >
                    🤖 Intelligently re-grade all papers with AI
                  </label>
                  <p className="text-xs text-muted-foreground mt-1">
                    AI will re-analyze each student&apos;s answer for {feedbackCorrections.filter(c => c.teacher_correction.trim()).length} part(s) using your grading guidance.
                  </p>
                  <p className="text-xs text-orange-600 mt-1 font-medium">
                    ⏱️ This will take 1-2 minutes for 30 papers. Uses LLM credits.
                  </p>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setFeedbackDialogOpen(false)}
                  disabled={submittingFeedback}
                >
                  Cancel
                </Button>
                <Button 
                  onClick={handleSubmitFeedback}
                  disabled={submittingFeedback || feedbackCorrections.every(c => !c.teacher_correction.trim())}
                  className="bg-orange-600 hover:bg-orange-700"
                >
                  {submittingFeedback ? "Submitting..." : `Submit ${feedbackCorrections.filter(c => c.teacher_correction.trim()).length} Correction(s)`}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
    );
  };

  return (
    <Layout user={user}>
      <div className="space-y-4" data-testid="review-papers-page">
        {/* Submissions List - Full Width */}
        <div className="max-w-7xl mx-auto">
          {/* Submissions List */}
          <Card className="flex flex-col">
            <CardHeader className="p-3 lg:p-4 pb-2 lg:pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base lg:text-lg">Papers to Review</CardTitle>
                {filters.exam_id && filteredSubmissions.length > 0 && (
                  <Button 
                    onClick={handleBulkApprove}
                    size="sm"
                    className="bg-green-600 hover:bg-green-700 text-xs"
                    data-testid="bulk-approve-btn"
                  >
                    <CheckCircle2 className="w-3 h-3 mr-1" />
                    Approve All
                  </Button>
                )}
              </div>
                
                {/* Filters */}
                <div className="space-y-2 mt-2 lg:mt-3">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <Input 
                      placeholder="Search student..."
                      value={searchInput}
                      onChange={(e) => setSearchInput(e.target.value)}
                      className="pl-9 text-sm"
                      data-testid="search-input"
                    />
                  </div>
                  
                  {/* Batch Filter */}
                  <Select 
                    value={filters.batch_id || "all"} 
                    onValueChange={(v) => setFilters(prev => ({ ...prev, batch_id: v === "all" ? "" : v, exam_id: "" }))}
                  >
                    <SelectTrigger data-testid="batch-filter" className="text-sm">
                      <SelectValue placeholder="Filter by batch" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Batches</SelectItem>
                      {batches.map(batch => (
                        <SelectItem key={batch.batch_id} value={batch.batch_id}>
                          {batch.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  
                  {/* Exam Filter */}
                  <Select 
                    value={filters.exam_id || "all"} 
                    onValueChange={(v) => setFilters(prev => ({ ...prev, exam_id: v === "all" ? "" : v }))}
                  >
                    <SelectTrigger data-testid="exam-filter" className="text-sm">
                      <SelectValue placeholder="Filter by exam" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Exams</SelectItem>
                      {exams
                        .filter(exam => !filters.batch_id || exam.batch_id === filters.batch_id)
                        .map(exam => (
                          <SelectItem key={exam.exam_id} value={exam.exam_id}>
                            {exam.exam_name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>

                  {/* Questions are auto-extracted when documents are uploaded */}
                </div>
              </CardHeader>
              
              <CardContent className="flex-1 overflow-hidden p-0">
                <ScrollArea className="h-[300px] lg:h-full px-3 lg:px-4 pb-3 lg:pb-4">
                  {loading ? (
                    <div className="space-y-2">
                      {[1, 2, 3, 4, 5].map(i => (
                        <div key={i} className="h-16 lg:h-20 bg-muted animate-pulse rounded-lg" />
                      ))}
                    </div>
                  ) : filteredSubmissions.length === 0 ? (
                    <div className="text-center py-6 lg:py-8">
                      <FileText className="w-10 h-10 lg:w-12 lg:h-12 mx-auto text-muted-foreground/50 mb-3" />
                      <p className="text-sm text-muted-foreground">No submissions found</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {filteredSubmissions.map((submission) => (
                        <div 
                          key={submission.submission_id}
                          onClick={() => fetchSubmissionDetails(submission.submission_id)}
                          className={`p-3 lg:p-4 rounded-lg border cursor-pointer transition-all ${
                            selectedSubmission?.submission_id === submission.submission_id
                              ? "border-primary bg-primary/5"
                              : "border-border hover:border-primary/50 hover:bg-muted/50"
                          }`}
                          data-testid={`submission-${submission.submission_id}`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="min-w-0">
                              <p className="font-medium text-sm lg:text-base truncate">{submission.student_name}</p>
                              <p className="text-xs lg:text-sm text-muted-foreground truncate">
                                {submission.exam_name || "Unknown Exam"}
                              </p>
                            </div>
                            <div className="text-right flex-shrink-0 ml-2">
                              <p className="font-bold text-base lg:text-lg">
                                {submission.obtained_marks || submission.total_score || 0}
                                <span className="text-xs lg:text-sm font-normal text-muted-foreground">
                                  /{submission.total_marks || exams.find(e => e.exam_id === submission.exam_id)?.total_marks || "?"}
                                </span>
                              </p>
                              <Badge 
                                variant="secondary"
                                className={`text-xs ${
                                  submission.status === "teacher_reviewed" 
                                    ? "bg-green-100 text-green-700" 
                                    : "bg-yellow-100 text-yellow-700"
                                }`}
                              >
                                {submission.status === "teacher_reviewed" ? "Done" : "Review"}
                              </Badge>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          </div>

          {/* Review Dialog - Full Screen */}
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogContent className="max-w-[98vw] w-full max-h-[95vh] h-[95vh] p-0 flex flex-col">
              {renderDetailContent()}
            </DialogContent>
          </Dialog>

          {/* Auto-Publish Dialog */}
          <Dialog open={autoPublishDialogOpen} onOpenChange={setAutoPublishDialogOpen}>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <div className="flex items-center gap-2">
                  <PartyPopper className="w-6 h-6 text-green-500" />
                  <DialogTitle>All Papers Reviewed!</DialogTitle>
                </div>
                <DialogDescription>
                  Great job! You&apos;ve reviewed all papers for this exam. 
                  Would you like to publish the results now so students can see their scores?
                </DialogDescription>
              </DialogHeader>
              
              <div className="space-y-4 py-4">
                <p className="text-sm font-medium">Choose what students can see:</p>
                
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
                      <p className="text-xs text-muted-foreground">Students can see their submitted answers</p>
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
                      <p className="text-xs text-muted-foreground">Students can see the correct answers</p>
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
                <Button 
                  variant="outline" 
                  onClick={() => setAutoPublishDialogOpen(false)}
                >
                  Maybe Later
                </Button>
                <Button 
                  onClick={handlePublishFromDialog}
                  className="bg-green-500 hover:bg-green-600"
                >
                  <Eye className="w-4 h-4 mr-2" />
                  Publish Results
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          {/* Multi-Page Continuous Scroll Viewer - Rendered at top level to avoid nested dialog issues */}
          <Dialog 
            key={modalKey}
            open={isModalOpen}
            onOpenChange={(open) => {
              console.log('🚪 Dialog onOpenChange called. New state:', open);
              setIsModalOpen(open);
              if (!open) {
                setZoomedImages(null);
                console.log('❌ Modal CLOSED');
              } else {
                console.log('✅ Modal OPENED');
              }
            }}
          >
            <DialogContent className="max-w-[95vw] max-h-[95vh] p-0 overflow-hidden">
              {/* Header with extra padding-right to avoid blocking close button */}
              <DialogHeader className="px-4 pt-4 pb-2 pr-16 border-b">
                <DialogTitle className="text-left">
                  {zoomedImages?.title || "Document"} - All Pages
                  <span className="text-sm text-muted-foreground font-normal ml-2">
                    ({zoomedImages?.images?.length || 0} pages)
                  </span>
                </DialogTitle>
                {/* Zoom Controls */}
                <div className="flex items-center gap-2 mt-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      setImageZoom(Math.max(50, imageZoom - 25));
                    }}
                  >
                    <ZoomOut className="w-4 h-4" />
                  </Button>
                  <span className="text-sm font-medium min-w-[60px] text-center">{imageZoom}%</span>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      setImageZoom(Math.min(200, imageZoom + 25));
                    }}
                  >
                    <ZoomIn className="w-4 h-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      setImageZoom(100);
                    }}
                  >
                    Reset
                  </Button>
                </div>
              </DialogHeader>
              <div className="overflow-auto p-4 bg-gray-50" style={{ maxHeight: 'calc(95vh - 80px)' }}>
                {zoomedImages?.images && (
                  <div className="space-y-6">
                    {zoomedImages.images.map((image, idx) => (
                      <div key={idx} className="relative bg-white p-2 rounded-lg shadow-sm">
                        <div className="sticky top-2 left-2 bg-blue-500 text-white px-3 py-1.5 rounded-lg text-sm font-medium z-10 inline-block shadow-md">
                          📄 {image.title}
                        </div>
                        <div
                          className="mx-auto mt-2"
                          style={{ width: `${imageZoom}%`, maxWidth: "none" }}
                        >
                          <AnnotationImage
                            imageBase64={image.imageBase64}
                            pageIndex={idx}
                            annotations={zoomedImages.annotationsByPage?.[idx] || []}
                            showAnnotations={!!zoomedImages.useOverlay}
                            interactive={false}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </Layout>
    );
  }
