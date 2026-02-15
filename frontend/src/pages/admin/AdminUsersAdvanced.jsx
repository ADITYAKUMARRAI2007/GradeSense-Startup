import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Users, Search, Edit, Ban, CheckCircle, XCircle, Shield, Zap, TrendingUp, AlertCircle } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Badge } from '../../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../../components/ui/dialog';
import { Switch } from '../../components/ui/switch';
import { Label } from '../../components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { toast } from 'sonner';
import FeedbackBeacon from '../../components/FeedbackBeacon';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const AdminUsersAdvanced = () => {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('all');
  
  // Edit user dialog
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  const [userDetails, setUserDetails] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      const response = await axios.get(`${API}/admin/users`, { withCredentials: true });
      setUsers(response.data);
    } catch (error) {
      console.error('Error fetching users:', error);
      toast.error('Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  const openEditDialog = async (user) => {
    setSelectedUser(user);
    setEditDialogOpen(true);
    setLoadingDetails(true);
    
    try {
      const response = await axios.get(`${API}/admin/users/${user.user_id}/details`, { withCredentials: true });
      setUserDetails(response.data);
    } catch (error) {
      console.error('Error fetching user details:', error);
      toast.error('Failed to load user details');
    } finally {
      setLoadingDetails(false);
    }
  };

  const handleFeatureToggle = (featureName) => {
    setUserDetails({
      ...userDetails,
      feature_flags: {
        ...userDetails.feature_flags,
        [featureName]: !userDetails.feature_flags[featureName]
      }
    });
  };

  const handleQuotaChange = (quotaName, value) => {
    setUserDetails({
      ...userDetails,
      quotas: {
        ...userDetails.quotas,
        [quotaName]: parseInt(value) || 0
      }
    });
  };

  const handleSaveFeatures = async () => {
    setSaving(true);
    try {
      await axios.put(
        `${API}/admin/users/${userDetails.user_id}/features`,
        userDetails.feature_flags,
        { withCredentials: true }
      );
      toast.success('Feature flags updated successfully');
      fetchUsers();
    } catch (error) {
      console.error('Error updating features:', error);
      toast.error('Failed to update features');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveQuotas = async () => {
    setSaving(true);
    try {
      await axios.put(
        `${API}/admin/users/${userDetails.user_id}/quotas`,
        userDetails.quotas,
        { withCredentials: true }
      );
      toast.success('Quotas updated successfully');
      fetchUsers();
    } catch (error) {
      console.error('Error updating quotas:', error);
      toast.error('Failed to update quotas');
    } finally {
      setSaving(false);
    }
  };

  const handleStatusChange = async (status, reason = null) => {
    if (!confirm(`Are you sure you want to ${status} this user?`)) {
      return;
    }

    setSaving(true);
    try {
      await axios.put(
        `${API}/admin/users/${userDetails.user_id}/status`,
        { status, reason },
        { withCredentials: true }
      );
      toast.success(`User ${status} successfully`);
      setEditDialogOpen(false);
      fetchUsers();
    } catch (error) {
      console.error('Error updating status:', error);
      toast.error('Failed to update user status');
    } finally {
      setSaving(false);
    }
  };

  const filteredUsers = users.filter(user => {
    const matchesSearch = 
      user.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      user.email.toLowerCase().includes(searchQuery.toLowerCase());
    
    const matchesRole = roleFilter === 'all' || user.role === roleFilter;
    
    return matchesSearch && matchesRole;
  });

  const stats = {
    total: users.length,
    teachers: users.filter(u => u.role === 'teacher').length,
    students: users.filter(u => u.role === 'student').length,
    active: users.filter(u => u.account_status === 'active' || !u.account_status).length,
    disabled: users.filter(u => u.account_status === 'disabled').length,
    banned: users.filter(u => u.account_status === 'banned').length
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
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <button
          onClick={() => navigate('/admin')}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Admin Hub
        </button>

        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Advanced User Management</h1>
            <p className="text-gray-500">Control features, quotas, and account access</p>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          <Card>
            <CardContent className="p-4">
              <p className="text-sm text-gray-600 mb-1">Total</p>
              <p className="text-2xl font-bold text-gray-900">{stats.total}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-sm text-gray-600 mb-1">Teachers</p>
              <p className="text-2xl font-bold text-primary">{stats.teachers}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <p className="text-sm text-gray-600 mb-1">Students</p>
              <p className="text-2xl font-bold text-green-600">{stats.students}</p>
            </CardContent>
          </Card>
          <Card className="border-green-200">
            <CardContent className="p-4">
              <p className="text-sm text-green-600 mb-1">Active</p>
              <p className="text-2xl font-bold text-green-700">{stats.active}</p>
            </CardContent>
          </Card>
          <Card className="border-orange-200">
            <CardContent className="p-4">
              <p className="text-sm text-orange-600 mb-1">Disabled</p>
              <p className="text-2xl font-bold text-orange-700">{stats.disabled}</p>
            </CardContent>
          </Card>
          <Card className="border-red-200">
            <CardContent className="p-4">
              <p className="text-sm text-red-600 mb-1">Banned</p>
              <p className="text-2xl font-bold text-red-700">{stats.banned}</p>
            </CardContent>
          </Card>
        </div>

        {/* Filters */}
        <Card className="mb-6">
          <CardContent className="p-4">
            <div className="flex flex-col md:flex-row gap-4">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <Input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by name or email..."
                  className="pl-10"
                />
              </div>
              <Select value={roleFilter} onValueChange={setRoleFilter}>
                <SelectTrigger className="w-full md:w-[200px]">
                  <SelectValue placeholder="Filter by role" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Roles</SelectItem>
                  <SelectItem value="teacher">Teachers</SelectItem>
                  <SelectItem value="student">Students</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Users Table */}
        <Card>
          <CardHeader>
            <CardTitle>All Users ({filteredUsers.length})</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="text-left p-4 text-sm font-semibold text-gray-700">User</th>
                    <th className="text-left p-4 text-sm font-semibold text-gray-700">Role</th>
                    <th className="text-center p-4 text-sm font-semibold text-gray-700">Status</th>
                    <th className="text-center p-4 text-sm font-semibold text-gray-700">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filteredUsers.map((user) => (
                    <tr key={user.user_id} className="hover:bg-gray-50 transition-colors">
                      <td className="p-4">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                            <span className="text-lg font-semibold text-primary">
                              {user.name?.charAt(0).toUpperCase()}
                            </span>
                          </div>
                          <div>
                            <p className="font-semibold text-gray-900">{user.name}</p>
                            <p className="text-sm text-gray-500">{user.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="p-4">
                        <Badge 
                          className={
                            user.role === 'teacher' 
                              ? 'bg-blue-100 text-blue-700' 
                              : 'bg-green-100 text-green-700'
                          }
                        >
                          {user.role.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="p-4 text-center">
                        {user.account_status === 'banned' ? (
                          <Badge className="bg-red-100 text-red-700">
                            <Ban className="w-3 h-3 mr-1" />
                            Banned
                          </Badge>
                        ) : user.account_status === 'disabled' ? (
                          <Badge className="bg-orange-100 text-orange-700">
                            <XCircle className="w-3 h-3 mr-1" />
                            Disabled
                          </Badge>
                        ) : (
                          <Badge className="bg-green-100 text-green-700">
                            <CheckCircle className="w-3 h-3 mr-1" />
                            Active
                          </Badge>
                        )}
                      </td>
                      <td className="p-4 text-center">
                        <Button
                          size="sm"
                          onClick={() => openEditDialog(user)}
                          className="gap-2"
                        >
                          <Edit className="w-4 h-4" />
                          Manage
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Edit User Dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-2xl flex items-center gap-2">
              <Shield className="w-6 h-6 text-primary" />
              Manage User: {selectedUser?.name}
            </DialogTitle>
            <p className="text-sm text-gray-500">{selectedUser?.email}</p>
          </DialogHeader>

          {loadingDetails ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
            </div>
          ) : userDetails && (
            <Tabs defaultValue="features" className="mt-4">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="features">Feature Flags</TabsTrigger>
                <TabsTrigger value="quotas">Usage Quotas</TabsTrigger>
                <TabsTrigger value="status">Account Status</TabsTrigger>
              </TabsList>

              {/* Feature Flags Tab */}
              <TabsContent value="features" className="space-y-4">
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
                  <p className="text-sm text-blue-800">
                    <Zap className="w-4 h-4 inline mr-1" />
                    Control which features this user can access
                  </p>
                </div>

                {Object.entries(userDetails.feature_flags || {}).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
                    <div>
                      <Label className="text-base font-semibold capitalize">
                        {key.replace(/_/g, ' ')}
                      </Label>
                      <p className="text-sm text-gray-600">
                        {key === 'ai_suggestions' && 'Allow AI-powered grading suggestions'}
                        {key === 'sub_questions' && 'Enable sub-question grading support'}
                        {key === 'bulk_upload' && 'Allow bulk paper uploads'}
                        {key === 'analytics' && 'Access to analytics dashboard'}
                        {key === 'peer_comparison' && 'View peer comparison data'}
                        {key === 'export_data' && 'Export grades and reports'}
                      </p>
                    </div>
                    <Switch
                      checked={value}
                      onCheckedChange={() => handleFeatureToggle(key)}
                    />
                  </div>
                ))}

                <Button onClick={handleSaveFeatures} disabled={saving} className="w-full mt-4">
                  {saving ? 'Saving...' : 'Save Feature Flags'}
                </Button>
              </TabsContent>

              {/* Usage Quotas Tab */}
              <TabsContent value="quotas" className="space-y-4">
                <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-4">
                  <p className="text-sm text-purple-800">
                    <TrendingUp className="w-4 h-4 inline mr-1" />
                    Set limits on user's monthly usage
                  </p>
                </div>

                {/* Current Usage */}
                {userDetails.current_usage && (
                  <Card className="bg-gray-50">
                    <CardHeader>
                      <CardTitle className="text-base">Current Usage (This Month)</CardTitle>
                    </CardHeader>
                    <CardContent className="grid grid-cols-2 gap-4">
                      <div>
                        <p className="text-sm text-gray-600">Exams Created</p>
                        <p className="text-2xl font-bold text-gray-900">
                          {userDetails.current_usage.exams_this_month}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-gray-600">Papers Graded</p>
                        <p className="text-2xl font-bold text-gray-900">
                          {userDetails.current_usage.papers_this_month}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-gray-600">Total Students</p>
                        <p className="text-2xl font-bold text-gray-900">
                          {userDetails.current_usage.total_students}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-gray-600">Total Batches</p>
                        <p className="text-2xl font-bold text-gray-900">
                          {userDetails.current_usage.total_batches}
                        </p>
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Quota Settings */}
                <div className="space-y-4">
                  <div>
                    <Label htmlFor="max-exams">Max Exams per Month</Label>
                    <Input
                      id="max-exams"
                      type="number"
                      value={userDetails.quotas?.max_exams_per_month || 0}
                      onChange={(e) => handleQuotaChange('max_exams_per_month', e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="max-papers">Max Papers per Month</Label>
                    <Input
                      id="max-papers"
                      type="number"
                      value={userDetails.quotas?.max_papers_per_month || 0}
                      onChange={(e) => handleQuotaChange('max_papers_per_month', e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="max-students">Max Students</Label>
                    <Input
                      id="max-students"
                      type="number"
                      value={userDetails.quotas?.max_students || 0}
                      onChange={(e) => handleQuotaChange('max_students', e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="max-batches">Max Batches</Label>
                    <Input
                      id="max-batches"
                      type="number"
                      value={userDetails.quotas?.max_batches || 0}
                      onChange={(e) => handleQuotaChange('max_batches', e.target.value)}
                      className="mt-1"
                    />
                  </div>
                </div>

                <Button onClick={handleSaveQuotas} disabled={saving} className="w-full mt-4">
                  {saving ? 'Saving...' : 'Save Quotas'}
                </Button>
              </TabsContent>

              {/* Account Status Tab */}
              <TabsContent value="status" className="space-y-4">
                <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 mb-4">
                  <p className="text-sm text-orange-800">
                    <AlertCircle className="w-4 h-4 inline mr-1" />
                    Control user's account access and status
                  </p>
                </div>

                <div className="space-y-4">
                  <Card className="bg-green-50 border-green-200">
                    <CardContent className="p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h4 className="font-semibold text-green-900">Activate Account</h4>
                          <p className="text-sm text-green-700">Allow full access to all features</p>
                        </div>
                        <Button
                          onClick={() => handleStatusChange('active')}
                          disabled={saving || userDetails.account_status === 'active'}
                          className="bg-green-600 hover:bg-green-700"
                        >
                          <CheckCircle className="w-4 h-4 mr-2" />
                          Activate
                        </Button>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="bg-orange-50 border-orange-200">
                    <CardContent className="p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h4 className="font-semibold text-orange-900">Disable Account</h4>
                          <p className="text-sm text-orange-700">Temporarily suspend access</p>
                        </div>
                        <Button
                          onClick={() => handleStatusChange('disabled', 'Temporarily disabled by admin')}
                          disabled={saving || userDetails.account_status === 'disabled'}
                          variant="outline"
                          className="border-orange-300 text-orange-700 hover:bg-orange-100"
                        >
                          <XCircle className="w-4 h-4 mr-2" />
                          Disable
                        </Button>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="bg-red-50 border-red-200">
                    <CardContent className="p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h4 className="font-semibold text-red-900">Ban Account</h4>
                          <p className="text-sm text-red-700">Permanently block all access</p>
                        </div>
                        <Button
                          onClick={() => handleStatusChange('banned', 'Banned for policy violation')}
                          disabled={saving || userDetails.account_status === 'banned'}
                          variant="outline"
                          className="border-red-300 text-red-700 hover:bg-red-100"
                        >
                          <Ban className="w-4 h-4 mr-2" />
                          Ban
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>
            </Tabs>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <FeedbackBeacon user={{}} />
    </div>
  );
};

export default AdminUsersAdvanced;
