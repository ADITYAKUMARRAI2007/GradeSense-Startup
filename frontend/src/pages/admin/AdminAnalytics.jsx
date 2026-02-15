import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Users, FileText, TrendingUp, DollarSign, Zap, Target, Activity, Clock, CheckCircle2, XCircle } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { toast } from 'sonner';
import FeedbackBeacon from '../../components/FeedbackBeacon';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const AdminAnalytics = () => {
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchMetrics();
  }, []);

  const fetchMetrics = async () => {
    try {
      const response = await axios.get(`${API}/admin/metrics/overview`, { withCredentials: true });
      setMetrics(response.data);
    } catch (error) {
      console.error('Error fetching metrics:', error);
      toast.error('Failed to load analytics');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
      </div>
    );
  }

  if (!metrics) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-500">No metrics available</p>
      </div>
    );
  }

  const { business_metrics, engagement_metrics, ai_trust_metrics, system_performance, unit_economics, geographic_distribution } = metrics;

  // Prepare chart data
  const userDistribution = [
    { name: 'Teachers', value: business_metrics.total_teachers, color: '#3b82f6' },
    { name: 'Students', value: business_metrics.total_students, color: '#10b981' }
  ];

  const activeUsers = [
    { period: 'Daily', users: business_metrics.dau },
    { period: 'Weekly', users: business_metrics.wau },
    { period: 'Monthly', users: business_metrics.mau }
  ];

  const gradingModes = engagement_metrics.grading_mode_distribution.map(m => ({
    mode: (m._id || 'Unknown').toUpperCase(),
    count: m.count
  }));
  
  // ⭐ NEW: Geographic distribution chart data
  const geoData = (geographic_distribution || []).map(g => ({
    country: g.country || 'Unknown',
    users: g.user_count
  }));
  
  // ⭐ NEW: Error breakdown chart data
  const errorData = (system_performance.error_breakdown || []).map(e => ({
    type: e._id || 'Unknown',
    count: e.count
  }));

  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'];

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <button
          onClick={() => navigate('/teacher/dashboard')}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </button>

        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Platform Analytics</h1>
          <p className="text-gray-500">Comprehensive insights into GradeSense performance and usage</p>
        </div>

        {/* Executive Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <Card className="border-l-4 border-l-blue-500">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <Users className="w-8 h-8 text-blue-500" />
                <span className="text-sm text-gray-500">+{business_metrics.new_signups_30d} this month</span>
              </div>
              <p className="text-3xl font-bold text-gray-900">{business_metrics.total_users}</p>
              <p className="text-sm text-gray-600 mt-1">Total Users</p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-green-500">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <FileText className="w-8 h-8 text-green-500" />
                <span className="text-sm text-gray-500">{engagement_metrics.total_exams} exams</span>
              </div>
              <p className="text-3xl font-bold text-gray-900">{engagement_metrics.total_papers}</p>
              <p className="text-sm text-gray-600 mt-1">Papers Graded</p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-purple-500">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <Target className="w-8 h-8 text-purple-500" />
                <span className="text-sm text-gray-500">Accuracy</span>
              </div>
              <p className="text-3xl font-bold text-gray-900">{ai_trust_metrics.zero_touch_rate}%</p>
              <p className="text-sm text-gray-600 mt-1">Zero-Touch Rate</p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-orange-500">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <DollarSign className="w-8 h-8 text-orange-500" />
                <span className="text-sm text-gray-500">${unit_economics.avg_cost_per_paper_usd}</span>
              </div>
              <p className="text-3xl font-bold text-gray-900">${unit_economics.total_cost_usd}</p>
              <p className="text-sm text-gray-600 mt-1">Total AI Cost</p>
            </CardContent>
          </Card>
        </div>

        {/* Active Users Chart */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-primary" />
              Active Users (DAU/WAU/MAU)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={activeUsers}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="period" />
                <YAxis />
                <Tooltip />
                <Bar dataKey="users" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* NEW: High Priority Metrics Section */}
        <Card className="mb-8 border-l-4 border-l-green-500">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-green-500" />
              High-Impact Metrics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Retention Rate */}
              <div className="text-center p-4 bg-green-50 rounded-lg border border-green-200">
                <p className="text-4xl font-bold text-green-700">{business_metrics.retention_rate}%</p>
                <p className="text-sm text-green-600 mt-2">30-Day Retention</p>
                <p className="text-xs text-gray-500 mt-1">Users who create 2nd exam</p>
              </div>
              
              {/* Average Batch Size */}
              <div className="text-center p-4 bg-blue-50 rounded-lg border border-blue-200">
                <p className="text-4xl font-bold text-blue-700">{engagement_metrics.avg_batch_size}</p>
                <p className="text-sm text-blue-600 mt-2">Avg Batch Size</p>
                <p className="text-xs text-gray-500 mt-1">Papers per exam</p>
              </div>
              
              {/* End-to-End Grading Time */}
              <div className="text-center p-4 bg-purple-50 rounded-lg border border-purple-200">
                <p className="text-4xl font-bold text-purple-700">
                  {engagement_metrics.avg_grading_time_seconds ? 
                    `${Math.round(engagement_metrics.avg_grading_time_seconds)}s` : 
                    'N/A'}
                </p>
                <p className="text-sm text-purple-600 mt-2">Avg Grading Time</p>
                <p className="text-xs text-gray-500 mt-1">Per paper (end-to-end)</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {/* Geographic Distribution */}
          <Card>
            <CardHeader>
              <CardTitle>Geographic Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              {geoData.length > 0 ? (
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={geoData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="country" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="users" fill="#10b981" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-center text-gray-500 py-8">No geographic data available yet</p>
              )}
            </CardContent>
          </Card>

          {/* Error Breakdown */}
          <Card>
            <CardHeader>
              <CardTitle>Error Breakdown (Last 24h)</CardTitle>
            </CardHeader>
            <CardContent>
              {errorData.length > 0 ? (
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={errorData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="type" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="count" fill="#ef4444" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="text-center py-8">
                  <CheckCircle2 className="w-16 h-16 text-green-500 mx-auto mb-2" />
                  <p className="text-green-600 font-semibold">No Errors Detected!</p>
                  <p className="text-sm text-gray-500">All systems running smoothly</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {/* User Distribution */}
          <Card>
            <CardHeader>
              <CardTitle>User Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={userDistribution}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, value }) => `${name}: ${value}`}
                    outerRadius={80}
                    fill="#8884d8"
                    dataKey="value"
                  >
                    {userDistribution.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Grading Mode Preference */}
          <Card>
            <CardHeader>
              <CardTitle>Grading Mode Preference</CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={gradingModes}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="mode" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="count" fill="#10b981" />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>

        {/* AI Trust Metrics */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-yellow-500" />
              AI Performance & Trust Metrics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              <div className="text-center p-4 bg-blue-50 rounded-lg">
                <p className="text-4xl font-bold text-blue-700">{ai_trust_metrics.avg_confidence}%</p>
                <p className="text-sm text-blue-600 mt-2">Avg AI Confidence</p>
              </div>
              <div className="text-center p-4 bg-green-50 rounded-lg">
                <p className="text-4xl font-bold text-green-700">{ai_trust_metrics.zero_touch_rate}%</p>
                <p className="text-sm text-green-600 mt-2">Zero-Touch Rate</p>
              </div>
              <div className="text-center p-4 bg-orange-50 rounded-lg">
                <p className="text-4xl font-bold text-orange-700">{ai_trust_metrics.human_intervention_rate}%</p>
                <p className="text-sm text-orange-600 mt-2">Human Edit Rate</p>
              </div>
              <div className="text-center p-4 bg-purple-50 rounded-lg">
                <p className="text-4xl font-bold text-purple-700">±{ai_trust_metrics.avg_grade_delta}</p>
                <p className="text-sm text-purple-600 mt-2">Avg Grade Delta</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Power Users */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-green-500" />
              Top 10 Power Users
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {engagement_metrics.power_users.map((user, idx) => (
                <div key={user.teacher_id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center font-bold text-primary">
                      {idx + 1}
                    </div>
                    <span className="font-semibold text-gray-900">{user.teacher_name}</span>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-bold text-primary">{user.papers_graded}</p>
                    <p className="text-xs text-gray-500">papers graded</p>
                  </div>
                </div>
              ))}
              {engagement_metrics.power_users.length === 0 && (
                <p className="text-center text-gray-500 py-4">No data available yet</p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* System Performance */}
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-blue-500" />
              System Performance
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="flex items-center justify-between p-4 bg-blue-50 rounded-lg">
                <div>
                  <p className="text-sm text-blue-600 mb-1">Avg Response Time</p>
                  <p className="text-2xl font-bold text-blue-700">{system_performance.avg_response_time_ms}ms</p>
                </div>
                <Clock className="w-12 h-12 text-blue-300" />
              </div>
              <div className="flex items-center justify-between p-4 bg-green-50 rounded-lg">
                <div>
                  <p className="text-sm text-green-600 mb-1">API Success Rate</p>
                  <p className="text-2xl font-bold text-green-700">{system_performance.api_success_rate}%</p>
                </div>
                <CheckCircle2 className="w-12 h-12 text-green-300" />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Unit Economics */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-orange-500" />
              Unit Economics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="text-center p-4 border-2 border-orange-200 rounded-lg">
                <p className="text-sm text-gray-600 mb-2">Total AI Cost</p>
                <p className="text-3xl font-bold text-orange-600">${unit_economics.total_cost_usd}</p>
              </div>
              <div className="text-center p-4 border-2 border-blue-200 rounded-lg">
                <p className="text-sm text-gray-600 mb-2">Cost per Paper</p>
                <p className="text-3xl font-bold text-blue-600">${unit_economics.avg_cost_per_paper_usd}</p>
              </div>
              <div className="text-center p-4 border-2 border-green-200 rounded-lg">
                <p className="text-sm text-gray-600 mb-2">Total Tokens</p>
                <p className="text-3xl font-bold text-green-600">
                  {(unit_economics.total_tokens_input + unit_economics.total_tokens_output) / 1000000}M
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Feedback Beacon */}
      <FeedbackBeacon user={{}} />
    </div>
  );
};

export default AdminAnalytics;
