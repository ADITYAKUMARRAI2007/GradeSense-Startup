import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { toast } from 'sonner';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const ProfileSetup = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    contact: '',
    teacher_type: '',
    exam_category: ''
  });

  const teacherTypes = [
    { value: 'school', label: 'School Teacher' },
    { value: 'college', label: 'College Professor' },
    { value: 'competitive', label: 'Competitive Exam Coach' },
    { value: 'others', label: 'Others' }
  ];

  const examCategories = [
    { value: 'UPSC', label: 'UPSC' },
    { value: 'CA', label: 'CA' },
    { value: 'CLAT', label: 'CLAT' },
    { value: 'JEE', label: 'JEE' },
    { value: 'NEET', label: 'NEET' },
    { value: 'others', label: 'Others' }
  ];

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value,
      // Clear exam_category if teacher_type changes and is not competitive
      ...(name === 'teacher_type' && value !== 'competitive' ? { exam_category: '' } : {})
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Validation
    if (!formData.name || !formData.email || !formData.contact || !formData.teacher_type) {
      toast.error('All fields are required');
      return;
    }

    if (formData.teacher_type === 'competitive' && !formData.exam_category) {
      toast.error('Please select an exam category');
      return;
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(formData.email)) {
      toast.error('Please enter a valid email address');
      return;
    }

    // Validate contact number
    const phoneRegex = /^[0-9]{10}$/;
    if (!phoneRegex.test(formData.contact)) {
      toast.error('Please enter a valid 10-digit phone number');
      return;
    }

    setLoading(true);
    try {
      await axios.put(`${API}/profile/complete`, formData, {
        withCredentials: true
      });
      
      toast.success('Profile setup complete!');
      navigate('/teacher/dashboard');
    } catch (error) {
      console.error('Profile setup error:', error);
      toast.error(error.response?.data?.detail || 'Failed to complete profile setup');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-800 mb-2">Welcome to GradeSense!</h1>
          <p className="text-gray-600">Let's set up your profile to get started</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Full Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              name="name"
              value={formData.name}
              onChange={handleChange}
              placeholder="Enter your full name"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {/* Email */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Email Address <span className="text-red-500">*</span>
            </label>
            <input
              type="email"
              name="email"
              value={formData.email}
              onChange={handleChange}
              placeholder="your.email@example.com"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {/* Contact */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Contact Number <span className="text-red-500">*</span>
            </label>
            <input
              type="tel"
              name="contact"
              value={formData.contact}
              onChange={handleChange}
              placeholder="10-digit mobile number"
              maxLength="10"
              pattern="[0-9]{10}"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>

          {/* Teacher Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              What type of teacher are you? <span className="text-red-500">*</span>
            </label>
            <select
              name="teacher_type"
              value={formData.teacher_type}
              onChange={handleChange}
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            >
              <option value="">Select teacher type</option>
              {teacherTypes.map(type => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
          </div>

          {/* Exam Category (conditional) */}
          {formData.teacher_type === 'competitive' && (
            <div className="animate-fadeIn">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Exam Category <span className="text-red-500">*</span>
              </label>
              <select
                name="exam_category"
                value={formData.exam_category}
                onChange={handleChange}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              >
                <option value="">Select exam category</option>
                {examCategories.map(category => (
                  <option key={category.value} value={category.value}>
                    {category.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-gradient-to-r from-blue-600 to-indigo-600 text-white py-3 px-6 rounded-lg font-semibold hover:from-blue-700 hover:to-indigo-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {loading ? 'Setting up...' : 'Complete Setup & Continue'}
          </button>
        </form>

        <p className="text-center text-sm text-gray-500 mt-6">
          All fields are required to complete your profile
        </p>
      </div>
    </div>
  );
};

export default ProfileSetup;
