import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Progress } from "../../components/ui/progress";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "../../components/ui/alert-dialog";
import { toast } from "sonner";
import { useDropzone } from "react-dropzone";
import { 
  Upload, 
  FileText, 
  Plus, 
  Trash2, 
  CheckCircle, 
  ArrowRight, 
  ArrowLeft,
  Loader2,
  X,
  AlertCircle,
  RotateCcw,
  Info
} from "lucide-react";

const GRADING_MODES = [
  { 
    id: "strict", 
    name: "Strict Mode", 
    description: "Exact match with model answer required. Minimal tolerance for deviations.",
    color: "border-red-300 bg-red-50"
  },
  { 
    id: "balanced", 
    name: "Balanced Mode", 
    description: "Fair evaluation considering both accuracy and conceptual understanding.",
    color: "border-blue-300 bg-blue-50",
    recommended: true
  },
  { 
    id: "conceptual", 
    name: "Conceptual Mode", 
    description: "Focus on understanding of concepts over exact wording or format.",
    color: "border-purple-300 bg-purple-50"
  },
  { 
    id: "lenient", 
    name: "Lenient Mode", 
    description: "Generous partial credit. Rewards attempt and partial understanding.",
    color: "border-green-300 bg-green-50"
  },
];

const EXAM_TYPES = [
  "Mock Test",
  "Unit Test", 
  "Mid-Term",
  "End-Term",
  "Competitive Prep",
  "Custom"
];

