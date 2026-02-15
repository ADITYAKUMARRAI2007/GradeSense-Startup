import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API } from "../App";
import { Dialog, DialogContent } from "./ui/dialog";
import { Input } from "./ui/input";
import { ScrollArea } from "./ui/scroll-area";
import { Badge } from "./ui/badge";
import { 
  Search, 
  FileText, 
  Users, 
  BookOpen, 
  ClipboardList,
  Loader2
} from "lucide-react";

export default function GlobalSearch({ open, onClose, user }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100);
      setQuery("");
      setResults(null);
    }
  }, [open]);

  useEffect(() => {
    const searchDebounce = setTimeout(() => {
      if (query.length >= 2) {
        performSearch();
      } else {
        setResults(null);
      }
    }, 300);

    return () => clearTimeout(searchDebounce);
  }, [query]);

  const performSearch = async () => {
    try {
      setLoading(true);
      const response = await axios.post(`${API}/search?query=${encodeURIComponent(query)}`);
      setResults(response.data);
    } catch (error) {
      console.error("Search error:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleResultClick = (type, item) => {
    let path = "";
    
    if (user?.role === "teacher") {
      if (type === "exam") {
        path = `/teacher/exams`;
      } else if (type === "student") {
        path = `/teacher/students`;
      } else if (type === "batch") {
        path = `/teacher/batches`;
      } else if (type === "submission") {
        path = `/teacher/review`;
      }
    } else {
      if (type === "exam") {
        path = `/student/results`;
      }
    }
    
    navigate(path);
    onClose();
  };

  const getTotalResults = () => {
    if (!results) return 0;
    return (results.exams?.length || 0) + 
           (results.students?.length || 0) + 
           (results.batches?.length || 0) + 
           (results.submissions?.length || 0);
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl p-0 gap-0">
        {/* Search Input */}
        <div className="flex items-center gap-3 p-4 border-b">
          <Search className="w-5 h-5 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search exams, students, batches..."
            className="border-0 focus-visible:ring-0 text-base"
            data-testid="global-search-input"
          />
          {loading && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
        </div>

        {/* Results */}
        <ScrollArea className="max-h-[400px]">
          {query.length < 2 && (
            <div className="p-8 text-center">
              <Search className="w-12 h-12 mx-auto text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">Type at least 2 characters to search</p>
              <p className="text-xs text-muted-foreground mt-1">Search across exams, students, batches, and more</p>
            </div>
          )}

          {query.length >= 2 && !loading && results && getTotalResults() === 0 && (
            <div className="p-8 text-center">
              <Search className="w-12 h-12 mx-auto text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">No results found for "{query}"</p>
            </div>
          )}

          {results && getTotalResults() > 0 && (
            <div className="p-2 space-y-4">
              {/* Exams */}
              {results.exams?.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 px-3 py-2">
                    <ClipboardList className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground uppercase">Exams</span>
                  </div>
                  <div className="space-y-1">
                    {results.exams.map((exam) => (
                      <button
                        key={exam.exam_id}
                        onClick={() => handleResultClick("exam", exam)}
                        className="w-full flex items-center justify-between p-3 rounded-lg hover:bg-muted transition-colors text-left"
                        data-testid={`search-result-exam-${exam.exam_id}`}
                      >
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-orange-50 flex items-center justify-center">
                            <FileText className="w-4 h-4 text-orange-600" />
                          </div>
                          <div>
                            <p className="font-medium text-sm">{exam.exam_name}</p>
                            <p className="text-xs text-muted-foreground">{exam.exam_date}</p>
                          </div>
                        </div>
                        {exam.status && (
                          <Badge variant="outline" className="text-xs">
                            {exam.status}
                          </Badge>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Students */}
              {results.students?.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 px-3 py-2">
                    <Users className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground uppercase">Students</span>
                  </div>
                  <div className="space-y-1">
                    {results.students.map((student) => (
                      <button
                        key={student.user_id}
                        onClick={() => handleResultClick("student", student)}
                        className="w-full flex items-center justify-between p-3 rounded-lg hover:bg-muted transition-colors text-left"
                        data-testid={`search-result-student-${student.user_id}`}
                      >
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center">
                            <Users className="w-4 h-4 text-blue-600" />
                          </div>
                          <div>
                            <p className="font-medium text-sm">{student.name}</p>
                            <p className="text-xs text-muted-foreground">{student.student_id}</p>
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Batches */}
              {results.batches?.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 px-3 py-2">
                    <BookOpen className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground uppercase">Batches</span>
                  </div>
                  <div className="space-y-1">
                    {results.batches.map((batch) => (
                      <button
                        key={batch.batch_id}
                        onClick={() => handleResultClick("batch", batch)}
                        className="w-full flex items-center gap-3 p-3 rounded-lg hover:bg-muted transition-colors text-left"
                        data-testid={`search-result-batch-${batch.batch_id}`}
                      >
                        <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
                          <BookOpen className="w-4 h-4 text-green-600" />
                        </div>
                        <p className="font-medium text-sm">{batch.name}</p>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Submissions */}
              {results.submissions?.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 px-3 py-2">
                    <FileText className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground uppercase">Submissions</span>
                  </div>
                  <div className="space-y-1">
                    {results.submissions.map((submission) => (
                      <button
                        key={submission.submission_id}
                        onClick={() => handleResultClick("submission", submission)}
                        className="w-full flex items-center justify-between p-3 rounded-lg hover:bg-muted transition-colors text-left"
                        data-testid={`search-result-submission-${submission.submission_id}`}
                      >
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center">
                            <FileText className="w-4 h-4 text-purple-600" />
                          </div>
                          <p className="font-medium text-sm">{submission.student_name}</p>
                        </div>
                        {submission.percentage !== undefined && (
                          <Badge variant="outline">{submission.percentage.toFixed(1)}%</Badge>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t bg-muted/30">
          <p className="text-xs text-muted-foreground">
            {results && getTotalResults() > 0 && (
              <span>{getTotalResults()} results found</span>
            )}
          </p>
          <div className="flex items-center gap-2">
            <kbd className="px-2 py-1 text-xs bg-white border rounded">Esc</kbd>
            <span className="text-xs text-muted-foreground">to close</span>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
