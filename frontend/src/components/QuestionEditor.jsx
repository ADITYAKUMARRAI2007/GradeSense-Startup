import { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Card } from "./ui/card";
import { Plus, Trash2, ChevronDown, ChevronUp } from "lucide-react";

export default function QuestionEditor({ question, onChange, onRemove }) {
  const [expanded, setExpanded] = useState(true);
  
  const handleAddSubQuestion = () => {
    const currentSubs = question.sub_questions || [];
    onChange({
      ...question,
      sub_questions: [
        ...currentSubs,
        {
          sub_id: String.fromCharCode(97 + currentSubs.length),
          max_marks: 0,
          rubric: ""
        }
      ]
    });
  };
  
  return (
    <Card className="p-4 border-l-4 border-l-blue-500">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h4 className="font-semibold text-lg">Question {question.question_number}</h4>
          <span className="text-sm text-gray-500">({question.max_marks || 0} marks)</span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-red-500 hover:text-red-700"
            onClick={onRemove}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
      
      {expanded && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Question Number</Label>
              <Input
                type="number"
                value={question.question_number}
                onChange={(e) => onChange({...question, question_number: parseInt(e.target.value)})}
              />
            </div>
            <div>
              <Label>Total Marks</Label>
              <Input
                type="number"
                step="0.5"
                value={question.max_marks || ""}
                onChange={(e) => onChange({...question, max_marks: parseFloat(e.target.value) || 0})}
                placeholder="e.g., 10"
              />
            </div>
          </div>
          
          <div>
            <Label>Rubric/Question Text (Optional)</Label>
            <Textarea
              value={(() => {
                let rubric = question.rubric || "";
                // Handle nested object structure
                if (typeof rubric === 'object' && rubric !== null) {
                  rubric = rubric.rubric || rubric.question_text || "";
                }
                return typeof rubric === 'string' ? rubric : String(rubric);
              })()}
              onChange={(e) => onChange({...question, rubric: e.target.value, question_text: e.target.value})}
              placeholder="Brief guidelines for this question..."
              rows={3}
            />
          </div>
          
          {/* Sub-questions */}
          {question.sub_questions && question.sub_questions.length > 0 && (
            <div className="space-y-3">
              <Label className="text-sm font-medium">Sub-questions</Label>
              {question.sub_questions.map((sub, subIdx) => (
                <SubQuestionEditor
                  key={subIdx}
                  subQuestion={sub}
                  questionNumber={question.question_number}
                  onChange={(updated) => {
                    const newSubs = [...question.sub_questions];
                    newSubs[subIdx] = updated;
                    onChange({...question, sub_questions: newSubs});
                  }}
                  onRemove={() => {
                    const newSubs = question.sub_questions.filter((_, i) => i !== subIdx);
                    onChange({...question, sub_questions: newSubs});
                  }}
                />
              ))}
            </div>
          )}
          
          <Button
            variant="outline"
            size="sm"
            onClick={handleAddSubQuestion}
            className="w-full"
          >
            <Plus className="h-4 w-4 mr-2" />
            Add Sub-question
          </Button>
        </div>
      )}
    </Card>
  );
}

function SubQuestionEditor({ subQuestion, questionNumber, onChange, onRemove }) {
  return (
    <div className="ml-6 p-3 border-2 border-dashed rounded-lg bg-gray-50">
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-sm">
          Q{questionNumber}({subQuestion.sub_id})
        </span>
        <Button 
          size="sm" 
          variant="ghost" 
          onClick={onRemove}
          className="h-6 w-6 p-0 text-red-500 hover:text-red-700"
        >
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label className="text-xs">Sub-ID</Label>
            <Input
              size="sm"
              value={subQuestion.sub_id || ""}
              onChange={(e) => onChange({...subQuestion, sub_id: e.target.value})}
              placeholder="a, b, c..."
              className="h-8"
            />
          </div>
          <div>
            <Label className="text-xs">Marks</Label>
            <Input
              size="sm"
              type="number"
              step="0.5"
              value={subQuestion.max_marks || ""}
              onChange={(e) => onChange({...subQuestion, max_marks: parseFloat(e.target.value) || 0})}
              placeholder="0"
              className="h-8"
            />
          </div>
        </div>
        <div>
          <Label className="text-xs">Rubric (Optional)</Label>
          <Textarea
            value={subQuestion.rubric || ""}
            onChange={(e) => onChange({...subQuestion, rubric: e.target.value})}
            placeholder="Brief guidelines..."
            rows={2}
            className="text-sm"
          />
        </div>
      </div>
    </div>
  );
}
