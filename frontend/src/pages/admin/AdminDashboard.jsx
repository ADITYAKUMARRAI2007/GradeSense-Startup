import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart3, Users, MessageSquare, Settings, Mail, Shield, TrendingUp, Database, FileText, Zap, Activity } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import FeedbackBeacon from '../../components/FeedbackBeacon';

const AdminDashboard = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState({
    active_now: 0,
    pending_feedback: 0,
    api_health: 0,
    system_status: 'Loading...'
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDashboardStats();
    // Refresh every 30 seconds
    const interval = setInterval(fetchDashboardStats, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchDashboardStats = async () => {
    try {
      const response = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/admin/dashboard-stats`, {
        credentials: 'include'
      });
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (error) {
      console.error('Error fetching dashboard stats:', error);
    } finally {
      setLoading(false);
    }
  };

  const adminSections = [
    {
      title: 'Analytics Dashboard',
      description: 'View platform metrics, user engagement, and AI performance',
      icon: BarChart3,
      path: '/admin/analytics',
      color: 'bg-blue-500',
      stats: 'Real-time insights'
    },
    {
      title: 'User Management',
      description: 'Manage users, feature flags, quotas, and account status',
      icon: Users,
      path: '/admin/users',
      color: 'bg-green-500',
      stats: 'Full control',
      badge: '✨ All Features'
    },
    {
      title: 'Feedback Management',
      description: 'View and respond to user feedback, bugs, and questions',
      icon: MessageSquare,
      path: '/admin/feedback',
      color: 'bg-purple-500',
      stats: 'Direct support'
    },
    {
      title: 'System Health',
      description: 'Monitor API performance, errors, and system status',
      icon: Activity,
      path: '/admin/system',
      color: 'bg-orange-500',
      stats: 'Coming soon',
      disabled: true
    },
    {
      title: 'Email Templates',
      description: 'Manage email templates and automated notifications',
      icon: Mail,
      path: '/admin/emails',
      color: 'bg-pink-500',
      stats: 'Coming soon',
      disabled: true
    },
    {
      title: 'Audit Logs',
      description: 'View detailed logs of all admin actions and changes',
      icon: FileText,
      path: '/admin/logs',
      color: 'bg-red-500',
      stats: 'Coming soon',
      disabled: true
    }
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 bg-primary rounded-lg flex items-center justify-center">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Admin Control Panel</h1>
              <p className="text-gray-500">Central hub for managing GradeSense platform</p>
            </div>
          </div>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
          <Card className="border-l-4 border-l-blue-500">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600 mb-1">Active Now</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {loading ? '...' : stats.active_now}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Last 30 minutes</p>
                </div>
                <Activity className="w-8 h-8 text-blue-500" />
              </div>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-green-500">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600 mb-1">Pending Feedback</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {loading ? '...' : stats.pending_feedback}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Unresolved</p>
                </div>
                <MessageSquare className="w-8 h-8 text-green-500" />
              </div>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-purple-500">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600 mb-1">API Health</p>
                  <p className={`text-2xl font-bold ${
                    stats.api_health >= 95 ? 'text-green-600' :
                    stats.api_health >= 80 ? 'text-yellow-600' :
                    'text-red-600'
                  }`}>
                    {loading ? '...' : `${stats.api_health}%`}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Last hour</p>
                </div>
                <TrendingUp className="w-8 h-8 text-purple-500" />
              </div>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-orange-500">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600 mb-1">System Status</p>
                  <p className={`text-2xl font-bold ${
                    stats.system_status === 'Healthy' ? 'text-green-600' :
                    stats.system_status === 'Degraded' ? 'text-yellow-600' :
                    'text-red-600'
                  }`}>
                    {loading ? '...' : stats.system_status}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {loading ? 'Checking...' : (
                      stats.system_status === 'Healthy' ? 'All systems operational' :
                      stats.system_status === 'Degraded' ? 'Minor issues detected' :
                      'Issues detected'
                    )}
                  </p>
                </div>
                <Shield className="w-8 h-8 text-orange-500" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Admin Sections Grid */}
        <div className="mb-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Admin Tools</h2>
          
          {/* Info Card for Feature Flags & Quotas */}
          <Card className="mb-6 bg-gradient-to-r from-green-50 to-blue-50 border-green-200">
            <CardContent className="p-6">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 bg-green-500 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Zap className="w-6 h-6 text-white" />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-gray-900 mb-2">
                    ✨ Feature Flags & Usage Quotas are LIVE!
                  </h3>
                  <p className="text-sm text-gray-700 mb-3">
                    Control user features and set usage limits directly from <strong>User Management</strong>. 
                    Click on any user and use the tabs to:
                  </p>
                  <div className="grid md:grid-cols-3 gap-3 text-sm">
                    <div className="flex items-center gap-2 bg-white/50 p-2 rounded">
                      <Zap className="w-4 h-4 text-yellow-600" />
                      <span><strong>Tab 1:</strong> Toggle 6 feature flags</span>
                    </div>
                    <div className="flex items-center gap-2 bg-white/50 p-2 rounded">
                      <Database className="w-4 h-4 text-indigo-600" />
                      <span><strong>Tab 2:</strong> Set usage quotas</span>
                    </div>
                    <div className="flex items-center gap-2 bg-white/50 p-2 rounded">
                      <Shield className="w-4 h-4 text-red-600" />
                      <span><strong>Tab 3:</strong> Manage account status</span>
                    </div>
                  </div>
                  <button
                    onClick={() => navigate('/admin/users')}
                    className="mt-4 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium"
                  >
                    Go to User Management →
                  </button>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {adminSections.map((section) => (
              <Card
                key={section.path}
                className={`hover:shadow-lg transition-all duration-200 ${
                  section.disabled ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer hover:scale-105'
                }`}
                onClick={() => !section.disabled && navigate(section.path)}
              >
                <CardContent className="p-6">
                  <div className="flex items-start justify-between mb-4">
                    <div className={`w-12 h-12 ${section.color} rounded-lg flex items-center justify-center`}>
                      <section.icon className="w-6 h-6 text-white" />
                    </div>
                    {section.disabled ? (
                      <span className="text-xs bg-gray-200 text-gray-600 px-2 py-1 rounded-full">
                        Coming Soon
                      </span>
                    ) : section.badge ? (
                      <span className="text-xs bg-green-500 text-white px-2 py-1 rounded-full font-semibold animate-pulse">
                        {section.badge}
                      </span>
                    ) : null}
                  </div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-2">{section.title}</h3>
                  <p className="text-sm text-gray-600 mb-4">{section.description}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-500">{section.stats}</span>
                    {!section.disabled && (
                      <button className="text-sm text-primary font-medium hover:underline">
                        Open →
                      </button>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>

        {/* Info Banner */}
        <Card className="bg-gradient-to-r from-blue-50 to-purple-50 border-blue-200">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <Shield className="w-8 h-8 text-blue-600 flex-shrink-0" />
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">Admin Access</h3>
                <p className="text-sm text-gray-700 mb-3">
                  You have full administrative access to GradeSense. This panel gives you control over users, 
                  analytics, system settings, and platform configuration. All actions are logged for security.
                </p>
                <div className="flex items-center gap-4 text-sm text-gray-600">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                    <span>Real-time monitoring</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                    <span>Secure access</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-purple-500 rounded-full"></div>
                    <span>Audit logged</span>
                  </div>
                </div>
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

export default AdminDashboard;
