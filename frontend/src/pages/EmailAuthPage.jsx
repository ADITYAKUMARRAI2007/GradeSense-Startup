import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Eye, EyeOff, Mail, Lock, User, ArrowLeft } from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";

const API_BASE = (process.env.REACT_APP_BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
const API = `${API_BASE}/api`;

export default function EmailAuthPage() {
  const navigate = useNavigate();
  const [isLogin, setIsLogin] = useState(true);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  
  const [formData, setFormData] = useState({
    email: "",
    password: "",
    name: "",
    role: "teacher",
    exam_type: "upsc"
  });

  const toErrorMessage = (error) => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail.map((item) => item?.msg || item?.type || "Validation error").join("; ");
    }
    if (detail && typeof detail === "object") {
      return detail.msg || detail.type || JSON.stringify(detail);
    }
    return error?.message || "Authentication failed";
  };

  const isPasswordTooLong = (password) => password && password.length > 0
    && new TextEncoder().encode(password).length > 72;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      if (isPasswordTooLong(formData.password)) {
        toast.error("Password must be 72 bytes or fewer. Please use a shorter password.");
        return;
      }

      const endpoint = isLogin ? "/auth/login" : "/auth/register";
      const payload = isLogin 
        ? { email: formData.email, password: formData.password, exam_type: formData.exam_type }
        : formData;

      const response = await axios.post(`${API}${endpoint}`, payload, {
        withCredentials: true
      });

      toast.success(isLogin ? "Login successful!" : "Account created successfully!");
      
      // Redirect based on role and profile completion
      const profileCompleted = response.data.profile_completed !== false; // Default to true if not specified
      
      let redirectPath;
      if (!profileCompleted) {
        // New users who haven't completed profile
        redirectPath = "/profile-setup";
      } else {
        // Existing users or users with completed profiles
        redirectPath = response.data.role === "teacher" 
          ? "/teacher/dashboard" 
          : "/student/dashboard";
      }
      
      // Reload to update auth context
      window.location.href = redirectPath;

    } catch (error) {
      console.error("Auth error:", error);
      const errorMessage = toErrorMessage(error);
      
      // If error mentions Google sign-in, show helpful message
      if (errorMessage.includes("Google sign-in")) {
        toast.error(errorMessage, {
          action: {
            label: "Set Password",
            onClick: () => setIsLogin("setPassword")
          }
        });
      } else {
        toast.error(errorMessage);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSetPassword = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      if (isPasswordTooLong(formData.password)) {
        toast.error("Password must be 72 bytes or fewer. Please use a shorter password.");
        return;
      }

      await axios.post(`${API}/auth/set-password`, {
        email: formData.email,
        new_password: formData.password
      });

      toast.success("Password set successfully! You can now login with your email and password.");
      setIsLogin(true); // Switch back to login
      
    } catch (error) {
      console.error("Set password error:", error);
      const errorMessage = toErrorMessage(error);
      toast.error(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Back button */}
        <Button
          variant="ghost"
          onClick={() => navigate("/login")}
          className="mb-4"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          Back to login options
        </Button>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100">
          {/* Logo & Title */}
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent mb-2">
              GradeSense
            </h1>
            <p className="text-gray-600">
              {isLogin === "setPassword" 
                ? "Set a password for your account" 
                : isLogin 
                ? "Sign in to your account" 
                : "Create your account"}
            </p>
          </div>

          {/* Form */}
          <form onSubmit={isLogin === "setPassword" ? handleSetPassword : handleSubmit} className="space-y-4">
            {/* Name (only for registration) */}
            {!isLogin && isLogin !== "setPassword" && (
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  Full Name
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <Input
                    type="text"
                    placeholder="Enter your name"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="pl-10"
                    required
                  />
                </div>
              </div>
            )}

            {/* Email */}
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">
                Email Address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <Input
                  type="email"
                  placeholder="you@example.com"
                  value={formData.email}
                  onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                  className="pl-10"
                  required
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">
                Password {isLogin === "setPassword" && "(New)"}
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <Input
                  type={showPassword ? "text" : "password"}
                  placeholder={isLogin ? "Enter password" : "Min. 8 characters"}
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  className="pl-10 pr-10"
                  required
                  minLength={8}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
            </div>

            {/* Role (only for registration) */}
            {!isLogin && isLogin !== "setPassword" && (
              <div>
                <label className="text-sm font-medium text-gray-700 mb-2 block">
                  I am a...
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, role: "teacher" })}
                    className={`p-3 rounded-lg border-2 transition-all ${
                      formData.role === "teacher"
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <div className="font-semibold">Teacher</div>
                    <div className="text-xs text-gray-500">Grade papers</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, role: "student" })}
                    className={`p-3 rounded-lg border-2 transition-all ${
                      formData.role === "student"
                        ? "border-purple-500 bg-purple-50 text-purple-700"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <div className="font-semibold">Student</div>
                    <div className="text-xs text-gray-500">Submit papers</div>
                  </button>
                </div>
              </div>
            )}

            {(isLogin !== "setPassword") && (
              <div>
                <label className="text-sm font-medium text-gray-700 mb-2 block">
                  Exam Type (Required)
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, exam_type: "upsc" })}
                    className={`p-3 rounded-lg border-2 transition-all text-left ${
                      formData.exam_type === "upsc"
                        ? "border-orange-500 bg-orange-50 text-orange-700"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <div className="font-semibold">UPSC</div>
                    <div className="text-xs text-gray-500">Competitive evaluation</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, exam_type: "college" })}
                    className={`p-3 rounded-lg border-2 transition-all text-left ${
                      formData.exam_type === "college"
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <div className="font-semibold">College/School</div>
                    <div className="text-xs text-gray-500">Academic evaluation</div>
                  </button>
                </div>
              </div>
            )}

            {/* Submit Button */}
            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700"
            >
              {loading 
                ? "Please wait..." 
                : isLogin === "setPassword" 
                ? "Set Password" 
                : isLogin 
                ? "Sign In" 
                : "Create Account"}
            </Button>
          </form>

          {/* Toggle Login/Register/SetPassword */}
          <div className="mt-6 text-center space-y-2">
            {isLogin === "setPassword" ? (
              <button
                type="button"
                onClick={() => setIsLogin(true)}
                className="text-sm text-gray-600 hover:text-gray-900"
              >
                Back to Sign In
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setIsLogin(!isLogin)}
                  className="text-sm text-gray-600 hover:text-gray-900 block w-full"
                >
                  {isLogin ? (
                    <>
                      Don&apos;t have an account? <span className="text-blue-600 font-semibold">Sign Up</span>
                    </>
                  ) : (
                    <>
                      Already have an account? <span className="text-blue-600 font-semibold">Sign In</span>
                    </>
                  )}
                </button>
                
                {isLogin && (
                  <button
                    type="button"
                    onClick={() => setIsLogin("setPassword")}
                    className="text-sm text-purple-600 hover:text-purple-800 font-medium"
                  >
                    Have a Google account? Set a password here
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
