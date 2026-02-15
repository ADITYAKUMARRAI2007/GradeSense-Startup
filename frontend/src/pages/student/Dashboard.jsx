import { useState, useEffect } from "react";
import axios from "axios";
import { API } from "../../App";
import Layout from "../../components/Layout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Progress } from "../../components/ui/progress";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  LineChart,
  Line
} from "recharts";
import { 
  TrendingUp, 
  TrendingDown,
  Award,
  BookOpen,
  Target,
  ArrowRight,
  AlertTriangle,
  CheckCircle,
  Lightbulb,
  X
} from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function StudentDashboard({ user }) {
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedWeakArea, setSelectedWeakArea] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    fetchDashboard();
  }, []);

  const fetchDashboard = async () => {
    try {
      const response = await axios.get(`${API}/analytics/student-dashboard`);
      setAnalytics(response.data);
    } catch (error) {
      console.error("Error fetching dashboard:", error);
    } finally {
      setLoading(false);
    }
  };

  const stats = analytics?.stats || {};
  const recentResults = analytics?.recent_results || [];
  const recommendations = analytics?.recommendations || [];
  const subjectPerformance = analytics?.subject_performance || [];
  const weakAreas = analytics?.weak_areas || [];
  const strongAreas = analytics?.strong_areas || [];

  return (
    <Layout user={user}>
      <div className="space-y-4 lg:space-y-6" data-testid="student-dashboard">
        {/* Welcome */}
        <div>
          <h1 className="text-2xl lg:text-3xl font-bold text-foreground">
            Welcome, {user?.name?.split(" ")[0]}!
          </h1>
          <p className="text-sm lg:text-base text-muted-foreground mt-1">
            Track your performance and see personalized study recommendations
          </p>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4">
          <Card className="animate-fade-in">
            <CardContent className="p-4 lg:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs lg:text-sm text-muted-foreground">Exams Taken</p>
                  <p className="text-2xl lg:text-3xl font-bold mt-1">{stats.total_exams || 0}</p>
                </div>
                <div className="p-2 lg:p-3 rounded-xl bg-blue-50">
                  <BookOpen className="w-5 h-5 lg:w-6 lg:h-6 text-blue-600" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="animate-fade-in stagger-1">
            <CardContent className="p-4 lg:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs lg:text-sm text-muted-foreground">Average Score</p>
                  <p className="text-2xl lg:text-3xl font-bold mt-1">{stats.avg_percentage || 0}%</p>
                </div>
                <div className="p-2 lg:p-3 rounded-xl bg-orange-50">
                  <Target className="w-5 h-5 lg:w-6 lg:h-6 text-orange-600" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="animate-fade-in stagger-2">
            <CardContent className="p-4 lg:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs lg:text-sm text-muted-foreground">Class Rank</p>
                  <p className="text-2xl lg:text-3xl font-bold mt-1">{stats.rank || "N/A"}</p>
                </div>
                <div className="p-2 lg:p-3 rounded-xl bg-green-50">
                  <Award className="w-5 h-5 lg:w-6 lg:h-6 text-green-600" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="animate-fade-in stagger-3">
            <CardContent className="p-4 lg:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs lg:text-sm text-muted-foreground">Improvement</p>
                  <p className="text-2xl lg:text-3xl font-bold mt-1">
                    {stats.improvement > 0 ? "+" : ""}{stats.improvement || 0}%
                  </p>
                </div>
                <div className={`p-2 lg:p-3 rounded-xl ${stats.improvement >= 0 ? "bg-green-50" : "bg-red-50"}`}>
                  {stats.improvement >= 0 ? (
                    <TrendingUp className="w-5 h-5 lg:w-6 lg:h-6 text-green-600" />
                  ) : (
                    <TrendingDown className="w-5 h-5 lg:w-6 lg:h-6 text-red-600" />
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:gap-6">
          {/* Recent Results & Chart */}
          <div className="lg:col-span-2 space-y-4 lg:space-y-6">
            {/* Performance Trend Chart */}
            {recentResults.length > 1 && (
              <Card className="animate-fade-in stagger-2">
                <CardHeader className="p-4 lg:p-6">
                  <CardTitle className="text-base lg:text-lg">Performance Trend</CardTitle>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0">
                  <div className="h-48 lg:h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={recentResults.slice().reverse()}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                        <XAxis 
                          dataKey="exam_name" 
                          tick={{ fontSize: 10 }}
                          tickFormatter={(value) => value.length > 8 ? value.substring(0, 8) + "..." : value}
                        />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
                        <Tooltip 
                          contentStyle={{ 
                            backgroundColor: 'white', 
                            border: '1px solid #E2E8F0',
                            borderRadius: '8px',
                            fontSize: '12px'
                          }}
                        />
                        <Line 
                          type="monotone" 
                          dataKey="percentage" 
                          stroke="#F97316" 
                          strokeWidth={2}
                          dot={{ fill: '#F97316', strokeWidth: 2 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Recent Results */}
            <Card className="animate-fade-in stagger-3">
              <CardHeader className="flex flex-row items-center justify-between p-4 lg:p-6">
                <CardTitle className="text-base lg:text-lg">Recent Results</CardTitle>
                <Button 
                  variant="ghost" 
                  size="sm"
                  onClick={() => navigate("/student/results")}
                  className="text-xs lg:text-sm"
                >
                  View All
                  <ArrowRight className="w-3 h-3 lg:w-4 lg:h-4 ml-1" />
                </Button>
              </CardHeader>
              <CardContent className="p-4 lg:p-6 pt-0">
                {loading ? (
                  <div className="space-y-3">
                    {[1, 2, 3].map(i => (
                      <div key={i} className="h-14 bg-muted animate-pulse rounded-lg" />
                    ))}
                  </div>
                ) : recentResults.length === 0 ? (
                  <div className="text-center py-8">
                    <BookOpen className="w-12 h-12 mx-auto text-muted-foreground/50 mb-3" />
                    <p className="text-muted-foreground">No exam results yet</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {recentResults.map((result, index) => (
                      <div 
                        key={index}
                        className="flex items-center justify-between p-3 lg:p-4 bg-muted/50 rounded-lg hover:bg-muted transition-colors"
                      >
                        <div className="min-w-0">
                          <p className="font-medium text-sm lg:text-base truncate">{result.exam_name}</p>
                          <p className="text-xs lg:text-sm text-muted-foreground">{result.subject}</p>
                        </div>
                        <Badge 
                          className={
                            result.percentage >= 80 ? "bg-green-100 text-green-700" :
                            result.percentage >= 60 ? "bg-blue-100 text-blue-700" :
                            result.percentage >= 40 ? "bg-yellow-100 text-yellow-700" :
                            "bg-red-100 text-red-700"
                          }
                        >
                          {result.percentage}%
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Subject Performance */}
            {subjectPerformance.length > 0 && (
              <Card className="animate-fade-in stagger-4">
                <CardHeader className="p-4 lg:p-6">
                  <CardTitle className="text-base lg:text-lg">Subject-wise Performance</CardTitle>
                </CardHeader>
                <CardContent className="p-4 lg:p-6 pt-0">
                  <div className="space-y-4">
                    {subjectPerformance.map((subject, idx) => (
                      <div key={idx}>
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-medium text-sm">{subject.subject}</span>
                          <span className="text-sm text-muted-foreground">{subject.exams} exams</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Progress 
                            value={subject.average} 
                            className="flex-1 h-2"
                          />
                          <span className={`text-sm font-medium w-12 ${
                            subject.average >= 70 ? "text-green-600" :
                            subject.average >= 50 ? "text-yellow-600" : "text-red-600"
                          }`}>
                            {subject.average}%
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Right Column - Tips, Weak/Strong Areas */}
          <div className="space-y-4 lg:space-y-6">
            {/* Weak Areas */}
            {weakAreas.length > 0 && (
              <Card className="border-red-200 bg-red-50/50 animate-fade-in stagger-3">
                <CardHeader className="p-4">
                  <CardTitle className="flex items-center gap-2 text-red-700 text-base">
                    <AlertTriangle className="w-5 h-5" />
                    Needs Improvement
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-4 pt-0">
                  <div className="space-y-2">
                    {weakAreas.slice(0, 3).map((area, idx) => (
                      <div 
                        key={idx} 
                        className="p-3 bg-white rounded border border-red-200 hover:border-red-300 hover:shadow-sm cursor-pointer transition-all"
                        onClick={() => {
                          setSelectedWeakArea(area);
                          setDialogOpen(true);
                        }}
                      >
                        <p className="font-medium text-red-700">{area.question}</p>
                        <p className="text-xs text-red-600">Score: {area.score}</p>
                        {area.feedback && (
                          <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{area.feedback}</p>
                        )}
                        <p className="text-xs text-primary mt-2 flex items-center gap-1">
                          <span>Click to learn more</span>
                          <ArrowRight className="w-3 h-3" />
                        </p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Strong Areas */}
            {strongAreas.length > 0 && (
              <Card className="border-green-200 bg-green-50/50 animate-fade-in stagger-4">
                <CardHeader className="p-4">
                  <CardTitle className="flex items-center gap-2 text-green-700 text-base">
                    <CheckCircle className="w-5 h-5" />
                    Your Strengths
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-4 pt-0">
                  <div className="space-y-2">
                    {strongAreas.slice(0, 3).map((area, idx) => (
                      <div key={idx} className="p-2 bg-white rounded text-sm">
                        <p className="font-medium text-green-700">{area.question}</p>
                        <p className="text-xs text-green-600">Score: {area.score}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Study Recommendations */}
            <Card className="animate-fade-in stagger-5">
              <CardHeader className="p-4">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Lightbulb className="w-5 h-5 text-primary" />
                  Study Tips
                </CardTitle>
                <CardDescription className="text-xs">Personalized recommendations</CardDescription>
              </CardHeader>
              <CardContent className="p-4 pt-0">
                {recommendations.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Complete some exams to get recommendations
                  </p>
                ) : (
                  <div className="space-y-2">
                    {recommendations.map((rec, index) => (
                      <div 
                        key={index}
                        className="p-3 bg-primary/5 border border-primary/20 rounded-lg text-sm"
                      >
                        {rec}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Quick Actions */}
            <Card className="animate-fade-in stagger-6">
              <CardHeader className="p-4">
                <CardTitle className="text-base">Quick Actions</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 space-y-2">
                <Button 
                  variant="outline" 
                  className="w-full justify-start text-sm"
                  onClick={() => navigate("/student/results")}
                >
                  <BookOpen className="w-4 h-4 mr-2" />
                  View All Results
                </Button>
                <Button 
                  variant="outline" 
                  className="w-full justify-start text-sm"
                  onClick={() => navigate("/student/re-evaluation")}
                >
                  <Target className="w-4 h-4 mr-2" />
                  Request Re-evaluation
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      {/* Improvement Details Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-700">
              <AlertTriangle className="w-5 h-5" />
              Area Needing Improvement
            </DialogTitle>
          </DialogHeader>
          
          {selectedWeakArea && (
            <div className="space-y-4 py-4">
              <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                <h3 className="font-semibold text-lg mb-2">{selectedWeakArea.question}</h3>
                <p className="text-sm text-red-700 font-medium mb-1">
                  Your Score: {selectedWeakArea.score}
                </p>
              </div>

              {selectedWeakArea.feedback && (
                <div className="space-y-2">
                  <h4 className="font-semibold">Feedback:</h4>
                  <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                    <p className="text-sm">{selectedWeakArea.feedback}</p>
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <h4 className="font-semibold">What to do next:</h4>
                <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                  <li>Review the question and your answer carefully</li>
                  <li>Check your class notes or textbook for similar problems</li>
                  <li>Practice more questions on this topic</li>
                  <li>Ask your teacher for clarification if needed</li>
                </ul>
              </div>

              <div className="flex justify-end gap-2 pt-4 border-t">
                <Button
                  variant="outline"
                  onClick={() => navigate("/student/results")}
                >
                  View Full Results
                </Button>
                <Button
                  onClick={() => setDialogOpen(false)}
                >
                  Got It, Close
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
