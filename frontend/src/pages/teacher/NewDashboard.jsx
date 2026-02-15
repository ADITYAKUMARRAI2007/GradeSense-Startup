import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Plus, Users, FileText, TrendingUp, BookOpen } from 'lucide-react';
import { Card, CardContent } from '../../components/ui/card';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const NewDashboard = () => {
  const navigate = useNavigate();
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedFilter, setSelectedFilter] = useState('all');

  useEffect(() => {
    fetchBatches();
  }, []);

  const fetchBatches = async () => {
    try {
      const response = await axios.get(`${API}/batches`, { withCredentials: true });
      
      // Enrich each batch with stats
      const enrichedBatches = await Promise.all(
        response.data.map(async (batch) => {
          try {
            const statsResponse = await axios.get(`${API}/batches/${batch.batch_id}/stats`, {
              withCredentials: true
            });
            return { ...batch, stats: statsResponse.data };
          } catch (error) {
            return { ...batch, stats: null };
          }
        })
      );
      
      setBatches(enrichedBatches);
    } catch (error) {
      console.error('Error fetching batches:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateBatch = () => {
    navigate('/teacher/batches/create');
  };

  const handleBatchClick = (batchId) => {
    navigate(`/teacher/batch/${batchId}`);
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
      {/* Header */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <BookOpen className="w-8 h-8 text-primary" />
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Viewing:</h1>
              <select
                value={selectedFilter}
                onChange={(e) => setSelectedFilter(e.target.value)}
                className="text-xl text-gray-600 border-none outline-none bg-transparent cursor-pointer"
              >
                <option value="all">All Batches</option>
                <option value="active">Active Only</option>
                <option value="archived">Archived</option>
              </select>
            </div>
          </div>
          
          <button
            onClick={() => navigate('/teacher/batches')}
            className="text-sm text-primary hover:underline"
          >
            All Batches →
          </button>
        </div>
      </div>

      {/* Batch Grid */}
      <div className="max-w-7xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {/* Create New Batch Card */}
          <Card
            onClick={handleCreateBatch}
            className="border-2 border-dashed border-gray-300 hover:border-primary hover:bg-gray-50 cursor-pointer transition-all group"
          >
            <CardContent className="flex flex-col items-center justify-center h-64 p-6">
              <div className="w-16 h-16 rounded-full bg-gray-100 group-hover:bg-primary/10 flex items-center justify-center mb-4 transition-colors">
                <Plus className="w-8 h-8 text-gray-400 group-hover:text-primary transition-colors" />
              </div>
              <h3 className="text-lg font-semibold text-gray-700 group-hover:text-primary transition-colors">
                Create New Class
              </h3>
              <p className="text-sm text-gray-500 mt-2 text-center">
                Add a new batch to start grading
              </p>
            </CardContent>
          </Card>

          {/* Batch Cards */}
          {batches.map((batch) => (
            <Card
              key={batch.batch_id}
              onClick={() => handleBatchClick(batch.batch_id)}
              className="hover:shadow-lg transition-all cursor-pointer border-l-4 border-l-primary"
            >
              <CardContent className="h-64 p-6 flex flex-col">
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <h3 className="text-lg font-bold text-gray-900 mb-1 line-clamp-2">
                      {batch.name}
                    </h3>
                    <p className="text-sm text-gray-500">
                      {batch.subject || 'General'}
                    </p>
                  </div>
                  <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                    <BookOpen className="w-5 h-5 text-primary" />
                  </div>
                </div>

                {/* Live Status */}
                <div className="flex-1">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-600 flex items-center gap-2">
                        <FileText className="w-4 h-4" />
                        Exams
                      </span>
                      <span className="font-semibold text-gray-900">
                        {batch.stats?.total_exams || 0} graded
                      </span>
                    </div>
                    
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-600 flex items-center gap-2">
                        <Users className="w-4 h-4" />
                        Students
                      </span>
                      <span className="font-semibold text-gray-900">
                        {batch.students?.length || 0}
                      </span>
                    </div>

                    {batch.stats?.class_average !== undefined && (
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-gray-600 flex items-center gap-2">
                          <TrendingUp className="w-4 h-4" />
                          Average
                        </span>
                        <span className="font-semibold text-green-600">
                          {batch.stats.class_average}%
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Mini Sparkline */}
                <div className="mt-4 pt-4 border-t border-gray-100">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-8 flex items-end gap-0.5">
                      {batch.stats?.trend?.slice(-8).map((value, idx) => (
                        <div
                          key={idx}
                          className="flex-1 bg-primary/20 rounded-t"
                          style={{ height: `${value}%` }}
                        />
                      )) || (
                        <span className="text-xs text-gray-400">No data yet</span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500">
                      {batch.stats?.trend_direction === 'up' ? '↗' : batch.stats?.trend_direction === 'down' ? '↘' : '→'}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {batches.length === 0 && (
          <div className="text-center py-12">
            <BookOpen className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-xl font-semibold text-gray-600 mb-2">No Classes Yet</h3>
            <p className="text-gray-500 mb-6">Create your first class to start grading papers</p>
            <button
              onClick={handleCreateBatch}
              className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
            >
              Create First Class
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default NewDashboard;