// Sub-question labeling formats
const LABELING_FORMATS = {
  lowercase: { name: "a, b, c...", generator: (i) => String.fromCharCode(97 + i) },
  uppercase: { name: "A, B, C...", generator: (i) => String.fromCharCode(65 + i) },
  roman_lower: { name: "i, ii, iii...", generator: (i) => ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'][i] || `${i + 1}` },
  roman_upper: { name: "I, II, III...", generator: (i) => ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'][i] || `${i + 1}` },
  numbers: { name: "1, 2, 3...", generator: (i) => `${i + 1}` },
};

export default function UploadGrade({ user }) {
  const [step, setStep] = useState(1);
  const [batches, setBatches] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState(0);

  // Sub-question labeling format state (per question)
  const [labelFormats, setLabelFormats] = useState({});
  // Modal state for format selection
  const [formatModalOpen, setFormatModalOpen] = useState(false);
  const [pendingAddSubQuestion, setPendingAddSubQuestion] = useState(null);
  
  // Reset confirmation dialog
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  
  // Question method change confirmation dialog
  const [changeMethodDialogOpen, setChangeMethodDialogOpen] = useState(false);
  
  // New state for optional question entry
  const [questionsSkipped, setQuestionsSkipped] = useState(false);
  const [showManualEntry, setShowManualEntry] = useState(false);
  const [paperUploaded, setPaperUploaded] = useState(false);

  // Form state
  const [formData, setFormData] = useState({
    batch_id: "",
    subject_id: "",
    exam_type: "",
    exam_name: "",
    total_marks: 100,
    exam_date: new Date().toISOString().split("T")[0],
    grading_mode: "balanced",
    questions: [{ question_number: 1, max_marks: 10, rubric: "", sub_questions: [] }]
  });

  const [modelAnswerFile, setModelAnswerFile] = useState(null);
  const [questionPaperFile, setQuestionPaperFile] = useState(null);
  const [studentFiles, setStudentFiles] = useState([]);
  const [examId, setExamId] = useState(null);
  const [results, setResults] = useState(null);
  const [activeJobId, setActiveJobId] = useState(null);
  const pollIntervalRef = useRef(null);

  // Centralized polling function
  const startPollingJob = useCallback((job_id) => {
    console.log('Starting polling for job:', job_id);
    
    // Clear any existing interval first
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    
    let pollAttempts = 0;
    const MAX_POLL_ATTEMPTS = 3600; // 2 hours (3600 * 2 seconds) - for large batches up to 2500+ pages
    
    const interval = setInterval(async () => {
      pollAttempts++;
      
      // SAFETY: Stop polling after 2 hours (for very large batches)
      if (pollAttempts >= MAX_POLL_ATTEMPTS) {
        console.error('Polling timeout: exceeded 2 hours. Job may still be processing in background.');
        clearInterval(interval);
        pollIntervalRef.current = null;
        toast.error('Grading is taking longer than expected. Please check the Manage Exams page for status.');
        setProcessing(false);
        return;
      }
      
      try {
        const jobResponse = await axios.get(`${API}/grading-jobs/${job_id}`, {
          withCredentials: true
        });
        const jobData = jobResponse.data;
        
        console.log('Polling job status:', jobData.status, `${jobData.processed_papers}/${jobData.total_papers}`);
        
        // Update progress bar
        const progress = jobData.total_papers > 0 
          ? Math.round((jobData.processed_papers / jobData.total_papers) * 100)
          : 0;
        setProcessingProgress(progress);
        
        // CRITICAL FIX: If processed equals total but status isn't completed, treat as completed
        if (jobData.processed_papers >= jobData.total_papers && 
            jobData.total_papers > 0 && 
            jobData.status !== 'completed' && 
            jobData.status !== 'failed' &&
            jobData.status !== 'cancelled') {
          console.log('Job appears done (processed >= total) but status is still:', jobData.status);
          console.log('Treating as completed...');
          jobData.status = 'completed';
        }
        
        // Check if job completed
        if (jobData.status === 'completed') {
          clearInterval(interval);
          pollIntervalRef.current = null;
          setProcessingProgress(100);
          
          console.log('Job completed! Setting results and moving to step 6');
          
          // Set results in the expected format
          const resultsData = {
            processed: jobData.successful,
            submissions: jobData.submissions || [],
            errors: jobData.errors || []
          };
          setResults(resultsData);
          
          // Force UI update
          setProcessing(false);
          setActiveJobId(null);
          localStorage.removeItem('activeGradingJob');
          
          // Move to results step
          setStep(6);
          
          // Show success/error messages
          if (jobData.errors && jobData.errors.length > 0) {
            toast.warning(`Graded ${jobData.successful} of ${jobData.total_papers} papers. ${jobData.errors.length} had errors.`);
            
            // Show first 3 errors only
            jobData.errors.slice(0, 3).forEach(error => {
              toast.error(`${error.filename}: ${error.error}`, { duration: 5000 });
            });
            if (jobData.errors.length > 3) {
              toast.info(`+ ${jobData.errors.length - 3} more errors`);
            }
          } else {
            toast.success(`✓ Successfully graded all ${jobData.successful} papers!`);
          }
          
          // Clear remaining localStorage
          localStorage.removeItem('uploadGradeState');
          
        } else if (jobData.status === 'failed') {
          clearInterval(interval);
          pollIntervalRef.current = null;
          console.error('Job failed:', jobData.error);
          toast.error(`Grading failed: ${jobData.error || 'Unknown error'}`);
          setProcessing(false);
          setActiveJobId(null);
          localStorage.removeItem('activeGradingJob');
          localStorage.removeItem('uploadGradeState');
        } else if (jobData.status === 'cancelled') {
          clearInterval(interval);
          pollIntervalRef.current = null;
          console.log('Job was cancelled');
          toast.warning('Grading was cancelled');
          setProcessing(false);
          setActiveJobId(null);
          localStorage.removeItem('activeGradingJob');
          localStorage.removeItem('uploadGradeState');
        }
        // If status is 'processing' or 'pending', continue polling
      } catch (pollError) {
        console.error('Error polling job status:', pollError);
        
        // If job not found (404) or forbidden (403), stop polling and clear state
        if (pollError.response?.status === 404 || pollError.response?.status === 403) {
          console.log('Job no longer accessible (404/403). Clearing state and stopping polling.');
          clearInterval(interval);
          pollIntervalRef.current = null;
          
          toast.error('Grading job no longer exists. Starting fresh.');
          
          setProcessing(false);
          setActiveJobId(null);
          localStorage.removeItem('activeGradingJob');
          localStorage.removeItem('uploadGradeState');
          
          // Reset to step 1
          setStep(1);
        }
        // For other network errors, keep trying
      }
    }, 2000); // Poll every 2 seconds
    
    pollIntervalRef.current = interval;
    
    // Safety timeout - stop polling after 20 minutes
    setTimeout(() => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
        toast.error("Grading is taking longer than expected. Check Review Papers page.");
        setProcessing(false);
      }
    }, 1200000); // 20 minutes
  }, []);

  // Cleanup polling interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        console.log('Cleaning up polling interval on unmount');
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // Restore state from localStorage on mount
  useEffect(() => {
    const restoreState = async () => {
      const savedState = localStorage.getItem('uploadGradeState');
      if (!savedState) return;
      
      try {
        const state = JSON.parse(savedState);
        // Only restore if the state is recent (within last 2 hours)
        if (!state.timestamp || Date.now() - state.timestamp >= 2 * 60 * 60 * 1000) {
          localStorage.removeItem('uploadGradeState');
          return;
        }
        
        // Restore persisted state silently
        
        // PRIORITY: Handle active grading job FIRST
        if (state.activeJobId) {
          console.log('Active grading job found:', state.activeJobId);
          
          // CRITICAL: Verify job and exam still exist before restoring
          try {
            // Check if exam exists
            const examResponse = await axios.get(`${API}/exams/${state.examId}`);
            const examData = examResponse.data;
            
            console.log('Exam verified:', examData.exam_id);
            
            // Exam exists, proceed with restoration
            setExamId(state.examId);
            setActiveJobId(state.activeJobId);
            setProcessing(true);
            
            // Restore form data
            if (state.formData) {
              setFormData(state.formData);
            }
            
            // Set file upload flags based on backend data
            if (examData.model_answer_file_id) {
              setPaperUploaded(true);
              console.log('Model answer confirmed uploaded');
            }
            
            if (examData.question_paper_file_id) {
              setQuestionsSkipped(false);
              console.log('Question paper confirmed uploaded');
            }
            
            setStep(5); // Always go to step 5 for active grading
            toast.info('Resuming grading progress...');
            
            // CRITICAL FIX: Restart polling for the active job
            startPollingJob(state.activeJobId);
            
            return; // Exit early - grading is top priority
            
          } catch (error) {
            // Exam or job doesn't exist (404, 403, etc.)
            console.error('Error restoring grading job:', error);
            console.log('Exam or job no longer exists. Clearing stale state.');
            
            // Clear stale localStorage
            localStorage.removeItem('activeGradingJob');
            localStorage.removeItem('uploadGradeState');
            
            // Reset state and start fresh
            setActiveJobId(null);
            setProcessing(false);
            setStep(1);
            
            toast.error('Previous grading job no longer exists. Starting fresh.');
            
            // Don't return - continue with normal flow
          }
        }
        
        // If we have an examId but no active job, check with backend
        if (state.examId) {
          try {
            const examResponse = await axios.get(`${API}/exams/${state.examId}`);
            const examData = examResponse.data;
            // Set exam ID first
            setExamId(state.examId);
            
            // Restore form data if available
            if (state.formData) {
              setFormData(state.formData);
            }
            
            // Mark files as uploaded based on backend data
            if (examData.model_answer_file_id) {
              setPaperUploaded(true);
            }
            
            if (examData.question_paper_file_id) {
              setQuestionsSkipped(false);
            }
            
            // Restore step
            setStep(state.step || 1);
            
          } catch (error) {
            console.error('Error fetching exam data:', error);
            // If exam not found, clear state
            if (error.response?.status === 404) {
              localStorage.removeItem('uploadGradeState');
              setStep(1);
              setExamId(null);
            }
          }
        }
        
      } catch (error) {
        console.error('Error restoring state:', error);
        localStorage.removeItem('uploadGradeState');
      }
    };
    
    restoreState();
  }, [startPollingJob]);

  // Save state to localStorage whenever it changes
  useEffect(() => {
    if (examId || activeJobId || step > 1) {
      const state = {
        step,
        examId,
        activeJobId,
        formData: formData, // Save form data too
        timestamp: Date.now()
      };
      localStorage.setItem('uploadGradeState', JSON.stringify(state));
    }
  }, [step, examId, activeJobId, formData]);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      const [batchesRes, subjectsRes] = await Promise.all([
        axios.get(`${API}/batches`),
        axios.get(`${API}/subjects`)
      ]);
      // Filter out closed/archived batches for Upload & Grade
      const activeBatches = batchesRes.data.filter(batch => batch.status !== 'closed');
      setBatches(activeBatches);
      setSubjects(subjectsRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    }
  };

  const handleInputChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const addQuestion = () => {
    const nextNum = formData.questions.length + 1;
    setFormData(prev => ({
      ...prev,
      questions: [...prev.questions, { question_number: nextNum, max_marks: 10, rubric: "", sub_questions: [] }]
    }));
  };

  const updateQuestion = (index, field, value) => {
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      newQuestions[index] = { ...newQuestions[index], [field]: value };
      return { ...prev, questions: newQuestions };
    });
  };

  const removeQuestion = (index) => {
    if (formData.questions.length > 1) {
      setFormData(prev => ({
        ...prev,
        questions: prev.questions.filter((_, i) => i !== index).map((q, i) => ({
          ...q,
          question_number: i + 1
        }))
      }));
      // Clean up label formats for this question
      setLabelFormats(prev => {
        const newFormats = { ...prev };
        delete newFormats[index];
        return newFormats;
      });
    }
  };

  // Get the label generator for a specific question and level
  const getLabelGenerator = (questionIndex, level = 'level1') => {
    const formatKey = labelFormats[questionIndex]?.[level] || 
      (level === 'level1' ? 'lowercase' : level === 'level2' ? 'roman_lower' : 'uppercase');
    return LABELING_FORMATS[formatKey]?.generator || LABELING_FORMATS.lowercase.generator;
  };

  // Handle clicking "Add Sub-question" - show format selector if first sub-question
  const handleAddSubQuestionClick = (questionIndex, level = 'level1', subIndex = null, partIndex = null) => {
    const question = formData.questions[questionIndex];
    let needsFormatSelection = false;
    
    if (level === 'level1') {
      needsFormatSelection = !question.sub_questions || question.sub_questions.length === 0;
    } else if (level === 'level2' && subIndex !== null) {
      const subQ = question.sub_questions?.[subIndex];
      needsFormatSelection = !subQ?.sub_parts || subQ.sub_parts.length === 0;
    } else if (level === 'level3' && subIndex !== null && partIndex !== null) {
      const part = question.sub_questions?.[subIndex]?.sub_parts?.[partIndex];
      needsFormatSelection = !part?.sub_parts || part.sub_parts.length === 0;
    }

    if (needsFormatSelection && !labelFormats[questionIndex]?.[level]) {
      setPendingAddSubQuestion({ questionIndex, level, subIndex, partIndex });
      setFormatModalOpen(true);
    } else {
      // Format already selected, add directly
      if (level === 'level1') {
        addSubQuestion(questionIndex);
      } else if (level === 'level2') {
        addSubSubQuestion(questionIndex, subIndex);
      } else if (level === 'level3') {
        addLevel3Part(questionIndex, subIndex, partIndex);
      }
    }
  };

  // Confirm format selection and add sub-question
  const confirmFormatAndAdd = (formatKey) => {
    if (!pendingAddSubQuestion) return;
    
    const { questionIndex, level, subIndex, partIndex } = pendingAddSubQuestion;
    
    // Save the selected format
    setLabelFormats(prev => ({
      ...prev,
      [questionIndex]: {
        ...prev[questionIndex],
        [level]: formatKey
      }
    }));

    // Close modal and add the sub-question
    setFormatModalOpen(false);
    
    // Use setTimeout to ensure state is updated before adding
    setTimeout(() => {
      if (level === 'level1') {
        addSubQuestionWithFormat(questionIndex, formatKey);
      } else if (level === 'level2') {
        addSubSubQuestionWithFormat(questionIndex, subIndex, formatKey);
      } else if (level === 'level3') {
        addLevel3PartWithFormat(questionIndex, subIndex, partIndex, formatKey);
      }
      setPendingAddSubQuestion(null);
    }, 0);
  };

  // Sub-question management with format support
  const addSubQuestion = (questionIndex) => {
    const generator = getLabelGenerator(questionIndex, 'level1');
    addSubQuestionWithFormat(questionIndex, null, generator);
  };

  const addSubQuestionWithFormat = (questionIndex, formatKey = null, existingGenerator = null) => {
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      const subQs = newQuestions[questionIndex].sub_questions || [];
      const generator = existingGenerator || (formatKey ? LABELING_FORMATS[formatKey].generator : getLabelGenerator(questionIndex, 'level1'));
      const nextId = generator(subQs.length);
      newQuestions[questionIndex].sub_questions = [
        ...subQs,
        { sub_id: nextId, max_marks: 2, rubric: "", sub_parts: [] }
      ];
      return { ...prev, questions: newQuestions };
    });
  };

  const updateSubQuestion = (questionIndex, subIndex, field, value) => {
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      newQuestions[questionIndex].sub_questions[subIndex][field] = value;
      return { ...prev, questions: newQuestions };
    });
  };

  const removeSubQuestion = (questionIndex, subIndex) => {
    const generator = getLabelGenerator(questionIndex, 'level1');
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      newQuestions[questionIndex].sub_questions = newQuestions[questionIndex].sub_questions
        .filter((_, i) => i !== subIndex)
        .map((sq, i) => ({ ...sq, sub_id: generator(i) }));
      return { ...prev, questions: newQuestions };
    });
  };

  // Roman numeral converter for sub-sub-questions (kept for backwards compatibility)
  const toRoman = (num) => {
    const romanNumerals = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'];
    return romanNumerals[num] || `${num + 1}`;
  };

  // Add sub-sub-question with format support
  const addSubSubQuestion = (questionIndex, subIndex) => {
    const generator = getLabelGenerator(questionIndex, 'level2');
    addSubSubQuestionWithFormat(questionIndex, subIndex, null, generator);
  };

  const addSubSubQuestionWithFormat = (questionIndex, subIndex, formatKey = null, existingGenerator = null) => {
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      const subParts = newQuestions[questionIndex].sub_questions[subIndex].sub_parts || [];
      const generator = existingGenerator || (formatKey ? LABELING_FORMATS[formatKey].generator : getLabelGenerator(questionIndex, 'level2'));
      const nextId = generator(subParts.length);
      newQuestions[questionIndex].sub_questions[subIndex].sub_parts = [
        ...subParts,
        { part_id: nextId, max_marks: 1, rubric: "", sub_parts: [] }
      ];
      return { ...prev, questions: newQuestions };
    });
  };

  // Update sub-sub-question
  const updateSubSubQuestion = (questionIndex, subIndex, partIndex, field, value) => {
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      newQuestions[questionIndex].sub_questions[subIndex].sub_parts[partIndex][field] = value;
      return { ...prev, questions: newQuestions };
    });
  };

  // Remove sub-sub-question
  const removeSubSubQuestion = (questionIndex, subIndex, partIndex) => {
    const generator = getLabelGenerator(questionIndex, 'level2');
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      newQuestions[questionIndex].sub_questions[subIndex].sub_parts = 
        newQuestions[questionIndex].sub_questions[subIndex].sub_parts
          .filter((_, i) => i !== partIndex)
          .map((sp, i) => ({ ...sp, part_id: generator(i) }));
      return { ...prev, questions: newQuestions };
    });
  };

  // Add level 3 sub-part with format support
  const addLevel3Part = (questionIndex, subIndex, partIndex) => {
    const generator = getLabelGenerator(questionIndex, 'level3');
    addLevel3PartWithFormat(questionIndex, subIndex, partIndex, null, generator);
  };

  const addLevel3PartWithFormat = (questionIndex, subIndex, partIndex, formatKey = null, existingGenerator = null) => {
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      const level3Parts = newQuestions[questionIndex].sub_questions[subIndex].sub_parts[partIndex].sub_parts || [];
      const generator = existingGenerator || (formatKey ? LABELING_FORMATS[formatKey].generator : getLabelGenerator(questionIndex, 'level3'));
      const nextId = generator(level3Parts.length);
      newQuestions[questionIndex].sub_questions[subIndex].sub_parts[partIndex].sub_parts = [
        ...level3Parts,
        { part_id: nextId, max_marks: 0.5, rubric: "" }
      ];
      return { ...prev, questions: newQuestions };
    });
  };

  // Update level 3 part
  const updateLevel3Part = (questionIndex, subIndex, partIndex, level3Index, field, value) => {
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      newQuestions[questionIndex].sub_questions[subIndex].sub_parts[partIndex].sub_parts[level3Index][field] = value;
      return { ...prev, questions: newQuestions };
    });
  };

  // Remove level 3 part
  const removeLevel3Part = (questionIndex, subIndex, partIndex, level3Index) => {
    const generator = getLabelGenerator(questionIndex, 'level3');
    setFormData(prev => {
      const newQuestions = [...prev.questions];
      newQuestions[questionIndex].sub_questions[subIndex].sub_parts[partIndex].sub_parts = 
        newQuestions[questionIndex].sub_questions[subIndex].sub_parts[partIndex].sub_parts
          .filter((_, i) => i !== level3Index)
          .map((sp, i) => ({ ...sp, part_id: generator(i) }));
      return { ...prev, questions: newQuestions };
    });
  };

  // Model answer dropzone
  const onModelAnswerDrop = useCallback((acceptedFiles) => {
    if (acceptedFiles.length > 0) {
      setModelAnswerFile(acceptedFiles[0]);
      setPaperUploaded(true);
    }
  }, []);

  const removeModelAnswerFile = (e) => {
    e.stopPropagation();
    setModelAnswerFile(null);
    // Only reset paperUploaded if question paper is also not uploaded
    if (!questionPaperFile) {
      setPaperUploaded(false);
    }
  };

  const { getRootProps: getModelRootProps, getInputProps: getModelInputProps, isDragActive: isModelDragActive } = useDropzone({
    onDrop: onModelAnswerDrop,
    accept: { 
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/msword': ['.doc'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'application/zip': ['.zip']
    },
    maxFiles: 1
  });

  // Question paper dropzone
  const onQuestionPaperDrop = useCallback((acceptedFiles) => {
    if (acceptedFiles.length > 0) {
      setQuestionPaperFile(acceptedFiles[0]);
      setPaperUploaded(true);
    }
  }, []);

  const removeQuestionPaperFile = (e) => {
    e.stopPropagation();
    setQuestionPaperFile(null);
    // Only reset paperUploaded if model answer is also not uploaded
    if (!modelAnswerFile) {
      setPaperUploaded(false);
    }
  };

  const { getRootProps: getQuestionRootProps, getInputProps: getQuestionInputProps, isDragActive: isQuestionDragActive } = useDropzone({
    onDrop: onQuestionPaperDrop,
    accept: { 
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/msword': ['.doc'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'application/zip': ['.zip']
    },
    maxFiles: 1
  });

  // Student papers dropzone
  const onStudentPapersDrop = useCallback((acceptedFiles) => {
    setStudentFiles(prev => [...prev, ...acceptedFiles]);
  }, []);

  const { getRootProps: getStudentRootProps, getInputProps: getStudentInputProps, isDragActive: isStudentDragActive } = useDropzone({
    onDrop: onStudentPapersDrop,
    accept: { 
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/msword': ['.doc'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'application/zip': ['.zip']  // ZIP for bulk upload
    },
    multiple: true,
    maxFiles: 50  // Allow up to 50 files or 1 ZIP
  });

  const removeStudentFile = (index) => {
    setStudentFiles(prev => prev.filter((_, i) => i !== index));
  };

  const createSubject = async (name) => {
    try {
      const response = await axios.post(`${API}/subjects`, { name });
      setSubjects(prev => [...prev, response.data]);
      handleInputChange("subject_id", response.data.subject_id);
      toast.success("Subject created");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to create subject");
    }
  };

  const createBatch = async (name) => {
    try {
      const response = await axios.post(`${API}/batches`, { name });
      setBatches(prev => [...prev, response.data]);
      handleInputChange("batch_id", response.data.batch_id);
      toast.success("Batch created");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to create batch");
    }
  };

  const handleSaveQuestionsAndContinue = async () => {
    if (!examId) {
      toast.error("Exam ID not found");
      return;
    }

    setLoading(true);
    try {
      // Update exam with configured questions and grading mode
      await axios.put(`${API}/exams/${examId}`, {
        questions: formData.questions,
        grading_mode: formData.grading_mode
      });
      
      toast.success("Questions saved successfully");
      setStep(5);
    } catch (error) {
      console.error("Error saving questions:", error);
      toast.error(error.response?.data?.detail || "Failed to save questions");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateExam = async () => {
    // If exam already created, just move to next step
    if (examId) {
      setStep(2);
      return;
    }
    
    setLoading(true);
    try {
      const response = await axios.post(`${API}/exams`, formData);
      const newExamId = response.data.exam_id;
      setExamId(newExamId);
      
      // Save to localStorage immediately
      localStorage.setItem('uploadGradeState', JSON.stringify({
        step: 2,
        examId: newExamId,
        activeJobId: null,
        formData: formData,
        timestamp: Date.now()
      }));
      
      toast.success("Exam configuration saved");
      setStep(2);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to create exam");
    } finally {
      setLoading(false);
    }
  };

  const handleUploadModelAnswer = async () => {
    if (!examId) {
      toast.error("Exam ID not found. Please go back to Step 1 and create the exam first.");
      return;
    }

    // Both uploads are now optional - questions will be extracted from student papers if needed
    setLoading(true);
    try {
      // Upload question paper if a new file is selected (optional)
      if (questionPaperFile) {
        const qpFormData = new FormData();
        qpFormData.append("file", questionPaperFile);
        const qpResponse = await axios.post(`${API}/exams/${examId}/upload-question-paper`, qpFormData, {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 900000  // 15 minutes for large document processing
        });

        // Show auto-extraction result
        if (qpResponse.data.auto_extracted) {
          toast.success(`✨ Question paper uploaded & ${qpResponse.data.extracted_count} questions auto-extracted!`);
        } else {
          toast.success("Question paper uploaded");
        }

        setPaperUploaded(true);
      }

      // Upload model answer if provided (optional)
      if (modelAnswerFile) {
        const formData = new FormData();
        formData.append("file", modelAnswerFile);
        const maResponse = await axios.post(`${API}/exams/${examId}/upload-model-answer`, formData, {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 900000  // 15 minutes for large document processing
        });

        // Show auto-extraction result
        if (maResponse.data.auto_extracted) {
          toast.success(`✨ Model answer uploaded & ${maResponse.data.extracted_count} answers auto-extracted!`);
        } else {
          toast.success("Model answer uploaded");
        }

        setPaperUploaded(true);
      }

      setStep(3);
    } catch (error) {
      console.error("Error:", error);
      toast.error(error.response?.data?.detail || "Failed to upload files");
    } finally {
      setLoading(false);
    }
  };

  const handleCancelGrading = async () => {
    if (!activeJobId) {
      toast.error("No active grading job found");
      return;
    }

    if (!confirm("Are you sure you want to cancel this grading job? This cannot be undone.")) {
      return;
    }

    try {
      await axios.post(`${API}/grading-jobs/${activeJobId}/cancel`, {}, {
        withCredentials: true
      });
      
      toast.success("Grading cancelled successfully");
      
      // Clear polling
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      
      // Reset state
      setProcessing(false);
      setActiveJobId(null);
      setProcessingProgress(0);
      localStorage.removeItem('activeGradingJob');
      localStorage.removeItem('uploadGradeState');
      
    } catch (error) {
      console.error("Error cancelling grading:", error);
      toast.error(error.response?.data?.detail || "Failed to cancel grading");
    }
  };

  const handleStartGrading = async () => {
    if (studentFiles.length === 0 || !examId) return;
    
    setProcessing(true);
    setProcessingProgress(0);
    
    try {
      const formDataObj = new FormData();
      studentFiles.forEach(file => {
        formDataObj.append("files", file);
      });
      
      // Start background grading job - returns immediately
      const response = await axios.post(`${API}/exams/${examId}/grade-papers-bg`, formDataObj, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 300000  // 5 minutes - enough time to upload and read 30+ large files
      });
      
      const { job_id, total_papers } = response.data;
      setActiveJobId(job_id);
      
      // Save to BOTH localStorage keys for cross-page access
      localStorage.setItem('activeGradingJob', JSON.stringify({
        job_id,
        exam_id: examId,
        total_papers: studentFiles.length,
        started_at: Date.now()
      }));
      
      localStorage.setItem('uploadGradeState', JSON.stringify({
        step: 5,
        examId: examId,
        activeJobId: job_id,
        formData: formData,
        timestamp: Date.now()
      }));
      
      console.log('Grading job started:', job_id);
      console.log('Saved to localStorage - activeGradingJob and uploadGradeState');
      
      toast.success(`Grading started for ${total_papers} papers. Processing in background...`);
      
      // Start polling using centralized function
      startPollingJob(job_id);
      
    } catch (error) {
      toast.error("Failed to start grading: " + (error.response?.data?.detail || error.message));
      setProcessing(false);
    }
  };

  const handleReset = async () => {
    try {
      // If there's an active job, cancel it on the backend
      if (activeJobId) {
        try {
          await axios.post(`${API}/grading-jobs/${activeJobId}/cancel`, {}, {
            withCredentials: true
          });
          console.log(`Cancelled job ${activeJobId}`);
        } catch (error) {
          console.error('Error cancelling job:', error);
          // Continue with reset even if cancel fails
        }
      }

      // Clear polling interval
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }

      // Clear localStorage
      localStorage.removeItem('activeGradingJob');
      localStorage.removeItem('uploadGradeState');

      // Reset all state to initial values
      setStep(1);
      setFormData({
        batch_id: "",
        subject_id: "",
        exam_type: "",
        exam_name: "",
        total_marks: 100,
        exam_date: new Date().toISOString().split("T")[0],
        grading_mode: "balanced",
        questions: [{ question_number: 1, max_marks: 10, rubric: "", sub_questions: [] }]
      });
      setModelAnswerFile(null);
      setQuestionPaperFile(null);
      setStudentFiles([]);
      setExamId(null);
      setResults(null);
      setActiveJobId(null);
      setProcessing(false);
      setProcessingProgress(0);
      setLoading(false);
      setQuestionsSkipped(false);
      setShowManualEntry(false);
      setPaperUploaded(false);
      setLabelFormats({});

      // Close the dialog
      setResetDialogOpen(false);

      toast.success("Reset complete. You can start fresh!");
    } catch (error) {
      console.error('Error during reset:', error);
      toast.error("Error during reset, but state has been cleared");
      setResetDialogOpen(false);
    }
  };

  const handleChangeQuestionMethod = () => {
    // If user has manually entered questions with data, show confirmation
    const hasManualQuestions = showManualEntry && formData.questions.length > 0 && 
      formData.questions.some(q => q.max_marks > 0 || q.rubric || q.sub_questions?.length > 0);
    
    if (hasManualQuestions) {
      setChangeMethodDialogOpen(true);
    } else {
      // No data to lose, just reset
      confirmChangeMethod();
    }
  };

  const confirmChangeMethod = () => {
    setShowManualEntry(false);
    setQuestionsSkipped(false);
    // Reset questions to default single question
    setFormData(prev => ({
      ...prev,
      questions: [{ question_number: 1, max_marks: 10, rubric: "", sub_questions: [] }]
    }));
    setChangeMethodDialogOpen(false);
    toast.info("Question configuration method changed. You can select a new option.");
  };

  const renderStepIndicator = () => (
    <div className="flex items-center justify-center gap-1 lg:gap-2 mb-6 lg:mb-8 overflow-x-auto pb-2">
      {[1, 2, 3, 4, 5, 6].map((s) => (
        <div key={s} className="flex items-center flex-shrink-0">
          <div 
            className={`w-6 h-6 lg:w-8 lg:h-8 rounded-full flex items-center justify-center text-xs lg:text-sm font-medium transition-all ${
              s < step ? "bg-green-500 text-white" :
              s === step ? "bg-primary text-white" :
              "bg-muted text-muted-foreground"
            }`}
          >
            {s < step ? <CheckCircle className="w-3 h-3 lg:w-5 lg:h-5" /> : s}
          </div>
          {s < 6 && (
            <div className={`w-4 lg:w-8 h-0.5 lg:h-1 mx-0.5 lg:mx-1 ${s < step ? "bg-green-500" : "bg-muted"}`} />
          )}
        </div>
      ))}
    </div>
  );

  return (
    <Layout user={user}>
      <div className="max-w-4xl mx-auto px-0 lg:px-4" data-testid="upload-grade-page">
        {/* Header with Reset Button */}
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl lg:text-3xl font-bold">Upload & Grade</h1>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setResetDialogOpen(true)}
            className="text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            Reset
          </Button>
        </div>

        {renderStepIndicator()}

        {/* Step 1: Exam Configuration */}
        {step === 1 && (
          <Card className="animate-fade-in">
            <CardHeader>
              <CardTitle>Step 1: Exam Configuration</CardTitle>
              <CardDescription>Set up the basic details for this exam</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 lg:gap-4">
                <div className="space-y-2">
                  <Label>Batch/Class *</Label>
                  <Select 
                    value={formData.batch_id} 
                    onValueChange={(v) => handleInputChange("batch_id", v)}
                  >
                    <SelectTrigger data-testid="batch-select">
                      <SelectValue placeholder="Select batch" />
                    </SelectTrigger>
                    <SelectContent>
                      {batches.map(batch => (
                        <SelectItem key={batch.batch_id} value={batch.batch_id}>
                          {batch.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button 
                    variant="link" 
                    size="sm" 
                    className="p-0 h-auto text-primary"
                    onClick={() => {
                      const name = prompt("Enter batch name:");
                      if (name) createBatch(name);
                    }}
                  >
                    <Plus className="w-3 h-3 mr-1" /> Add new batch
                  </Button>
                </div>

                <div className="space-y-2">
                  <Label>Subject *</Label>
                  <Select 
                    value={formData.subject_id} 
                    onValueChange={(v) => handleInputChange("subject_id", v)}
                  >
                    <SelectTrigger data-testid="subject-select">
                      <SelectValue placeholder="Select subject" />
                    </SelectTrigger>
                    <SelectContent>
                      {subjects.map(subject => (
                        <SelectItem key={subject.subject_id} value={subject.subject_id}>
                          {subject.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button 
                    variant="link" 
                    size="sm" 
                    className="p-0 h-auto text-primary"
                    onClick={() => {
                      const name = prompt("Enter subject name:");
                      if (name) createSubject(name);
                    }}
                  >
                    <Plus className="w-3 h-3 mr-1" /> Add new subject
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 lg:gap-4">
                <div className="space-y-2">
                  <Label>Exam Type *</Label>
                  <Select 
                    value={formData.exam_type} 
                    onValueChange={(v) => handleInputChange("exam_type", v)}
                  >
                    <SelectTrigger data-testid="exam-type-select">
                      <SelectValue placeholder="Select type" />
                    </SelectTrigger>
                    <SelectContent>
                      {EXAM_TYPES.map(type => (
                        <SelectItem key={type} value={type}>{type}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Exam Name *</Label>
                  <Input 
                    placeholder="e.g., Physics Mid-Term October 2024"
                    value={formData.exam_name}
                    onChange={(e) => handleInputChange("exam_name", e.target.value)}
                    data-testid="exam-name-input"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 lg:gap-4">
                <div className="space-y-2">
                  <Label>Total Marks *</Label>
                  <Input 
                    type="number"
                    value={formData.total_marks}
                    onChange={(e) => handleInputChange("total_marks", parseFloat(e.target.value))}
                    data-testid="total-marks-input"
                  />
                  <p className="text-xs text-muted-foreground">
                    This will be used as the exam&apos;s total marks. Auto-extracted marks will not override this value.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label>Date of Exam</Label>
                  <Input 
                    type="date"
                    value={formData.exam_date}
                    onChange={(e) => handleInputChange("exam_date", e.target.value)}
                    data-testid="exam-date-input"
                  />
                </div>
              </div>

              <div className="flex justify-end pt-4">
                <Button 
                  onClick={handleCreateExam}
                  disabled={!formData.batch_id || !formData.subject_id || !formData.exam_name || loading}
                  data-testid="create-exam-btn"
                >
                  {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  Continue to Upload Files
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 2: Upload Question Paper & Model Answer */}
        {step === 2 && (
          <Card className="animate-fade-in">
            <CardHeader>
              <CardTitle>Step 2: Upload Question Paper & Model Answer</CardTitle>
              <CardDescription>Upload the question paper and/or model answer for better AI grading (Questions will be auto-extracted)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Question Paper Upload */}
              <div>
                <Label className="text-sm font-medium mb-2 block">Question Paper (Optional)</Label>
                <div 
                  {...getQuestionRootProps()} 
                  className={`dropzone upload-zone p-6 text-center border-2 border-dashed rounded-xl ${isQuestionDragActive ? "border-blue-500 bg-blue-50" : "border-gray-300"}`}
                  data-testid="question-paper-dropzone"
                >
                  <input {...getQuestionInputProps()} />
                  {questionPaperFile ? (
                    <div className="flex items-center justify-center gap-3">
                      <FileText className="w-6 h-6 text-blue-600" />
                      <div className="text-left">
                        <p className="font-medium text-sm">{questionPaperFile.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {(questionPaperFile.size / 1024 / 1024).toFixed(2)} MB
                        </p>
                      </div>
                      <Button 
                        variant="ghost" 
                        size="icon"
                        onClick={removeQuestionPaperFile}
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </div>
                  ) : (
                    <>
                      <Upload className="w-8 h-8 mx-auto text-blue-400 mb-2" />
                      <p className="font-medium text-sm">Drop question paper here</p>
                      <p className="text-xs text-muted-foreground mt-1">PDF, Word, Images, or ZIP • Questions auto-extracted</p>
                    </>
                  )}
                </div>
              </div>

              {/* Model Answer Upload */}
              <div>
                <Label className="text-sm font-medium mb-2 block">Model Answer (Optional)</Label>
                
                <div 
                  {...getModelRootProps()} 
                  className={`dropzone upload-zone p-6 text-center border-2 border-dashed rounded-xl ${isModelDragActive ? "border-primary bg-primary/5" : "border-gray-300"}`}
                  data-testid="model-answer-dropzone"
                >
                  <input {...getModelInputProps()} />
                  {modelAnswerFile ? (
                    <div className="flex items-center justify-center gap-3">
                      <FileText className="w-6 h-6 text-primary" />
                      <div className="text-left">
                        <p className="font-medium text-sm">{modelAnswerFile.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {(modelAnswerFile.size / 1024 / 1024).toFixed(2)} MB
                        </p>
                      </div>
                      <Button 
                        variant="ghost" 
                        size="icon"
                        onClick={removeModelAnswerFile}
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </div>
                  ) : (
                    <>
                      <Upload className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
                      <p className="font-medium text-sm">Drop model answer here</p>
                      <p className="text-xs text-muted-foreground mt-1">PDF, Word, Images, or ZIP • Used for AI grading</p>
                    </>
                  )}
                </div>
              </div>

              <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                <p className="text-sm text-blue-800">
                  <strong>💡 Tip:</strong> Both uploads are optional! If neither is uploaded, questions will be automatically extracted from student answer papers. Model answer improves AI grading accuracy.
                </p>
              </div>
              <div className="flex justify-between pt-4">
                <Button variant="outline" onClick={() => setStep(1)}>
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Back
                </Button>
                <Button 
                  onClick={handleUploadModelAnswer} 
                  disabled={loading}
                  data-testid="upload-model-btn"
                >
                  {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  Upload & Continue
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 3: Grading Mode Selection - FIXED */}
        {step === 3 && (
          <Card className="animate-fade-in">
            <CardHeader>
              <CardTitle>Step 3: Select Grading Mode</CardTitle>
              <CardDescription>Choose how strictly the AI should grade the papers</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {GRADING_MODES.map((mode) => (
                  <div 
                    key={mode.id}
                    onClick={() => handleInputChange("grading_mode", mode.id)}
                    className={`p-4 border-2 rounded-xl cursor-pointer transition-all ${mode.color} ${
                      formData.grading_mode === mode.id 
                        ? "ring-2 ring-primary ring-offset-2 border-primary" 
                        : "hover:border-gray-400"
                    }`}
                    data-testid={`grading-mode-${mode.id}`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2">
                        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                          formData.grading_mode === mode.id 
                            ? "border-primary bg-primary" 
                            : "border-gray-400"
                        }`}>
                          {formData.grading_mode === mode.id && (
                            <div className="w-2 h-2 bg-white rounded-full" />
                          )}
                        </div>
                        <h3 className="font-semibold">{mode.name}</h3>
                      </div>
                      {mode.recommended && (
                        <Badge variant="secondary" className="text-xs bg-white">Recommended</Badge>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mt-2 ml-6">{mode.description}</p>
                  </div>
                ))}
              </div>

              <div className="p-4 bg-orange-50 border border-orange-200 rounded-lg">
                <p className="text-sm text-orange-800">
                  <strong>Selected:</strong> {GRADING_MODES.find(m => m.id === formData.grading_mode)?.name || "Balanced Mode"}
                </p>
                <p className="text-xs text-orange-700 mt-1">
                  {GRADING_MODES.find(m => m.id === formData.grading_mode)?.description}
                </p>
              </div>

              <div className="flex justify-between pt-4">
                <Button variant="outline" onClick={() => setStep(2)}>
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Back
                </Button>
                <Button 
                  onClick={() => setStep(4)} 
                  disabled={!formData.grading_mode}
                  data-testid="continue-to-questions-btn"
                >
                  Continue to Questions
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 4: Question Configuration with Sub-questions */}
        {step === 4 && (
          <Card className="animate-fade-in">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <CardTitle>Step 4: Question Configuration</CardTitle>
                  <CardDescription>
                    {showManualEntry || questionsSkipped
                      ? "Define the questions and marks distribution. Add sub-questions like 1a, 1b if needed."
                      : "Choose how you want to configure questions for this exam."}
                  </CardDescription>
                </div>
                {(showManualEntry || questionsSkipped) && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleChangeQuestionMethod}
                    className="ml-4"
                  >
                    <ArrowLeft className="w-4 h-4 mr-2" />
                    Change Method
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {!showManualEntry && !questionsSkipped && (
                <div className="space-y-6">
                  <div className="text-center py-8">
                    <h3 className="text-lg font-semibold mb-4">How would you like to add questions?</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl mx-auto">
                      <Card className="p-6 cursor-pointer hover:border-primary transition-colors" onClick={() => setShowManualEntry(true)}>
                        <div className="text-center space-y-3">
                          <div className="h-12 w-12 mx-auto bg-blue-100 rounded-full flex items-center justify-center">
                            <Plus className="h-6 w-6 text-blue-600" />
                          </div>
                          <h4 className="font-semibold">Enter Manually</h4>
                          <p className="text-sm text-muted-foreground">
                            Manually configure questions, marks, and sub-questions now
                          </p>
                        </div>
                      </Card>
                      
                      <Card className="p-6 cursor-pointer hover:border-primary transition-colors" 
                        onClick={async () => {
                          setQuestionsSkipped(true);
                          setFormData(prev => ({...prev, questions: []}));
                          // Auto-advance to Step 5 when auto-extract is chosen
                          await handleSaveQuestionsAndContinue();
                        }}
                      >
                        <div className="text-center space-y-3">
                          <div className="h-12 w-12 mx-auto bg-green-100 rounded-full flex items-center justify-center">
                            <CheckCircle className="h-6 w-6 text-green-600" />
                          </div>
                          <h4 className="font-semibold">Auto-Extract from Papers</h4>
                          <p className="text-sm text-muted-foreground">
                            Questions will be automatically extracted from uploaded question paper or model answer
                          </p>
                          <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200">
                            Recommended
                          </Badge>
                        </div>
                      </Card>
                    </div>
                  </div>

                  {paperUploaded ? (
                    <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
                      <p className="text-sm text-green-800">
                        <CheckCircle className="inline h-4 w-4 mr-2" />
                        <strong>Paper uploaded!</strong> Questions will be extracted automatically. You can edit them later in Manage Exams.
                      </p>
                    </div>
                  ) : (
                    <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                      <p className="text-sm text-yellow-800">
                        <AlertCircle className="inline h-4 w-4 mr-2" />
                        <strong>Note:</strong> Make sure to upload question paper or model answer in Step 2 for auto-extraction to work.
                      </p>
                    </div>
                  )}
                  
                  <div className="flex justify-between pt-4 border-t">
                    <Button variant="outline" onClick={() => setStep(3)}>
                      <ArrowLeft className="w-4 h-4 mr-2" />
                      Back
                    </Button>
                    {questionsSkipped && (
                      <Button onClick={handleSaveQuestionsAndContinue} disabled={loading}>
                        {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                        Continue to Upload Papers
                        <ArrowRight className="w-4 h-4 ml-2" />
                      </Button>
                    )}
                  </div>
                </div>
              )}
              
              {showManualEntry && (
              <div>
              {formData.questions.map((question, index) => (
                <div key={index} className="p-4 bg-muted/50 rounded-lg space-y-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 grid grid-cols-1 sm:grid-cols-3 gap-3">
                      <div className="space-y-2">
                        <Label>Question #{question.question_number}</Label>
                        <Input value={`Q${question.question_number}`} disabled />
                      </div>
                      <div className="space-y-2">
                        <Label>Max Marks</Label>
                        <Input 
                          type="number"
                          value={question.max_marks}
                          onChange={(e) => updateQuestion(index, "max_marks", parseFloat(e.target.value))}
                          data-testid={`question-${index}-marks`}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Rubric (Optional)</Label>
                        <Input 
                          placeholder="Grading criteria..."
                          value={(() => {
                            let rubric = question.rubric;
                            // Handle nested object structure
                            if (typeof rubric === 'object' && rubric !== null) {
                              rubric = rubric.rubric || rubric.question_text || "";
                            }
                            return typeof rubric === 'string' ? rubric : String(rubric || '');
                          })()}
                          onChange={(e) => updateQuestion(index, "rubric", e.target.value)}
                        />
                      </div>
                    </div>
                    {formData.questions.length > 1 && (
                      <Button 
                        variant="ghost" 
                        size="icon"
                        onClick={() => removeQuestion(index)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    )}
                  </div>

                  {/* Sub-questions - Level 1: a), b), c) */}
                  {question.sub_questions?.length > 0 && (
                    <div className="pl-4 border-l-2 border-primary/30 space-y-3 mt-2">
                      <Label className="text-sm text-muted-foreground font-medium">Sub-questions:</Label>
                      {question.sub_questions.map((subQ, subIndex) => (
                        <div key={subIndex} className="space-y-2">
                          {/* Sub-question row (a, b, c) */}
                          <div className="flex items-center gap-2 bg-blue-50 p-2 rounded border border-blue-100">
                            <span className="text-sm font-semibold text-blue-700 w-12">{subQ.sub_id})</span>
                            <Input 
                              type="number"
                              placeholder="Marks"
                              value={subQ.max_marks}
                              onChange={(e) => updateSubQuestion(index, subIndex, "max_marks", parseFloat(e.target.value) || 0)}
                              className="w-20 h-8 text-sm"
                            />
                            <Input 
                              placeholder="Rubric (optional)"
                              value={subQ.rubric || ""}
                              onChange={(e) => updateSubQuestion(index, subIndex, "rubric", e.target.value)}
                              className="flex-1 h-8 text-sm"
                            />
                            <Button 
                              variant="ghost" 
                              size="sm"
                              className="h-7 text-xs text-purple-600 hover:text-purple-700"
                              onClick={() => handleAddSubQuestionClick(index, 'level2', subIndex)}
                            >
                              <Plus className="w-3 h-3 mr-1" />
                              {labelFormats[index]?.level2 ? LABELING_FORMATS[labelFormats[index].level2].name : "i, ii..."}
                            </Button>
                            <Button 
                              variant="ghost" 
                              size="icon"
                              className="h-7 w-7 text-red-500 hover:text-red-700"
                              onClick={() => removeSubQuestion(index, subIndex)}
                            >
                              <X className="w-3 h-3" />
                            </Button>
                          </div>

                          {/* Sub-sub-questions - Level 2: i), ii), iii) */}
                          {subQ.sub_parts?.length > 0 && (
                            <div className="pl-6 border-l-2 border-purple-200 space-y-2 ml-4">
                              {subQ.sub_parts.map((part, partIndex) => (
                                <div key={partIndex} className="space-y-2">
                                  <div className="flex items-center gap-2 bg-purple-50 p-2 rounded border border-purple-100">
                                    <span className="text-sm font-medium text-purple-700 w-10">{part.part_id})</span>
                                    <Input 
                                      type="number"
                                      placeholder="Marks"
                                      value={part.max_marks}
                                      onChange={(e) => updateSubSubQuestion(index, subIndex, partIndex, "max_marks", parseFloat(e.target.value) || 0)}
                                      className="w-16 h-7 text-xs"
                                    />
                                    <Input 
                                      placeholder="Rubric"
                                      value={part.rubric || ""}
                                      onChange={(e) => updateSubSubQuestion(index, subIndex, partIndex, "rubric", e.target.value)}
                                      className="flex-1 h-7 text-xs"
                                    />
                                    <Button 
                                      variant="ghost" 
                                      size="sm"
                                      className="h-6 text-xs text-green-600 hover:text-green-700"
                                      onClick={() => handleAddSubQuestionClick(index, 'level3', subIndex, partIndex)}
                                    >
                                      <Plus className="w-2 h-2 mr-1" />
                                      {labelFormats[index]?.level3 ? LABELING_FORMATS[labelFormats[index].level3].name : "A, B..."}
                                    </Button>
                                    <Button 
                                      variant="ghost" 
                                      size="icon"
                                      className="h-6 w-6 text-red-400 hover:text-red-600"
                                      onClick={() => removeSubSubQuestion(index, subIndex, partIndex)}
                                    >
                                      <X className="w-3 h-3" />
                                    </Button>
                                  </div>

                                  {/* Level 3: A), B), C) */}
                                  {part.sub_parts?.length > 0 && (
                                    <div className="pl-6 border-l-2 border-green-200 space-y-1 ml-4">
                                      {part.sub_parts.map((level3, level3Index) => (
                                        <div key={level3Index} className="flex items-center gap-2 bg-green-50 p-1.5 rounded border border-green-100">
                                          <span className="text-xs font-medium text-green-700 w-8">{level3.part_id})</span>
                                          <Input 
                                            type="number"
                                            placeholder="Marks"
                                            value={level3.max_marks}
                                            onChange={(e) => updateLevel3Part(index, subIndex, partIndex, level3Index, "max_marks", parseFloat(e.target.value) || 0)}
                                            className="w-14 h-6 text-xs"
                                          />
                                          <Input 
                                            placeholder="Rubric"
                                            value={level3.rubric || ""}
                                            onChange={(e) => updateLevel3Part(index, subIndex, partIndex, level3Index, "rubric", e.target.value)}
                                            className="flex-1 h-6 text-xs"
                                          />
                                          <Button 
                                            variant="ghost" 
                                            size="icon"
                                            className="h-5 w-5 text-red-400 hover:text-red-600"
                                            onClick={() => removeLevel3Part(index, subIndex, partIndex, level3Index)}
                                          >
                                            <X className="w-2 h-2" />
                                          </Button>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  
                  <Button 
                    variant="outline" 
                    size="sm"
                    onClick={() => handleAddSubQuestionClick(index, 'level1')}
                    className="text-xs mt-2"
                  >
                    <Plus className="w-3 h-3 mr-1" />
                    Add Sub-question ({labelFormats[index]?.level1 ? LABELING_FORMATS[labelFormats[index].level1].name : "a, b, c..."})
                  </Button>
                </div>
              ))}

              <Button 
                variant="outline" 
                onClick={addQuestion}
                data-testid="add-question-btn"
                className="w-full"
              >
                <Plus className="w-4 h-4 mr-2" />
                Add Question
              </Button>

              <div className="flex justify-between pt-4 border-t">
                <Button variant="outline" onClick={() => setStep(3)}>
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Back
                </Button>
                <Button 
                  onClick={handleSaveQuestionsAndContinue} 
                  disabled={loading}
                  data-testid="save-questions-btn"
                >
                  {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  Save & Continue to Upload Papers
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </div>
              </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Step 5: Upload Student Papers */}
        {step === 5 && (
          <Card className="animate-fade-in">
            <CardHeader>
              <CardTitle>Step 5: Upload Student Papers</CardTitle>
              <CardDescription>Upload student answer sheets for grading</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Info: Model answer/question paper is optional */}
              {!paperUploaded && (
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                    <div className="space-y-2">
                      <p className="text-sm font-medium text-blue-900">ℹ️ Optional: Model Answer/Question Paper</p>
                      <p className="text-sm text-blue-800">
                        You can proceed without uploading a <strong>Question Paper</strong> or <strong>Model Answer</strong>. The AI can extract questions directly from student answer papers.
                      </p>
                      <p className="text-xs text-blue-700 mt-1">
                        💡 <strong>Tip:</strong> Upload a model answer for more accurate grading, or let AI extract questions from the first student paper.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {(formData.questions.length === 0 && !questionsSkipped) && paperUploaded && (
                <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
                    <div className="space-y-2">
                      <p className="text-sm font-medium text-yellow-900">⚠️ No Questions Defined</p>
                      <p className="text-sm text-yellow-800">
                        Questions should be auto-extracted from the uploaded paper. If extraction failed, you can add them manually in Step 4 or after exam creation.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Always show student papers upload area - removed paperUploaded condition */}
              <>
              {/* File Format Instructions */}
              <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-blue-900">✨ Smart Student Identification</p>
                    <p className="text-sm text-blue-800">
                      Our AI automatically extracts student ID and name from the answer sheet!
                    </p>
                    <p className="text-xs text-blue-700 mt-2">
                      <strong>Important:</strong> Students must write their <strong>Roll Number/Student ID</strong> and <strong>Name</strong> clearly at the top of their answer sheet.
                    </p>
                    <p className="text-xs text-blue-700 mt-2">
                      <strong>Supported ID formats:</strong><br/>
                      • Numbers only: <code className="px-1.5 py-0.5 bg-blue-100 rounded text-xs">123</code>, <code className="px-1.5 py-0.5 bg-blue-100 rounded text-xs">2024001</code><br/>
                      • Alphanumeric: <code className="px-1.5 py-0.5 bg-blue-100 rounded text-xs">STU001</code>, <code className="px-1.5 py-0.5 bg-blue-100 rounded text-xs">CS-2024-42</code>
                    </p>
                    <p className="text-xs text-blue-700 mt-2">
                      📝 <strong>Optional:</strong> You can name files as <code className="px-1.5 py-0.5 bg-blue-100 rounded">StudentName.pdf</code> as a fallback (e.g., <code className="px-1.5 py-0.5 bg-blue-100 rounded">John_Doe.pdf</code>)
                    </p>
                    <p className="text-xs text-blue-700 mt-1">
                      ✓ Students will be auto-created and added to this exam&apos;s batch
                    </p>
                  </div>
                </div>
              </div>

              <div 
                {...getStudentRootProps()} 
                className={`dropzone upload-zone p-8 text-center border-2 border-dashed rounded-xl ${isStudentDragActive ? "border-primary bg-primary/5" : "border-gray-300"}`}
                data-testid="student-papers-dropzone"
              >
                <input {...getStudentInputProps()} />
                <Upload className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
                <p className="font-medium">Drop student answer papers here</p>
                <p className="text-sm text-muted-foreground mt-1">
                  PDF, Word, Images, ZIP • Multiple files allowed
                </p>
              </div>

              {studentFiles.length > 0 && (
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {studentFiles.map((file, index) => (
                    <div key={index} className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                      <div className="flex items-center gap-3">
                        <FileText className="w-5 h-5 text-primary" />
                        <span className="text-sm font-medium">{file.name}</span>
                      </div>
                      <Button 
                        variant="ghost" 
                        size="icon"
                        onClick={() => removeStudentFile(index)}
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}

              {processing && (
                <div className="space-y-3 p-4 bg-blue-50 rounded-lg border border-blue-200">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
                      <span className="font-medium text-blue-900">Processing papers...</span>
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
                  <Progress value={processingProgress} className="h-2" />
                  <p className="text-sm text-blue-700">
                    {processingProgress < 100 ? `AI is analyzing using ${formData.grading_mode} mode...` : "Almost done!"}
                  </p>
                  
                  {/* Background grading tip */}
                  <div className="mt-3 p-3 bg-blue-100 rounded border border-blue-300">
                    <p className="text-xs text-blue-800 font-medium mb-1">
                      💡 <strong>Tip:</strong> Grading runs in background!
                    </p>
                    <p className="text-xs text-blue-700">
                      You can navigate away or close this tab. Check "Manage Exams" for status.
                    </p>
                  </div>
                </div>
              )}

              <div className="flex justify-between pt-4">
                <Button variant="outline" onClick={() => setStep(4)} disabled={processing}>
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Back
                </Button>
                <Button 
                  onClick={handleStartGrading} 
                  disabled={studentFiles.length === 0 || processing}
                  data-testid="start-grading-btn"
                >
                  {processing ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : null}
                  Start Grading ({studentFiles.length} papers)
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </div>
              </>
            </CardContent>
          </Card>
        )}

        {/* Step 6: Results */}
        {step === 6 && results && (
          <Card className="animate-fade-in">
            <CardHeader>
              <div className="flex items-center gap-3">
                <div className="p-3 rounded-full bg-green-100">
                  <CheckCircle className="w-6 h-6 text-green-600" />
                </div>
                <div>
                  <CardTitle>Grading Complete!</CardTitle>
                  <CardDescription>
                    Successfully processed {results.processed} paper{results.processed !== 1 ? "s" : ""} using <strong>{formData.grading_mode}</strong> mode
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {results.submissions.map((sub, index) => (
                  <div key={index} className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                        <span className="font-medium text-primary">
                          {sub.student_name?.charAt(0) || "?"}
                        </span>
                      </div>
                      <div>
                        <p className="font-medium">{sub.student_name}</p>
                        {sub.error ? (
                          <p className="text-sm text-destructive">{sub.error}</p>
                        ) : (
                          <p className="text-sm text-muted-foreground">
                            Score: {sub.total_score} ({sub.percentage}%)
                          </p>
                        )}
                      </div>
                    </div>
                    {!sub.error && (
                      <Badge 
                        className={
                          sub.percentage >= 80 ? "bg-green-100 text-green-700" :
                          sub.percentage >= 60 ? "bg-blue-100 text-blue-700" :
                          sub.percentage >= 40 ? "bg-yellow-100 text-yellow-700" :
                          "bg-red-100 text-red-700"
                        }
                      >
                        {sub.percentage}%
                      </Badge>
                    )}
                  </div>
                ))}
              </div>

              <div className="flex justify-center gap-4 pt-4">
                <Button 
                  variant="outline"
                  onClick={() => {
                    setStep(1);
                    setFormData({
                      batch_id: "",
                      subject_id: "",
                      exam_type: "",
                      exam_name: "",
                      total_marks: 100,
                      exam_date: new Date().toISOString().split("T")[0],
                      grading_mode: "balanced",
                      questions: [{ question_number: 1, max_marks: 10, rubric: "", sub_questions: [] }]
                    });
                    setModelAnswerFile(null);
                    setStudentFiles([]);
                    setExamId(null);
                    setResults(null);
                    setLabelFormats({});
                  }}
                >
                  Grade More Papers
                </Button>
                <Button onClick={() => window.location.href = "/teacher/review"} data-testid="review-papers-btn">
                  Review & Edit Grades
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Format Selection Modal */}
        <Dialog open={formatModalOpen} onOpenChange={setFormatModalOpen}>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle className="text-orange-600">Choose Label Format</DialogTitle>
              <DialogDescription>
                Select how you want to label the sub-questions. This format will be used for all sub-questions at this level.
              </DialogDescription>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-3 py-4">
              {Object.entries(LABELING_FORMATS).map(([key, format]) => (
                <Button
                  key={key}
                  variant="outline"
                  className="h-16 flex flex-col items-center justify-center gap-1 hover:bg-orange-50 hover:border-orange-300"
                  onClick={() => confirmFormatAndAdd(key)}
                >
                  <span className="text-lg font-semibold text-orange-600">{format.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {format.generator(0)}), {format.generator(1)}), {format.generator(2)})...
                  </span>
                </Button>
              ))}
            </div>
            <div className="text-xs text-muted-foreground text-center">
              Subsequent sub-questions will automatically follow this pattern
            </div>
          </DialogContent>
        </Dialog>

        {/* Reset Confirmation Dialog */}
        <AlertDialog open={resetDialogOpen} onOpenChange={setResetDialogOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Reset Upload & Grade?</AlertDialogTitle>
              <AlertDialogDescription>
                This will cancel any ongoing grading process and clear all entered data. 
                You will return to Step 1 and can start fresh.
                {activeJobId && (
                  <span className="block mt-2 text-orange-600 font-medium">
                    ⚠️ An active grading job will be cancelled.
                  </span>
                )}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={handleReset}
                className="bg-red-600 hover:bg-red-700"
              >
                Reset Everything
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Change Question Method Confirmation Dialog */}
        <AlertDialog open={changeMethodDialogOpen} onOpenChange={setChangeMethodDialogOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Change Question Configuration Method?</AlertDialogTitle>
              <AlertDialogDescription>
                You have manually entered question data. Changing the method will clear all entered questions and marks.
                <span className="block mt-2 text-orange-600 font-medium">
                  ⚠️ This action cannot be undone.
                </span>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={confirmChangeMethod}
                className="bg-orange-600 hover:bg-orange-700"
              >
                Change Method
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </Layout>
  );
}
