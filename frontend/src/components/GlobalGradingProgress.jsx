import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { X, Loader2, CheckCircle, AlertCircle, XCircle } from 'lucide-react';
import { Progress } from './ui/progress';

// Get API URL from environment
const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const GlobalGradingProgress = () => {
  const [activeJob, setActiveJob] = useState(null);
  const [jobData, setJobData] = useState(null);
  const [visible, setVisible] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    // Check for active job on mount
    checkActiveJob();

    // Poll every 5 seconds
    const interval = setInterval(() => {
      checkActiveJob();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  const checkActiveJob = async () => {
    try {
      const stored = localStorage.getItem('activeGradingJob');
      if (!stored) {
        setVisible(false);
        setActiveJob(null);
        setJobData(null);
        return;
      }

      const job = JSON.parse(stored);
      setActiveJob(job);
      
      console.log('GlobalGradingProgress: Checking job', job.job_id);

      // Fetch current status with credentials
      const response = await axios.get(`${API}/grading-jobs/${job.job_id}`, {
        withCredentials: true
      });

      console.log('GlobalGradingProgress: Job data', response.data);
      
      setJobData(response.data);
      setVisible(true);

      // If completed, failed, or cancelled, remove from storage after delay
      if (response.data.status === 'completed' || response.data.status === 'failed' || response.data.status === 'cancelled') {
        setTimeout(() => {
          localStorage.removeItem('activeGradingJob');
          setVisible(false);
          setActiveJob(null);
          setJobData(null);
        }, 5000); // Show completion message for 5 seconds
      }
    } catch (error) {
      console.error('GlobalGradingProgress: Error checking job:', error);
      // If job not found (404) or unauthorized (401), clear from storage
      if (error.response?.status === 404 || error.response?.status === 401) {
        console.log('GlobalGradingProgress: Job not found or unauthorized, clearing');
        localStorage.removeItem('activeGradingJob');
        setVisible(false);
        setActiveJob(null);
        setJobData(null);
      }
    }
  };

  const handleDismiss = () => {
    setVisible(false);
  };

  const handleClick = () => {
    navigate('/teacher/upload');
  };

  if (!visible || !jobData) return null;

  const progress = jobData.total_papers > 0 
    ? Math.round((jobData.processed_papers / jobData.total_papers) * 100)
    : 0;

  const getStatusColor = () => {
    if (jobData.status === 'completed') return 'bg-green-50 border-green-200';
    if (jobData.status === 'failed') return 'bg-red-50 border-red-200';
    if (jobData.status === 'cancelled') return 'bg-yellow-50 border-yellow-200';
    return 'bg-blue-50 border-blue-200';
  };

  const getStatusIcon = () => {
    if (jobData.status === 'completed') return <CheckCircle className="w-5 h-5 text-green-600" />;
    if (jobData.status === 'failed') return <AlertCircle className="w-5 h-5 text-red-600" />;
    if (jobData.status === 'cancelled') return <XCircle className="w-5 h-5 text-yellow-600" />;
    return <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />;
  };

  const getStatusText = () => {
    if (jobData.status === 'completed') {
      return `✓ Grading complete: ${jobData.successful}/${jobData.total_papers} papers`;
    }
    if (jobData.status === 'failed') {
      return `✗ Grading failed`;
    }
    if (jobData.status === 'cancelled') {
      return `⊗ Grading cancelled (exam deleted)`;
    }
    return `Grading in progress: ${jobData.processed_papers}/${jobData.total_papers} papers`;
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 animate-slide-up">
      <div 
        className={`${getStatusColor()} border-2 rounded-lg shadow-lg p-4 min-w-[320px] max-w-md cursor-pointer transition-all hover:shadow-xl`}
        onClick={handleClick}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            {getStatusIcon()}
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-900">
                {getStatusText()}
              </p>
              {jobData.status === 'processing' && (
                <div className="mt-2">
                  <Progress value={progress} className="h-2" />
                  <p className="text-xs text-gray-500 mt-1">
                    {progress}% complete
                  </p>
                </div>
              )}
              {jobData.status === 'completed' && jobData.errors?.length > 0 && (
                <p className="text-xs text-orange-600 mt-1">
                  {jobData.errors.length} paper(s) had errors
                </p>
              )}
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleDismiss();
            }}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        
        {jobData.status === 'processing' && (
          <p className="text-xs text-gray-500 mt-2">
            Click to view details →
          </p>
        )}
      </div>
    </div>
  );
};

export default GlobalGradingProgress;
