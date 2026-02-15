import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { GraduationCap, Loader2, Mail } from "lucide-react";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";

const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
const API = `${BACKEND_URL}/api`;

export default function LoginPage() {
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);
  const [examType, setExamType] = useState("upsc");

  // Check for existing session on page load
  useEffect(() => {
    const checkExistingSession = async () => {
      try {
        const response = await axios.get(`${API}/auth/me`, { withCredentials: true });
        
        if (response.data) {
          // User has valid session, redirect to appropriate dashboard
          const redirectPath = response.data.role === "teacher" 
            ? "/teacher/dashboard" 
            : "/student/dashboard";
          navigate(redirectPath, { replace: true });
        }
      } catch (error) {
        // No valid session, show login page
        setChecking(false);
      }
    };

    checkExistingSession();
  }, [navigate]);

  // Google OAuth login - using credentials from .env
  const handleGoogleLogin = (role) => {
    // Store role preference for after auth
    localStorage.setItem("preferredRole", role);
    localStorage.setItem("preferredExamType", examType);
    
    // Get Google Client ID from environment variable
    const GOOGLE_CLIENT_ID = process.env.REACT_APP_GOOGLE_CLIENT_ID;
    const REDIRECT_URI = encodeURIComponent(`${window.location.origin}/callback`);
    const SCOPE = encodeURIComponent("openid profile email");
    const STATE = encodeURIComponent(JSON.stringify({ role, exam_type: examType, timestamp: Date.now() }));
    
    // Redirect to Google OAuth
    window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${GOOGLE_CLIENT_ID}&redirect_uri=${REDIRECT_URI}&response_type=code&scope=${SCOPE}&state=${STATE}&access_type=offline&prompt=consent`;
  };

  // Show loading state while checking session
  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-orange-50 to-white">
        <div className="text-center">
          <Loader2 className="w-12 h-12 animate-spin text-primary mx-auto mb-4" />
          <p className="text-muted-foreground">Checking session...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-orange-50 to-white p-4">
      <div className="w-full max-w-md">
        {/* Logo and Title */}
        <div className="text-center mb-8 animate-fade-in">
          <div className="inline-flex items-center justify-center w-20 h-20 rounded-full bg-primary mb-4 shadow-lg shadow-orange-500/20">
            <GraduationCap className="w-10 h-10 text-white" />
          </div>
          <h1 className="text-4xl font-bold text-foreground tracking-tight">
            Grade<span className="text-primary">Sense</span>
          </h1>
          <p className="text-muted-foreground mt-2">
            AI-Powered Grading for Handwritten Answer Papers
          </p>
        </div>

        {/* Login Options */}
        <Card className="shadow-xl border-0 animate-fade-in stagger-1" data-testid="login-card">
          <CardHeader className="text-center pb-4">
            <CardTitle className="text-2xl">Welcome Back</CardTitle>
            <CardDescription>
              Choose exam type and role to continue with Google Sign In
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label className="text-sm">Exam Type (Required)</Label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setExamType("upsc")}
                  className={`p-3 rounded-lg border-2 transition-all text-left ${
                    examType === "upsc"
                      ? "border-orange-500 bg-orange-50 text-orange-700"
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className="font-semibold">UPSC</div>
                  <div className="text-xs text-gray-500">Competitive evaluation</div>
                </button>
                <button
                  type="button"
                  onClick={() => setExamType("college")}
                  className={`p-3 rounded-lg border-2 transition-all text-left ${
                    examType === "college"
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className="font-semibold">College/School</div>
                  <div className="text-xs text-gray-500">Academic evaluation</div>
                </button>
              </div>
            </div>
            {/* Teacher Login */}
            <Button
              onClick={() => handleGoogleLogin("teacher")}
              className="w-full h-14 text-lg rounded-xl bg-primary hover:bg-primary/90 shadow-md hover:shadow-lg transition-all"
              data-testid="teacher-login-btn"
            >
              <svg className="w-5 h-5 mr-3" viewBox="0 0 24 24">
                <path
                  fill="currentColor"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="currentColor"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="currentColor"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                />
                <path
                  fill="currentColor"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                />
              </svg>
              Sign in as Teacher
            </Button>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">Or</span>
              </div>
            </div>

            {/* Student Login */}
            <Button
              onClick={() => handleGoogleLogin("student")}
              variant="outline"
              className="w-full h-14 text-lg rounded-xl border-2 hover:border-primary hover:bg-primary/5 transition-all"
              data-testid="student-login-btn"
            >
              <svg className="w-5 h-5 mr-3" viewBox="0 0 24 24">
                <path
                  fill="currentColor"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="currentColor"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="currentColor"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                />
                <path
                  fill="currentColor"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                />
              </svg>
              Sign in as Student
            </Button>
          </CardContent>
        </Card>

        {/* Email/Password Auth Option */}
        <div className="mt-6 text-center animate-fade-in stagger-2">
          <div className="relative mb-4">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-300"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-4 bg-gradient-to-br from-blue-50 via-white to-purple-50 text-gray-500">
                Or use email & password
              </span>
            </div>
          </div>
          
          <Button
            variant="outline"
            onClick={() => navigate("/email-auth")}
            className="w-full max-w-sm border-2 hover:border-blue-400 hover:bg-blue-50"
          >
            <Mail className="w-5 h-5 mr-2" />
            Sign in with Email
          </Button>
          
          <p className="text-xs text-gray-500 mt-3">
            Use this if Google sign-in isn't working
          </p>
        </div>

        {/* Footer */}
        <p className="text-center text-sm text-muted-foreground mt-8 animate-fade-in stagger-2">
          Secure authentication powered by Google OAuth 2.0
        </p>
      </div>
    </div>
  );
}
