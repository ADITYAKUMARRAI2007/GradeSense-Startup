import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Upload, Users, FileText, CheckCircle, AlertCircle, Lightbulb, ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { Switch } from '../../components/ui/switch';
import { Checkbox } from '../../components/ui/checkbox';
import { toast } from 'sonner';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const CreateStudentExam = () => {
  const { batchId } = useParams();
  const navigate = useNavigate();
  
  const [step, setStep] = useState(1);
  const [batch, setBatch] = useState(null);
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  
  // Form data
  const [examName, setExamName] = useState('');
  const [totalMarks, setTotalMarks] = useState('');
  const [gradingMode, setGradingMode] = useState('balanced');
  const [showQuestionPaper, setShowQuestionPaper] = useState(false);
  const [selectedStudents, setSelectedStudents] = useState([]);
  const [questionPaper, setQuestionPaper] = useState(null);
  const [modelAnswer, setModelAnswer] = useState(null);
  const [questions, setQuestions] = useState([{ question_number: 1, max_marks: 10, sub_questions: [] }]);
  const [questionMode, setQuestionMode] = useState('manual'); // 'manual' or 'ai-extract'
  const [extracting, setExtracting] = useState(false);
  const [expandedQuestion, setExpandedQuestion] = useState(null);

  useEffect(() => {
    fetchBatchAndStudents();
  }, [batchId]);

  const fetchBatchAndStudents = async () => {
    try {
      const batchRes = await axios.get(`${API}/batches/${batchId}`, { withCredentials: true });
      setBatch(batchRes.data);
      
      const studentsRes = await axios.get(`${API}/batches/${batchId}/students`, { withCredentials: true });
      setStudents(studentsRes.data);
      
      // Auto-select all students
      setSelectedStudents(studentsRes.data.map(s => s.student_id));
    } catch (error) {
      console.error('Error fetching data:', error);
      toast.error('Failed to load batch data');
    } finally {
      setLoading(false);
    }
  };

  const toggleStudent = (studentId) => {
    setSelectedStudents(prev => 
      prev.includes(studentId)
        ? prev.filter(id => id !== studentId)
        : [...prev, studentId]
    );
  };

  const addQuestion = () => {
    setQuestions([...questions, { question_number: questions.length + 1, max_marks: 10, sub_questions: [] }]);
  };

  const updateQuestion = (index, field, value) => {
    const updated = [...questions];
    updated[index][field] = field === 'max_marks' ? parseFloat(value) : value;
    setQuestions(updated);
  };

  const removeQuestion = (index) => {
    setQuestions(questions.filter((_, i) => i !== index));
  };

  const addSubQuestion = (questionIndex) => {
    const updated = [...questions];
    const existingSubs = updated[questionIndex].sub_questions || [];
    const nextSubId = String.fromCharCode(97 + existingSubs.length); // a, b, c...
    updated[questionIndex].sub_questions = [
      ...existingSubs,
      { sub_id: nextSubId, max_marks: 5, rubric: '' }
    ];
    setQuestions(updated);
  };

  const updateSubQuestion = (questionIndex, subIndex, field, value) => {
    const updated = [...questions];
    updated[questionIndex].sub_questions[subIndex][field] = 
      field === 'max_marks' ? parseFloat(value) : value;
    setQuestions(updated);
  };

  const removeSubQuestion = (questionIndex, subIndex) => {
    const updated = [...questions];
    updated[questionIndex].sub_questions = updated[questionIndex].sub_questions.filter((_, i) => i !== subIndex);
    setQuestions(updated);
  };

  const handleExtractQuestions = async () => {
    if (!modelAnswer) {
      toast.error('Please upload a model answer first');
      return;
    }

    setExtracting(true);
    try {
      const formData = new FormData();
      formData.append('model_answer', modelAnswer);
      
      const response = await axios.post(`${API}/extract-questions-temp`, formData, {
        withCredentials: true,
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      
      if (response.data.questions && response.data.questions.length > 0) {
        setQuestions(response.data.questions.map(q => ({
          question_number: q.question_number,
          max_marks: q.max_marks || 10,
          sub_questions: q.sub_questions || []
        })));
        toast.success(`Extracted ${response.data.questions.length} questions from model answer`);
      } else {
        toast.error('No questions found in the model answer');
      }
    } catch (error) {
      console.error('Error extracting questions:', error);
      toast.error(error.response?.data?.detail || 'Failed to extract questions');
    } finally {
      setExtracting(false);
    }
  };

  const handleCreate = async () => {
    if (!examName || !totalMarks || selectedStudents.length === 0) {
      toast.error('Please fill all required fields');
      return;
    }

    // Validate questions exist
    if (questions.length === 0) {
      toast.error('Please add at least one question');
      return;
    }

    // Optional warning if using AI extraction without files
    if (questionMode === 'ai-extract' && (!questionPaper || !modelAnswer)) {
      toast.info('Note: Uploading question paper and model answer improves AI grading accuracy');
      // Don't return - allow proceeding without files
    }

    setCreating(true);
    try {
      const formData = new FormData();
      
      // Only append files if they exist
      if (questionPaper) {
        formData.append('question_paper', questionPaper);
      }
      if (modelAnswer) {
        formData.append('model_answer', modelAnswer);
      }
      
      const examData = {
        batch_id: batchId,
        exam_name: examName,
        total_marks: parseFloat(totalMarks),
        grading_mode: gradingMode,
        student_ids: selectedStudents,
        show_question_paper: showQuestionPaper && questionPaper !== null, // Only show if uploaded
        questions: questions.map(q => ({
          question_number: q.question_number,
          max_marks: q.max_marks,
          sub_questions: q.sub_questions || []
        }))
      };
      
      // Send as multipart with JSON in form field
      formData.append('exam_data', JSON.stringify(examData));
      
      const response = await axios.post(`${API}/exams/student-mode`, formData, {
        withCredentials: true,
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      
      toast.success('Exam created! Students can now submit their answers.');
      navigate(`/teacher/batch/${batchId}`);
    } catch (error) {
      console.error('Error creating exam:', error);
      toast.error(error.response?.data?.detail || 'Failed to create exam');
    } finally {
      setCreating(false);
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
      <div className="max-w-4xl mx-auto">
        <button
          onClick={() => navigate(`/teacher/batch/${batchId}`)}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Batch
        </button>

        <h1 className="text-3xl font-bold text-gray-900 mb-2">Create Student Upload Exam</h1>
        <p className="text-gray-500 mb-8">Students will upload their answer papers for this exam</p>

        {/* Progress Steps */}
        <div className="flex items-center justify-between mb-8">
          {[1, 2, 3, 4].map((num) => (
            <div key={num} className="flex items-center flex-1">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center font-semibold ${
                step >= num ? 'bg-primary text-white' : 'bg-gray-200 text-gray-600'
              }`}>
                {step > num ? <CheckCircle className="w-6 h-6" /> : num}
              </div>
              {num < 4 && (
                <div className={`flex-1 h-1 mx-2 ${
                  step > num ? 'bg-primary' : 'bg-gray-200'
                }`} />
              )}
            </div>
          ))}
        </div>

        {/* Step 1: Exam Details */}
        {step === 1 && (
          <Card>
            <CardHeader>
              <CardTitle>Step 1: Exam Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label>Exam Name *</Label>
                <Input
                  value={examName}
                  onChange={(e) => setExamName(e.target.value)}
                  placeholder="e.g., Mid-term Math Exam"
                  className="mt-1"
                />
              </div>
              <div>
                <Label>Total Marks *</Label>
                <Input
                  type="number"
                  value={totalMarks}
                  onChange={(e) => setTotalMarks(e.target.value)}
                  placeholder="e.g., 100"
                  className="mt-1"
                />
              </div>
              <div>
                <Label>Grading Mode</Label>
                <Select value={gradingMode} onValueChange={setGradingMode}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="strict">Strict</SelectItem>
                    <SelectItem value="balanced">Balanced</SelectItem>
                    <SelectItem value="lenient">Lenient</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center justify-between p-4 bg-blue-50 rounded-lg">
                <div>
                  <Label>Show Question Paper to Students</Label>
                  <p className="text-sm text-gray-600">Allow students to download the question paper</p>
                </div>
                <Switch
                  checked={showQuestionPaper}
                  onCheckedChange={setShowQuestionPaper}
                />
              </div>
              
              <Button onClick={() => setStep(2)} className="w-full" disabled={!examName || !totalMarks}>
                Next: Select Students
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Step 2: Select Students */}
        {step === 2 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="w-5 h-5" />
                Step 2: Select Students ({selectedStudents.length}/{students.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2 mb-4">
                {students.map((student) => (
                  <div
                    key={student.student_id}
                    className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg hover:bg-gray-100"
                  >
                    <Checkbox
                      checked={selectedStudents.includes(student.student_id)}
                      onCheckedChange={() => toggleStudent(student.student_id)}
                    />
                    <div className="flex-1">
                      <p className="font-semibold text-gray-900">{student.name}</p>
                      <p className="text-sm text-gray-500">{student.email}</p>
                    </div>
                  </div>
                ))}
              </div>
              {students.length === 0 && (
                <div className="text-center py-8">
                  <AlertCircle className="w-12 h-12 text-gray-300 mx-auto mb-2" />
                  <p className="text-gray-500">No students in this batch</p>
                </div>
              )}
              <div className="flex gap-3">
                <Button variant="outline" onClick={() => setStep(1)} className="flex-1">
                  Back
                </Button>
                <Button
                  onClick={() => setStep(3)}
                  className="flex-1"
                  disabled={selectedStudents.length === 0}
                >
                  Next: Upload Files
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 3: Upload Files & Configure Questions */}
        {step === 3 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Upload className="w-5 h-5" />
                Step 3: Upload Files & Configure Questions
              </CardTitle>
              <p className="text-sm text-gray-600 mt-2">
                📋 Optional but recommended: Upload files and configure questions for better grading
              </p>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* File Uploads Section */}
              <div className="space-y-4">
                <h3 className="text-base font-semibold text-gray-900">Upload Files (Optional)</h3>
                <div>
                  <Label>Question Paper (PDF)</Label>
                  <Input
                    type="file"
                    accept=".pdf"
                    onChange={(e) => setQuestionPaper(e.target.files[0])}
                    className="mt-1"
                  />
                  {questionPaper && (
                    <p className="text-sm text-green-600 mt-1">✓ {questionPaper.name}</p>
                  )}
                </div>
                <div>
                  <Label>Model Answer (PDF)</Label>
                  <Input
                    type="file"
                    accept=".pdf"
                    onChange={(e) => setModelAnswer(e.target.files[0])}
                    className="mt-1"
                  />
                  {modelAnswer && (
                    <p className="text-sm text-green-600 mt-1">✓ {modelAnswer.name}</p>
                  )}
                </div>
              </div>

              {/* Question Configuration Section */}
              <div className="border-t pt-6 space-y-4">
                <h3 className="text-base font-semibold text-gray-900">Question Structure</h3>
                
                {/* Mode Selection */}
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setQuestionMode('manual')}
                    className={`p-4 border-2 rounded-lg text-left transition-all ${
                      questionMode === 'manual'
                        ? 'border-primary bg-primary/5'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <FileText className="w-5 h-5 text-primary" />
                      <span className="font-semibold">Manual Entry</span>
                    </div>
                    <p className="text-sm text-gray-600">Add questions manually with marks</p>
                  </button>
                  
                  <button
                    onClick={() => setQuestionMode('ai-extract')}
                    className={`p-4 border-2 rounded-lg text-left transition-all ${
                      questionMode === 'ai-extract'
                        ? 'border-primary bg-primary/5'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Lightbulb className="w-5 h-5 text-primary" />
                      <span className="font-semibold">AI Extraction</span>
                    </div>
                    <p className="text-sm text-gray-600">Extract from model answer PDF</p>
                  </button>
                </div>

                {/* Manual Entry Mode */}
                {questionMode === 'manual' && (
                  <div className="space-y-4">
                    <p className="text-sm text-gray-600">Define questions with their marks and optional sub-questions</p>
                    {questions.map((q, idx) => (
                      <div key={idx} className="border border-gray-200 rounded-lg p-4">
                        <div className="flex gap-3 items-start">
                          <div className="flex-1 space-y-3">
                            <div className="flex gap-3">
                              <div className="w-32">
                                <Label className="text-xs">Question No.</Label>
                                <Input
                                  type="number"
                                  value={q.question_number}
                                  onChange={(e) => updateQuestion(idx, 'question_number', e.target.value)}
                                  placeholder="Q No."
                                  className="mt-1"
                                />
                              </div>
                              <div className="flex-1">
                                <Label className="text-xs">Max Marks</Label>
                                <Input
                                  type="number"
                                  value={q.max_marks}
                                  onChange={(e) => updateQuestion(idx, 'max_marks', e.target.value)}
                                  placeholder="Max marks"
                                  className="mt-1"
                                />
                              </div>
                            </div>

                            {/* Sub-questions section */}
                            {q.sub_questions && q.sub_questions.length > 0 && (
                              <div className="ml-4 space-y-2 border-l-2 border-blue-200 pl-4">
                                <Label className="text-xs text-blue-700">Sub-questions</Label>
                                {q.sub_questions.map((sub, subIdx) => (
                                  <div key={subIdx} className="flex gap-2 items-center bg-blue-50 p-2 rounded">
                                    <span className="text-sm font-medium text-blue-900 w-8">{sub.sub_id})</span>
                                    <Input
                                      type="number"
                                      value={sub.max_marks}
                                      onChange={(e) => updateSubQuestion(idx, subIdx, 'max_marks', e.target.value)}
                                      placeholder="Marks"
                                      className="w-24"
                                    />
                                    <Input
                                      value={sub.rubric || ''}
                                      onChange={(e) => updateSubQuestion(idx, subIdx, 'rubric', e.target.value)}
                                      placeholder="Description (optional)"
                                      className="flex-1"
                                    />
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => removeSubQuestion(idx, subIdx)}
                                      className="text-red-600 hover:text-red-700 hover:bg-red-50"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </Button>
                                  </div>
                                ))}
                              </div>
                            )}

                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => addSubQuestion(idx)}
                              className="text-blue-600 hover:text-blue-700"
                            >
                              <Plus className="w-4 h-4 mr-1" />
                              Add Sub-question
                            </Button>
                          </div>

                          {questions.length > 1 && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => removeQuestion(idx)}
                              className="text-red-600 hover:text-red-700 hover:bg-red-50"
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          )}
                        </div>
                      </div>
                    ))}
                    <Button variant="outline" size="sm" onClick={addQuestion} className="w-full">
                      <Plus className="w-4 h-4 mr-2" />
                      Add Question
                    </Button>
                  </div>
                )}

                {/* AI Extraction Mode */}
                {questionMode === 'ai-extract' && (
                  <div className="space-y-3">
                    {!modelAnswer ? (
                      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                        <p className="text-sm text-yellow-800">
                          ⚠️ Please upload a Model Answer PDF above to use AI extraction
                        </p>
                      </div>
                    ) : (
                      <>
                        <Button
                          onClick={handleExtractQuestions}
                          disabled={extracting}
                          className="w-full"
                        >
                          {extracting ? (
                            <>
                              <Upload className="w-4 h-4 mr-2 animate-spin" />
                              Extracting Questions...
                            </>
                          ) : (
                            <>
                              <Lightbulb className="w-4 h-4 mr-2" />
                              Extract Questions from Model Answer
                            </>
                          )}
                        </Button>
                        
                        {questions.length > 0 && (
                          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                            <p className="text-sm text-green-800 font-medium mb-2">
                              ✓ {questions.length} questions extracted
                            </p>
                            <div className="space-y-1">
                              {questions.map((q, idx) => (
                                <p key={idx} className="text-sm text-green-700">
                                  Q{q.question_number}: {q.max_marks} marks
                                </p>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>

              <div className="flex gap-3 pt-4">
                <Button variant="outline" onClick={() => setStep(2)} className="flex-1">
                  Back
                </Button>
                <Button
                  onClick={() => setStep(4)}
                  className="flex-1"
                >
                  Next: Review & Create
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 4: Review & Create */}
        {step === 4 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CheckCircle className="w-5 h-5" />
                Step 4: Review & Create
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="bg-gray-50 p-4 rounded-lg space-y-2">
                <p><strong>Exam Name:</strong> {examName}</p>
                <p><strong>Total Marks:</strong> {totalMarks}</p>
                <p><strong>Grading Mode:</strong> {gradingMode}</p>
                <p><strong>Students:</strong> {selectedStudents.length} selected</p>
                <p><strong>Question Paper:</strong> {questionPaper ? `Uploaded (${showQuestionPaper ? 'Visible to students' : 'Hidden from students'})` : 'Not uploaded'}</p>
                <p><strong>Model Answer:</strong> {modelAnswer ? 'Uploaded' : 'Not uploaded'}</p>
                <p><strong>Questions:</strong> {questions.length} questions configured ({questionMode === 'ai-extract' ? 'AI Extracted' : 'Manual Entry'})</p>
              </div>
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <p className="text-sm text-blue-800">
                  ℹ️ After creating this exam, students will be able to upload their answer papers. 
                  You'll be notified when all students have submitted.
                </p>
              </div>
              <div className="flex gap-3">
                <Button variant="outline" onClick={() => setStep(3)} className="flex-1">
                  Back
                </Button>
                <Button
                  onClick={handleCreate}
                  disabled={creating}
                  className="flex-1"
                >
                  {creating ? 'Creating...' : 'Create Exam'}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
};

export default CreateStudentExam;
