import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Search, Filter, Copy, Edit, Trash2, Grid, List, X, Save } from 'lucide-react';

const RubricLibrary: React.FC = () => {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [searchTerm, setSearchTerm] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState<{ action: string; id: number } | null>(null);
  
  const [newRubric, setNewRubric] = useState({
    name: '',
    subject: '',
    criteria: [
      { name: 'Content Knowledge', weight: 25, description: '' },
      { name: 'Structure & Flow', weight: 25, description: '' },
      { name: 'Examples & Analysis', weight: 25, description: '' },
      { name: 'Writing Quality', weight: 25, description: '' },
    ]
  });

  const [rubrics, setRubrics] = useState([
    {
      id: 1,
      name: 'Public Administration Essay Rubric',
      subject: 'Public Administration',
      criteria: 4,
      creator: 'Sanyam Sharma',
      lastUsed: '2 days ago',
      tags: ['Essay', 'UPSC', 'Mains'],
    },
    {
      id: 2,
      name: 'Ethics Answer Rubric',
      subject: 'Ethics',
      criteria: 5,
      creator: 'Priya Singh',
      lastUsed: '1 week ago',
      tags: ['Theory', 'Analysis'],
    },
    {
      id: 3,
      name: 'Geography Descriptive Rubric',
      subject: 'Geography',
      criteria: 3,
      creator: 'Rajesh Kumar',
      lastUsed: '3 days ago',
      tags: ['Descriptive', 'Maps'],
    },
  ]);

  const filteredRubrics = useMemo(() => {
    const lowerSearchTerm = searchTerm.toLowerCase();
    return rubrics.filter(rubric =>
      rubric.name.toLowerCase().includes(lowerSearchTerm) ||
      rubric.subject.toLowerCase().includes(lowerSearchTerm)
    );
  }, [rubrics, searchTerm]);

  const handleCreateRubric = () => {
    const totalWeight = newRubric.criteria.reduce((sum, c) => sum + c.weight, 0);
    if (totalWeight !== 100) {
      alert('Total criteria weights must equal 100%');
      return;
    }

    const rubric = {
      id: Date.now(),
      name: newRubric.name,
      subject: newRubric.subject,
      criteria: newRubric.criteria.length,
      creator: 'Sanyam Sharma',
      lastUsed: 'Just created',
      tags: ['Custom'],
    };

    setRubrics(prev => [rubric, ...prev]);
    setShowCreateModal(false);
    setNewRubric({
      name: '',
      subject: '',
      criteria: [
        { name: 'Content Knowledge', weight: 25, description: '' },
        { name: 'Structure & Flow', weight: 25, description: '' },
        { name: 'Examples & Analysis', weight: 25, description: '' },
        { name: 'Writing Quality', weight: 25, description: '' },
      ]
    });
    alert('Rubric created successfully!');
  };

  const handleRubricAction = (action: string, id: number) => {
    switch (action) {
      case 'use':
        alert(`Using rubric ${id} - This would redirect to New Batch with this rubric preloaded`);
        window.location.href = '/new-batch';
        break;
      case 'duplicate': {
        const original = rubrics.find(r => r.id === id);
        if (original) {
          const duplicate = {
            ...original,
            id: Date.now(),
            name: `${original.name} (Copy)`,
            lastUsed: 'Just created'
          };
          setRubrics(prev => [duplicate, ...prev]);
          alert('Rubric duplicated successfully!');
        }
        break;
      }
      case 'edit':
        alert(`Edit rubric ${id} - This would open the rubric editor`);
        break;
      case 'delete':
        setShowConfirmModal({ action: 'delete', id });
        break;
    }
  };

  const confirmAction = () => {
    if (showConfirmModal?.action === 'delete') {
      setRubrics(prev => prev.filter(r => r.id !== showConfirmModal.id));
      alert('Rubric deleted successfully!');
    }
    setShowConfirmModal(null);
  };

  const updateCriteriaWeight = (index: number, weight: number) => {
    const newCriteria = [...newRubric.criteria];
    newCriteria[index].weight = weight;
    
    // Auto-adjust other criteria to maintain 100% total
    // const otherTotal = newCriteria.reduce((sum, c, i) => i === index ? sum : sum + c.weight, 0);
    const remaining = 100 - weight;
    const otherCount = newCriteria.length - 1;
    
    if (otherCount > 0 && remaining >= 0) {
      const avgOther = Math.floor(remaining / otherCount);
      const remainder = remaining % otherCount;
      
      newCriteria.forEach((c, i) => {
        if (i !== index) {
          c.weight = avgOther + (i < remainder ? 1 : 0);
        }
      });
    }
    
    setNewRubric(prev => ({ ...prev, criteria: newCriteria }));
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-7xl mx-auto"
    >
      <div className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Rubric Library</h1>
            <p className="text-gray-600">Manage and organize your grading rubrics</p>
          </div>
          <button 
            onClick={() => setShowCreateModal(true)}
            className="bg-orange-500 text-white px-6 py-3 rounded-lg hover:bg-orange-600 transition-colors flex items-center space-x-2"
          >
            <Plus className="w-5 h-5" />
            <span>Create New Rubric</span>
          </button>
        </div>
      </div>

      {/* Filters and Search */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-6">
        <div className="flex flex-col md:flex-row items-center justify-between space-y-4 md:space-y-0">
          <div className="flex items-center space-x-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                placeholder="Search rubrics..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent w-64"
              />
            </div>
            
            <div className="flex items-center space-x-2">
              <Filter className="w-5 h-5 text-gray-400" />
              <select className="border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-orange-500 focus:border-transparent">
                <option value="">All Subjects</option>
                <option value="essay">Essay</option>
                <option value="ethics">Ethics</option>
                <option value="general-studies">General Studies</option>
                <option value="general-studies-iii">General Studies - III</option>
                <option value="geography">Geography</option>
                <option value="philosophy">Philosophy</option>
                <option value="psychology">Psychology</option>
                <option value="public-administration">Public Administration</option>
                <option value="sociology">Sociology</option>
              </select>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={() => setViewMode('list')}
              className={`p-2 rounded-lg transition-colors ${
                viewMode === 'list' ? 'bg-orange-100 text-orange-600' : 'text-gray-400 hover:text-gray-600'
              }`}
            >
              <List className="w-5 h-5" />
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`p-2 rounded-lg transition-colors ${
                viewMode === 'grid' ? 'bg-orange-100 text-orange-600' : 'text-gray-400 hover:text-gray-600'
              }`}
            >
              <Grid className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>

      {/* Rubrics Display */}
      {viewMode === 'grid' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredRubrics.map((rubric, index) => (
            <motion.div
              key={rubric.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">{rubric.name}</h3>
                  <p className="text-sm text-gray-600">{rubric.subject}</p>
                </div>
                <div className="flex items-center space-x-1">
                  <button 
                    onClick={() => handleRubricAction('duplicate', rubric.id)}
                    className="p-1 text-gray-400 hover:text-orange-600 transition-colors"
                  >
                    <Copy className="w-4 h-4" />
                  </button>
                  <button 
                    onClick={() => handleRubricAction('edit', rubric.id)}
                    className="p-1 text-gray-400 hover:text-blue-600 transition-colors"
                  >
                    <Edit className="w-4 h-4" />
                  </button>
                  <button 
                    onClick={() => handleRubricAction('delete', rubric.id)}
                    className="p-1 text-gray-400 hover:text-red-600 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="space-y-3 mb-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-600">Criteria</span>
                  <span className="font-medium text-gray-900">{rubric.criteria}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-600">Creator</span>
                  <span className="font-medium text-gray-900">{rubric.creator}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-600">Last Used</span>
                  <span className="font-medium text-gray-900">{rubric.lastUsed}</span>
                </div>
              </div>

              <div className="flex flex-wrap gap-2 mb-4">
                {rubric.tags.map((tag) => (
                  <span key={tag} className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">
                    {tag}
                  </span>
                ))}
              </div>

              <div className="flex space-x-2">
                <button 
                  onClick={() => handleRubricAction('use', rubric.id)}
                  className="flex-1 bg-orange-500 text-white py-2 rounded-lg hover:bg-orange-600 transition-colors text-sm"
                >
                  Use Rubric
                </button>
                <button 
                  onClick={() => handleRubricAction('duplicate', rubric.id)}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors text-sm"
                >
                  Duplicate
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100">
          <div className="p-6">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left py-3 px-4 font-medium text-gray-900">Name</th>
                    <th className="text-left py-3 px-4 font-medium text-gray-900">Subject</th>
                    <th className="text-left py-3 px-4 font-medium text-gray-900">Criteria</th>
                    <th className="text-left py-3 px-4 font-medium text-gray-900">Creator</th>
                    <th className="text-left py-3 px-4 font-medium text-gray-900">Last Used</th>
                    <th className="text-left py-3 px-4 font-medium text-gray-900">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRubrics.map((rubric) => (
                    <tr key={rubric.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="py-4 px-4">
                        <div>
                          <p className="font-medium text-gray-900">{rubric.name}</p>
                          <div className="flex space-x-1 mt-1">
                            {rubric.tags.map((tag) => (
                              <span key={tag} className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs">
                                {tag}
                              </span>
                            ))}
                          </div>
                        </div>
                      </td>
                      <td className="py-4 px-4 text-gray-600">{rubric.subject}</td>
                      <td className="py-4 px-4 text-gray-600">{rubric.criteria}</td>
                      <td className="py-4 px-4 text-gray-600">{rubric.creator}</td>
                      <td className="py-4 px-4 text-gray-600">{rubric.lastUsed}</td>
                      <td className="py-4 px-4">
                        <div className="flex items-center space-x-2">
                          <button 
                            onClick={() => handleRubricAction('use', rubric.id)}
                            className="text-orange-600 hover:text-orange-700 text-sm font-medium"
                          >
                            Use
                          </button>
                          <button 
                            onClick={() => handleRubricAction('duplicate', rubric.id)}
                            className="p-1 text-gray-400 hover:text-orange-600 transition-colors"
                          >
                            <Copy className="w-4 h-4" />
                          </button>
                          <button 
                            onClick={() => handleRubricAction('edit', rubric.id)}
                            className="p-1 text-gray-400 hover:text-blue-600 transition-colors"
                          >
                            <Edit className="w-4 h-4" />
                          </button>
                          <button 
                            onClick={() => handleRubricAction('delete', rubric.id)}
                            className="p-1 text-gray-400 hover:text-red-600 transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Create Rubric Modal */}
      <AnimatePresence>
        {showCreateModal && (
          <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-4xl bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden max-h-[90vh] overflow-y-auto"
            >
              <div className="p-6 border-b border-gray-200">
                <div className="flex items-center justify-between">
                  <h2 className="text-2xl font-semibold text-gray-900">Create New Rubric</h2>
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
              </div>

              <div className="p-6 space-y-6">
                {/* Basic Info */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Rubric Name *
                    </label>
                    <input
                      type="text"
                      value={newRubric.name}
                      onChange={(e) => setNewRubric(prev => ({ ...prev, name: e.target.value }))}
                      className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                      placeholder="e.g., Public Administration Essay Rubric"
                    />
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Subject *
                    </label>
                    <select
                      value={newRubric.subject}
                      onChange={(e) => setNewRubric(prev => ({ ...prev, subject: e.target.value }))}
                      className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                    >
                      <option value="">Select Subject</option>
                      <option value="Essay">Essay</option>
                      <option value="Ethics">Ethics</option>
                      <option value="General Studies">General Studies</option>
                      <option value="General Studies - III">General Studies - III</option>
                      <option value="Geography">Geography</option>
                      <option value="Philosophy">Philosophy</option>
                      <option value="Psychology">Psychology</option>
                      <option value="Public Administration">Public Administration</option>
                      <option value="Sociology">Sociology</option>
                    </select>
                  </div>
                </div>

                {/* Criteria */}
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-medium text-gray-900">Grading Criteria</h3>
                    <div className="text-sm text-gray-600">
                      Total: {newRubric.criteria.reduce((sum, c) => sum + c.weight, 0)}%
                    </div>
                  </div>
                  
                  <div className="space-y-4">
                    {newRubric.criteria.map((criterion, index) => (
                      <div key={index} className="p-4 border border-gray-200 rounded-lg">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-3">
                          <input
                            type="text"
                            value={criterion.name}
                            onChange={(e) => {
                              const newCriteria = [...newRubric.criteria];
                              newCriteria[index].name = e.target.value;
                              setNewRubric(prev => ({ ...prev, criteria: newCriteria }));
                            }}
                            className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                            placeholder="Criterion name"
                          />
                          
                          <div className="flex items-center space-x-3">
                            <input
                              type="range"
                              min="0"
                              max="100"
                              value={criterion.weight}
                              onChange={(e) => updateCriteriaWeight(index, parseInt(e.target.value))}
                              className="flex-1"
                            />
                            <span className="w-12 text-sm font-medium text-gray-900">
                              {criterion.weight}%
                            </span>
                          </div>
                          
                          <input
                            type="number"
                            value={criterion.weight}
                            onChange={(e) => updateCriteriaWeight(index, parseInt(e.target.value) || 0)}
                            className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                            min="0"
                            max="100"
                          />
                        </div>
                        
                        <textarea
                          value={criterion.description}
                          onChange={(e) => {
                            const newCriteria = [...newRubric.criteria];
                            newCriteria[index].description = e.target.value;
                            setNewRubric(prev => ({ ...prev, criteria: newCriteria }));
                          }}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                          placeholder="Description of what this criterion evaluates..."
                          rows={2}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="p-6 border-t border-gray-200 bg-gray-50 flex items-center justify-between">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateRubric}
                  disabled={!newRubric.name || !newRubric.subject}
                  className="flex items-center space-x-2 bg-orange-500 text-white px-6 py-2 rounded-lg hover:bg-orange-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Save className="w-4 h-4" />
                  <span>Create Rubric</span>
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Confirmation Modal */}
      <AnimatePresence>
        {showConfirmModal && (
          <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="w-full max-w-md bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden"
            >
              <div className="p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-2">Confirm Action</h3>
                <p className="text-gray-600 mb-6">
                  Are you sure you want to delete this rubric? This action cannot be undone.
                </p>
                <div className="flex space-x-3">
                  <button
                    onClick={() => setShowConfirmModal(null)}
                    className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={confirmAction}
                    className="flex-1 px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

export default RubricLibrary;