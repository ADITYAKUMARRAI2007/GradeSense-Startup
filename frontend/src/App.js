import { useEffect, useState, useRef } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import axios from "axios";
import { Toaster } from "./components/ui/sonner";

// Pages
import LoginPage from "./pages/LoginPage";
import EmailAuthPage from "./pages/EmailAuthPage";
import AuthCallback from "./pages/AuthCallback";
import ProfileSetup from "./pages/ProfileSetup";
import BatchView from './pages/teacher/BatchView';
import Dashboard from "./pages/teacher/Dashboard";
import UploadGrade from "./pages/teacher/UploadGrade";
import ReviewPapers from "./pages/teacher/ReviewPapers";
import ClassReports from "./pages/teacher/ClassReports";
import ClassInsights from "./pages/teacher/ClassInsights";
import Analytics from "./pages/teacher/Analytics";
import ManageStudents from "./pages/teacher/ManageStudents";
import ManageBatches from "./pages/teacher/ManageBatches";
import ManageExams from "./pages/teacher/ManageExams";
import ReEvaluations from "./pages/teacher/ReEvaluations";
import AddBatch from "./pages/teacher/AddBatch";
import BatchSettings from "./pages/teacher/BatchSettings";
import ManageStudentsInBatch from "./pages/teacher/ManageStudentsInBatch";
import CreateStudentExam from "./pages/teacher/CreateStudentExam";
import ExamSubmissionsView from "./pages/teacher/ExamSubmissionsView";
import StudentDashboard from "./pages/student/Dashboard";
import StudentExamsView from "./pages/student/StudentExamsView";
import StudentResults from "./pages/student/Results";
import StudentReEvaluation from "./pages/student/RequestReEvaluation";
import Settings from "./pages/Settings";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminFeedback from "./pages/admin/AdminFeedback";
import AdminAnalytics from "./pages/admin/AdminAnalytics";
import AdminUsersAdvanced from "./pages/admin/AdminUsersAdvanced";
import FeedbackBeacon from "./components/FeedbackBeacon";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || window.location.origin;
export const API = `${BACKEND_URL}/api`;

// Debug logging for environment (disabled in UI to keep console clean)
if (!process.env.REACT_APP_BACKEND_URL) {
  // Intentionally silent in UI
}

// Configure axios
axios.defaults.withCredentials = true;

// Auth context
export const useAuth = () => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuth = async () => {
    try {
      const response = await axios.get(`${API}/auth/me`);
      setUser(response.data);
      return response.data;
    } catch (error) {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await axios.post(`${API}/auth/logout`);
    } catch (error) {
      console.error("Logout error:", error);
    }
    setUser(null);
    window.location.href = "/login";
  };

  return { user, setUser, loading, checkAuth, logout };
};

// Protected Route wrapper
const ProtectedRoute = ({ children, allowedRoles }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(null);
  const [user, setUser] = useState(null);
  const [profileCheck, setProfileCheck] = useState(null);
  const navigate = useNavigate();
  const location = useLocation();
  const checkedRef = useRef(false);

  useEffect(() => {
    // If user was passed from AuthCallback, use it directly
    if (location.state?.user) {
      setUser(location.state.user);
      setIsAuthenticated(true);
      setProfileCheck({ profile_completed: true }); // User passed from AuthCallback is already validated
      return;
    }

    if (checkedRef.current) return;
    checkedRef.current = true;

    const checkAuth = async () => {
      try {
        const response = await axios.get(`${API}/auth/me`);
        setUser(response.data);
        setIsAuthenticated(true);

        // Check profile completion status
        try {
          const profileResponse = await axios.get(`${API}/profile/check`);
          setProfileCheck(profileResponse.data);
          
          // ONLY redirect to profile setup if EXPLICITLY marked as incomplete (false)
          // AND not already on profile setup page
          if (profileResponse.data.profile_completed === false && location.pathname !== '/profile/setup') {
            navigate('/profile/setup', { replace: true });
            return;
          }
          
          // If profile is complete (true or null for existing users), continue normally
        } catch (profileError) {
          console.error('Profile check error:', profileError);
          // If profile check fails, assume profile is complete (existing user)
          setProfileCheck({ profile_completed: true });
        }

        // Check role
        if (allowedRoles && !allowedRoles.includes(response.data.role)) {
          const redirectPath = response.data.role === "teacher" ? "/teacher/dashboard" : "/student/dashboard";
          navigate(redirectPath, { replace: true });
        }
      } catch (error) {
        setIsAuthenticated(false);
        navigate("/login", { replace: true });
      }
    };

    checkAuth();
  }, [navigate, allowedRoles, location.state, location.pathname]);

  if (isAuthenticated === null || profileCheck === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return children({ user, setUser });
};

// App Router with session_id detection
function AppRouter() {
  const location = useLocation();

  // CRITICAL: Detect session_id synchronously during render
  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  if (location.hash?.includes("session_id=")) {
    return <AuthCallback />;
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/email-auth" element={<EmailAuthPage />} />
      <Route path="/callback" element={<AuthCallback />} />
      <Route
        path="/profile/setup"
        element={
          <ProtectedRoute>
            {(props) => <ProfileSetup {...props} />}
          </ProtectedRoute>
        }
      />
      
      {/* Teacher Routes */}
      <Route
        path="/teacher/dashboard"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <Dashboard {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/batch/:batchId"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <BatchView {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/batches/create"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <AddBatch {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/batch/:batchId/settings"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <BatchSettings {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/batch/:batchId/students/add"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ManageStudentsInBatch {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/batch/:batchId/create-student-exam"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <CreateStudentExam {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/exam/:examId/submissions"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ExamSubmissionsView {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/upload"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <UploadGrade {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/review"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ReviewPapers {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/reports"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ClassReports {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/insights"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ClassInsights {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/analytics"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <Analytics {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/students"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ManageStudents {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/batches"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ManageBatches {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/exams"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ManageExams {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/re-evaluations"
        element={
          <ProtectedRoute allowedRoles={["teacher"]}>
            {(props) => <ReEvaluations {...props} />}
          </ProtectedRoute>
        }
      />

      {/* Student Routes */}
      <Route
        path="/student/dashboard"
        element={
          <ProtectedRoute allowedRoles={["student"]}>
            {(props) => <StudentDashboard {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/exams"
        element={
          <ProtectedRoute allowedRoles={["student"]}>
            {(props) => <StudentExamsView {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/results"
        element={
          <ProtectedRoute allowedRoles={["student"]}>
            {(props) => <StudentResults {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/re-evaluation"
        element={
          <ProtectedRoute allowedRoles={["student"]}>
            {(props) => <StudentReEvaluation {...props} />}
          </ProtectedRoute>
        }
      />

      {/* Shared Routes */}
      <Route
        path="/settings"
        element={
          <ProtectedRoute>
            {(props) => <Settings {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            {(props) => <AdminDashboard {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/feedback"
        element={
          <ProtectedRoute>
            {(props) => <AdminFeedback {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/analytics"
        element={
          <ProtectedRoute>
            {(props) => <AdminAnalytics {...props} />}
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/users"
        element={
          <ProtectedRoute>
            {(props) => <AdminUsersAdvanced {...props} />}
          </ProtectedRoute>
        }
      />

      {/* Default redirect */}
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AppRouter />
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </div>
  );
}

export default App;
