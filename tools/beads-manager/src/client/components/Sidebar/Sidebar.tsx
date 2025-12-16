import { useState } from 'react';
import type { Issue, IssueType } from '../../lib/types';
import { STATUS_LABELS, TYPE_LABELS } from '../../lib/types';
import { getStatusColor, getTypeColor } from '../../lib/transformers';

interface SidebarProps {
  view: 'graph' | 'list';
  onViewChange: (view: 'graph' | 'list') => void;
  filters: {
    status: string[];
    type: string[];
    priority: number[];
  };
  onFiltersChange: (filters: { status: string[]; type: string[]; priority: number[] }) => void;
  issues: Issue[];
  onCreateIssue: (issue: Partial<Issue>) => Promise<Issue | null>;
}

export function Sidebar({
  view,
  onViewChange,
  filters,
  onFiltersChange,
  issues,
  onCreateIssue,
}: SidebarProps) {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newType, setNewType] = useState<IssueType>('task');
  const [creating, setCreating] = useState(false);

  const toggleFilter = (category: 'status' | 'type', value: string) => {
    const current = filters[category];
    const updated = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onFiltersChange({ ...filters, [category]: updated });
  };

  const handleCreate = async () => {
    if (!newTitle.trim()) return;

    setCreating(true);
    const result = await onCreateIssue({
      title: newTitle.trim(),
      issue_type: newType,
    });

    if (result) {
      setNewTitle('');
      setShowCreateForm(false);
    }
    setCreating(false);
  };

  // Calculate stats
  const stats = {
    total: issues.length,
    open: issues.filter((i) => i.status === 'open').length,
    inProgress: issues.filter((i) => i.status === 'in_progress').length,
    blocked: issues.filter((i) => i.status === 'blocked').length,
    closed: issues.filter((i) => i.status === 'closed').length,
  };

  return (
    <aside className="w-64 bg-slate-800 border-r border-slate-700 flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-slate-700">
        <h1 className="text-xl font-bold text-slate-100">Beads Manager</h1>
        <p className="text-sm text-slate-400 mt-1">{stats.total} issues</p>
      </div>

      {/* View Toggle */}
      <div className="p-4 border-b border-slate-700">
        <div className="flex gap-2">
          <button
            onClick={() => onViewChange('graph')}
            className={`flex-1 px-3 py-2 rounded text-sm font-medium transition-colors ${
              view === 'graph'
                ? 'bg-indigo-600 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            Graph
          </button>
          <button
            onClick={() => onViewChange('list')}
            className={`flex-1 px-3 py-2 rounded text-sm font-medium transition-colors ${
              view === 'list'
                ? 'bg-indigo-600 text-white'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >
            List
          </button>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="p-4 border-b border-slate-700">
        <h2 className="text-sm font-medium text-slate-400 mb-2">Status</h2>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-status-open" />
            <span className="text-slate-300">Open: {stats.open}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-status-progress" />
            <span className="text-slate-300">Active: {stats.inProgress}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-status-blocked" />
            <span className="text-slate-300">Blocked: {stats.blocked}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-status-closed" />
            <span className="text-slate-300">Done: {stats.closed}</span>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="p-4 border-b border-slate-700 flex-1 overflow-y-auto">
        <h2 className="text-sm font-medium text-slate-400 mb-2">Filter by Status</h2>
        <div className="flex flex-wrap gap-2 mb-4">
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <button
              key={value}
              onClick={() => toggleFilter('status', value)}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                filters.status.includes(value)
                  ? `${getStatusColor(value)} text-white`
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <h2 className="text-sm font-medium text-slate-400 mb-2">Filter by Type</h2>
        <div className="flex flex-wrap gap-2">
          {Object.entries(TYPE_LABELS).map(([value, label]) => (
            <button
              key={value}
              onClick={() => toggleFilter('type', value)}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                filters.type.includes(value)
                  ? `${getTypeColor(value)} text-white`
                  : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {(filters.status.length > 0 || filters.type.length > 0) && (
          <button
            onClick={() => onFiltersChange({ status: [], type: [], priority: [] })}
            className="mt-4 text-sm text-slate-400 hover:text-slate-200"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Create Issue */}
      <div className="p-4 border-t border-slate-700">
        {showCreateForm ? (
          <div className="space-y-2">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="Issue title..."
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-slate-100 placeholder-slate-400 focus:outline-none focus:border-indigo-500"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreate();
                if (e.key === 'Escape') setShowCreateForm(false);
              }}
            />
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value as IssueType)}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
            >
              {Object.entries(TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <div className="flex gap-2">
              <button
                onClick={handleCreate}
                disabled={creating || !newTitle.trim()}
                className="flex-1 px-3 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {creating ? 'Creating...' : 'Create'}
              </button>
              <button
                onClick={() => setShowCreateForm(false)}
                className="px-3 py-2 bg-slate-700 text-slate-300 rounded text-sm font-medium hover:bg-slate-600"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowCreateForm(true)}
            className="w-full px-3 py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700"
          >
            + New Issue
          </button>
        )}
      </div>
    </aside>
  );
}
