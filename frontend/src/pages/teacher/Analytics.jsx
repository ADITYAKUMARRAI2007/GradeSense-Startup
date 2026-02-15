import { useState, useEffect } from 'react';
import axios from 'axios';
import { API } from '../../App';
import Layout from '../../components/Layout';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { Badge } from '../../components/ui/badge';
import { ScrollArea } from '../../components/ui/scroll-area';
import { toast } from 'sonner';
import { 
  Brain,
  Sparkles,
  Send,
  Loader2,
  TrendingUp,
  BarChart3,
  PieChart,
  ListOrdered,
  Hash
} from 'lucide-react';
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart as RePieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from 'recharts';

const COLORS = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#6366f1', '#ef4444', '#14b8a6'];

export default function Analytics({ user }) {
  const [exams, setExams] = useState([]);
  const [batches, setBatches] = useState([]);
  const [selectedExam, setSelectedExam] = useState('');
  const [selectedBatch, setSelectedBatch] = useState('');
  
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [responses, setResponses] = useState([]);
  
  const [suggestions] = useState([
    "List students who scored below 50%",
    "Show me a histogram of student performance",
    "Which topics do students struggle with most?",
    "How many students gave the exam?",
    "Show top 5 performing students",
    "Which questions had the lowest average score?",
    "Compare performance across different batches",
    "Show me students who need attention"
  ]);

  useEffect(() => {
    fetchFilters();
  }, []);

  const fetchFilters = async () => {
    try {
      const [examsRes, batchesRes] = await Promise.all([
        axios.get(`${API}/exams`),
        axios.get(`${API}/batches`)
      ]);
      setExams(examsRes.data);
      setBatches(batchesRes.data);
    } catch (error) {
      console.error('Error fetching filters:', error);
    }
  };

  const handleAskAI = async () => {
    if (!query.trim()) {
      toast.error('Please enter a question');
      return;
    }

    setLoading(true);
    
    try {
      const response = await axios.post(`${API}/analytics/ask-ai`, {
        query: query.trim(),
        exam_id: selectedExam || undefined,
        batch_id: selectedBatch || undefined
      });

      // Add to responses with timestamp
      setResponses(prev => [...prev, {
        query: query.trim(),
        result: response.data,
        timestamp: new Date().toLocaleTimeString()
      }]);
      
      setQuery('');
      toast.success('Analysis complete!');
    } catch (error) {
      console.error('Error asking AI:', error);
      toast.error(error.response?.data?.detail || 'Failed to process your question');
      
      // Add error response
      setResponses(prev => [...prev, {
        query: query.trim(),
        result: {
          type: 'error',
          message: error.response?.data?.detail || 'Failed to process your question'
        },
        timestamp: new Date().toLocaleTimeString()
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleSuggestionClick = (suggestion) => {
    setQuery(suggestion);
  };

  const renderResponse = (response) => {
    const { result } = response;

    if (!result) return null;

    switch (result.type) {
      case 'text':
        return (
          <div className="space-y-3">
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{result.response}</p>
            {result.key_points && result.key_points.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-sm font-semibold">Key Points:</p>
                <ul className="list-disc list-inside space-y-1">
                  {result.key_points.map((point, idx) => (
                    <li key={idx} className="text-sm text-muted-foreground">{point}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );

      case 'number':
        return (
          <div className="flex flex-col items-center justify-center p-8 bg-gradient-to-br from-blue-50 to-purple-50 rounded-lg">
            <div className="text-5xl font-bold text-primary mb-2">{result.value}</div>
            <div className="text-lg font-medium text-center">{result.label}</div>
            {result.description && (
              <p className="text-sm text-muted-foreground text-center mt-3 max-w-md">
                {result.description}
              </p>
            )}
          </div>
        );

      case 'list':
        return (
          <div className="space-y-3">
            {result.title && <h3 className="font-semibold text-lg">{result.title}</h3>}
            {result.description && (
              <p className="text-sm text-muted-foreground">{result.description}</p>
            )}
            <ScrollArea className="h-[300px] rounded-md border p-4">
              <div className="space-y-2">
                {result.items && result.items.map((item, idx) => (
                  <div key={idx} className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg">
                    <Badge variant="outline" className="w-8 h-8 flex items-center justify-center">
                      {idx + 1}
                    </Badge>
                    <div className="flex-1">
                      {typeof item === 'string' ? (
                        <p className="text-sm">{item}</p>
                      ) : (
                        <div>
                          <p className="text-sm font-medium">{item.name || item.label || item.student}</p>
                          {item.score !== undefined && (
                            <p className="text-xs text-muted-foreground">Score: {item.score}</p>
                          )}
                          {item.percentage !== undefined && (
                            <p className="text-xs text-muted-foreground">Percentage: {item.percentage}%</p>
                          )}
                          {item.details && (
                            <p className="text-xs text-muted-foreground">{item.details}</p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        );

      case 'chart':
        return (
          <div className="space-y-3">
            {result.title && <h3 className="font-semibold text-lg">{result.title}</h3>}
            {result.description && (
              <p className="text-sm text-muted-foreground">{result.description}</p>
            )}
            <div className="w-full h-[400px] mt-4">
              <ResponsiveContainer width="100%" height="100%">
                {result.chart_type === 'bar' || result.chart_type === 'histogram' ? (
                  <BarChart data={result.data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey={result.data[0]?.name ? "name" : result.data[0]?.range ? "range" : "label"} 
                      label={{ value: result.x_label, position: 'insideBottom', offset: -5 }}
                    />
                    <YAxis label={{ value: result.y_label, angle: -90, position: 'insideLeft' }} />
                    <Tooltip />
                    <Legend />
                    <Bar 
                      dataKey={result.data[0]?.value !== undefined ? "value" : result.data[0]?.count !== undefined ? "count" : "score"} 
                      fill="#3b82f6"
                    >
                      {result.data.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                ) : result.chart_type === 'line' ? (
                  <LineChart data={result.data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      dataKey="x" 
                      label={{ value: result.x_label, position: 'insideBottom', offset: -5 }}
                    />
                    <YAxis label={{ value: result.y_label, angle: -90, position: 'insideLeft' }} />
                    <Tooltip />
                    <Legend />
                    <Line type="monotone" dataKey="y" stroke="#3b82f6" strokeWidth={2} />
                  </LineChart>
                ) : result.chart_type === 'pie' ? (
                  <RePieChart>
                    <Pie
                      data={result.data}
                      cx="50%"
                      cy="50%"
                      labelLine={false}
                      label={(entry) => `${entry.name}: ${entry.value}`}
                      outerRadius={120}
                      fill="#8884d8"
                      dataKey="value"
                    >
                      {result.data.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </RePieChart>
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground">
                    Unsupported chart type
                  </div>
                )}
              </ResponsiveContainer>
            </div>
          </div>
        );

      case 'multi':
        return (
          <div className="space-y-6">
            {result.components && result.components.map((component, idx) => (
              <div key={idx} className="border-l-4 border-primary pl-4">
                {renderResponse({ result: component })}
              </div>
            ))}
          </div>
        );

      case 'error':
        return (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm text-red-800">{result.message}</p>
          </div>
        );

      default:
        return (
          <div className="p-4 bg-muted rounded-lg">
            <pre className="text-xs overflow-auto">{JSON.stringify(result, null, 2)}</pre>
          </div>
        );
    }
  };

  return (
    <Layout user={user}>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-3">
              <Brain className="w-8 h-8 text-primary" />
              Ask AI
            </h1>
            <p className="text-muted-foreground mt-1">
              Ask any question about your students, exams, and performance data
            </p>
          </div>

          {/* Filters */}
          <div className="flex gap-3">
            <Select value={selectedBatch || 'all'} onValueChange={(v) => setSelectedBatch(v === 'all' ? '' : v)}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="All Batches" />
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

            <Select value={selectedExam || 'all'} onValueChange={(v) => setSelectedExam(v === 'all' ? '' : v)}>
              <SelectTrigger className="w-48">
                <SelectValue placeholder="All Exams" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Exams</SelectItem>
                {exams.map(exam => (
                  <SelectItem key={exam.exam_id} value={exam.exam_id}>
                    {exam.exam_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* AI Query Input */}
        <Card className="border-2 border-primary shadow-lg">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-primary" />
              What would you like to know?
            </CardTitle>
            <CardDescription>
              Ask questions in plain English about student performance, exam results, trends, or any other data
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Input */}
            <div className="flex gap-2">
              <Input
                placeholder='e.g., "Show me students scoring below 50%" or "Create a histogram of performance"'
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAskAI()}
                className="flex-1 text-base"
                disabled={loading}
              />
              <Button 
                onClick={handleAskAI} 
                disabled={loading || !query.trim()}
                size="lg"
              >
                {loading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Send className="w-5 h-5" />
                )}
              </Button>
            </div>

            {/* Suggestions */}
            {responses.length === 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium text-muted-foreground">Try these examples:</p>
                <div className="flex flex-wrap gap-2">
                  {suggestions.map((suggestion, idx) => (
                    <Button
                      key={idx}
                      variant="outline"
                      size="sm"
                      onClick={() => handleSuggestionClick(suggestion)}
                      className="text-xs"
                      disabled={loading}
                    >
                      {suggestion}
                    </Button>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Responses */}
        {responses.length > 0 && (
          <div className="space-y-4">
            {responses.map((response, idx) => (
              <Card key={idx} className="overflow-hidden">
                <CardHeader className="bg-muted/50 pb-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-start gap-3 flex-1">
                      <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 mt-1">
                        <span className="text-sm font-semibold text-primary">{idx + 1}</span>
                      </div>
                      <div className="flex-1">
                        <p className="font-medium text-sm">{response.query}</p>
                        <p className="text-xs text-muted-foreground mt-1">{response.timestamp}</p>
                      </div>
                    </div>
                    <div className="flex-shrink-0">
                      {response?.result?.type === 'chart' && <BarChart3 className="w-5 h-5 text-primary" />}
                      {response?.result?.type === 'list' && <ListOrdered className="w-5 h-5 text-primary" />}
                      {response?.result?.type === 'number' && <Hash className="w-5 h-5 text-primary" />}
                      {response?.result?.type === 'text' && <TrendingUp className="w-5 h-5 text-primary" />}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-6">
                  {renderResponse(response)}
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {/* Empty State */}
        {responses.length === 0 && !loading && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-12 text-center">
              <Brain className="w-16 h-16 text-muted-foreground/50 mb-4" />
              <h3 className="text-lg font-semibold mb-2">Ready to analyze your data</h3>
              <p className="text-sm text-muted-foreground max-w-md">
                Ask any question about student performance, exam trends, or specific insights you need.
                The AI will provide answers with charts, lists, or detailed analysis.
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </Layout>
  );
}
