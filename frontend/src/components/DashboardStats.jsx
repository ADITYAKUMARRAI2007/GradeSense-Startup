import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { ChevronRight } from 'lucide-react';

const DashboardStats = ({ batches = [] }) => {
  const navigate = useNavigate();

  return (
    <div className="mb-8">
      {/* Batch Selector Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-700">📚 My Classes</h2>
        <Badge variant="outline" className="text-xs">
          {batches.length} {batches.length === 1 ? 'Batch' : 'Batches'}
        </Badge>
      </div>

      {/* Batch Cards Grid (Replaces the 4 actionable cards) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {/* Create New Batch Card */}
        <div
          onClick={() => navigate('/teacher/batches/create')}
          className="bg-white p-6 rounded-xl border-2 border-dashed border-gray-300 hover:border-primary hover:bg-gray-50 transition-all cursor-pointer group flex flex-col items-center justify-center min-h-[200px]"
        >
          <div className="w-16 h-16 rounded-full bg-gray-100 group-hover:bg-primary/10 flex items-center justify-center mb-4 transition-colors">
            <svg className="w-8 h-8 text-gray-400 group-hover:text-primary transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-gray-700 group-hover:text-primary transition-colors">
            Create New Class
          </h3>
          <p className="text-sm text-gray-500 mt-2 text-center">
            Add a new batch to start grading
          </p>
        </div>

        {/* Batch Cards */}
        {batches.map((batch) => (
          <div
            key={batch.batch_id}
            onClick={() => navigate(`/teacher/batch/${batch.batch_id}`)}
            className="bg-white p-6 rounded-xl border-2 border-gray-200 hover:shadow-lg hover:border-primary transition-all cursor-pointer group min-h-[200px] flex flex-col"
          >
            {/* Header */}
            <div className="flex items-start justify-between mb-4">
              <div className="flex-1">
                <h3 className="text-lg font-bold text-gray-900 mb-1 line-clamp-2 group-hover:text-primary transition-colors">
                  {batch.name}
                </h3>
                <p className="text-sm text-gray-500">
                  {batch.subject || 'General'}
                </p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                <svg className="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                </svg>
              </div>
            </div>

            {/* Live Status */}
            <div className="flex-1">
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-600 flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Exams
                  </span>
                  <span className="font-semibold text-gray-900">
                    {batch.exam_count || 0}
                  </span>
                </div>
                
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-600 flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                    </svg>
                    Students
                  </span>
                  <span className="font-semibold text-gray-900">
                    {batch.students?.length || 0}
                  </span>
                </div>

                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-600 flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                    </svg>
                    Average
                  </span>
                  <span className="font-semibold text-green-600">
                    {batch.average || 0}%
                  </span>
                </div>
              </div>
            </div>

            {/* Click indicator */}
            <div className="mt-4 pt-4 border-t border-gray-100">
              <div className="flex items-center text-primary text-sm font-medium group-hover:translate-x-1 transition-transform">
                View Class <ChevronRight size={16} className="ml-1" />
              </div>
            </div>
          </div>
        ))}

        {batches.length === 0 && (
          <div className="col-span-full text-center py-12">
            <svg className="w-16 h-16 text-gray-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
            </svg>
            <h3 className="text-xl font-semibold text-gray-600 mb-2">No Classes Yet</h3>
            <p className="text-gray-500 mb-6">Create your first class to start grading papers</p>
            <Button onClick={() => navigate('/teacher/batches/create')}>
              Create First Class
            </Button>
          </div>
        )}
      </div>
    </div>
  );
};

export default DashboardStats;
