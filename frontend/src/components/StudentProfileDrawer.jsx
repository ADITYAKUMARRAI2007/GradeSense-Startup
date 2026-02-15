import { useEffect, useState } from 'react';
import axios from 'axios';
import { X, Download, Mail, TrendingUp, TrendingDown, AlertCircle, CheckCircle } from 'lucide-react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const StudentProfileDrawer = ({ student, batchId, onClose }) => {
  const [studentData, setStudentData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStudentData();
  }, [student.student_id]);

  const fetchStudentData = async () => {
    try {
      const response = await axios.get(
        `${API}/students/${student.student_id}/analytics?batch_id=${batchId}`,
        { withCredentials: true }
      );
      setStudentData(response.data);
    } catch (error) {
      console.error('Error fetching student data:', error);
    } finally {
      setLoading(false);
    }
  };

  const chartData = {
    labels: studentData?.exam_history?.map(e => e.exam_name) || [],
    datasets: [
      {
        label: 'Student Score',
        data: studentData?.exam_history?.map(e => e.percentage) || [],
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        fill: true,
        tension: 0.4
      },
      {
        label: 'Class Average',
        data: studentData?.exam_history?.map(e => e.class_average) || [],
        borderColor: '#94a3b8',
        backgroundColor: 'transparent',
        borderDash: [5, 5],
        tension: 0.4
      }
    ]
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top'
      }
    },
    scales: {
      y: {
        beginAtZero: true,
        max: 100
      }
    }
  };

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/50 z-40 transition-opacity"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-full md:w-[600px] bg-white shadow-2xl z-50 overflow-y-auto animate-slide-in-right">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b z-10 p-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-gray-900">{student.name}</h2>
              <p className="text-gray-500 mt-1">
                Roll: {student.roll_number || 'N/A'} • {student.email}
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-full transition-colors"
            >
              <X className="w-5 h-5 text-gray-500" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
          </div>
        ) : (
          <div className="p-6 space-y-6">
            {/* Performance Chart */}
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Performance Trend</h3>
              <div className="h-64 bg-gray-50 rounded-lg p-4">
                <Line data={chartData} options={chartOptions} />
              </div>
            </div>

            {/* Overall Stats */}
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-blue-50 p-4 rounded-lg">
                <div className="text-sm text-blue-600 mb-1">Average Score</div>
                <div className="text-3xl font-bold text-blue-700">
                  {studentData?.overall_average || 0}%
                </div>
              </div>
              <div className="bg-green-50 p-4 rounded-lg">
                <div className="text-sm text-green-600 mb-1">Exams Taken</div>
                <div className="text-3xl font-bold text-green-700">
                  {studentData?.total_exams || 0}
                </div>
              </div>
            </div>

            {/* Strengths & Weaknesses */}
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Strengths & Weaknesses</h3>
              <div className="space-y-3">
                {/* Strengths */}
                <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle className="w-5 h-5 text-green-600" />
                    <span className="font-semibold text-green-700">Strengths</span>
                  </div>
                  <ul className="list-disc list-inside text-sm text-green-700 space-y-1">
                    {studentData?.strengths?.map((strength, idx) => (
                      <li key={idx}>{strength}</li>
                    )) || <li>No data yet</li>}
                  </ul>
                </div>

                {/* Weaknesses */}
                <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertCircle className="w-5 h-5 text-red-600" />
                    <span className="font-semibold text-red-700">Needs Improvement</span>
                  </div>
                  <ul className="list-disc list-inside text-sm text-red-700 space-y-1">
                    {studentData?.weaknesses?.map((weakness, idx) => (
                      <li key={idx}>{weakness}</li>
                    )) || <li>No data yet</li>}
                  </ul>
                </div>
              </div>
            </div>

            {/* Exam History */}
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Exams</h3>
              <div className="space-y-3">
                {studentData?.exam_history?.slice(0, 5).map((exam, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
                  >
                    <div>
                      <div className="font-medium text-gray-900">{exam.exam_name}</div>
                      <div className="text-sm text-gray-500">
                        {new Date(exam.graded_at).toLocaleDateString()}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-lg font-bold ${
                        exam.percentage >= 75 ? 'text-green-600' :
                        exam.percentage >= 40 ? 'text-yellow-600' :
                        'text-red-600'
                      }`}>
                        {exam.percentage}%
                      </div>
                      <div className="text-xs text-gray-500">
                        {exam.obtained_marks}/{exam.total_marks}
                      </div>
                    </div>
                  </div>
                )) || (
                  <p className="text-gray-500 text-center py-8">No exam history</p>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-3 pt-4 border-t">
              <button
                onClick={() => window.open(`${API}/students/${student.student_id}/report?batch_id=${batchId}`, '_blank')}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
              >
                <Download className="w-4 h-4" />
                Download Report Card
              </button>
              <button
                onClick={() => window.location.href = `mailto:${student.email}`}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <Mail className="w-4 h-4" />
                Email Parent
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

export default StudentProfileDrawer;
