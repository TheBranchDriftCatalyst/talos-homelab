import { useState } from 'react';
import type { Issue, IssueStatus } from '../../lib/types';
import { STATUS_LABELS, TYPE_LABELS, PRIORITY_LABELS } from '../../lib/types';
import {
  getStatusColor,
  getTypeColor,
  getPriorityColor,
  formatDate,
  getRelativeTime,
} from '../../lib/transformers';
import { MarkdownEditor } from './MarkdownEditor';

interface IssueDetailProps {
  issue: Issue;
  onClose: () => void;
  onUpdate: (id: string, changes: Partial<Issue>) => Promise<Issue | null>;
  onCloseIssue: (id: string, reason?: string) => Promise<boolean>;
}

export function IssueDetail({ issue, onClose, onUpdate, onCloseIssue }: IssueDetailProps) {
  const [editing, setEditing] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [saving, setSaving] = useState(false);

  const startEdit = (field: string, value: string) => {
    setEditing(field);
    setEditValue(value || '');
  };

  const cancelEdit = () => {
    setEditing(null);
    setEditValue('');
  };

  const saveEdit = async (field: string) => {
    setSaving(true);
    await onUpdate(issue.id, { [field]: editValue || null });
    setEditing(null);
    setEditValue('');
    setSaving(false);
  };

  const handleStatusChange = async (newStatus: IssueStatus) => {
    if (newStatus === 'closed') {
      await onCloseIssue(issue.id);
    } else {
      await onUpdate(issue.id, { status: newStatus });
    }
  };

  const handlePriorityChange = async (priority: number) => {
    await onUpdate(issue.id, { priority });
  };

  return (
    <div className="w-96 bg-slate-800 border-l border-slate-700 flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-slate-700 flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${getTypeColor(issue.issue_type)} text-white`}>
              {TYPE_LABELS[issue.issue_type]}
            </span>
            <span className="text-slate-500 text-sm">{issue.id}</span>
          </div>
          {editing === 'title' ? (
            <input
              type="text"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onBlur={() => saveEdit('title')}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveEdit('title');
                if (e.key === 'Escape') cancelEdit();
              }}
              className="w-full px-2 py-1 bg-slate-700 border border-slate-600 rounded text-slate-100 text-lg font-semibold focus:outline-none focus:border-indigo-500"
              autoFocus
            />
          ) : (
            <h2
              className="text-lg font-semibold text-slate-100 cursor-pointer hover:text-white truncate"
              onClick={() => startEdit('title', issue.title)}
              title="Click to edit"
            >
              {issue.title}
            </h2>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1 text-slate-400 hover:text-slate-200 ml-2"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Status & Priority */}
      <div className="p-4 border-b border-slate-700 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-400">Status</span>
          <select
            value={issue.status}
            onChange={(e) => handleStatusChange(e.target.value as IssueStatus)}
            className={`px-2 py-1 rounded text-xs font-medium ${getStatusColor(issue.status)} text-white bg-opacity-80 cursor-pointer`}
          >
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-400">Priority</span>
          <select
            value={issue.priority}
            onChange={(e) => handlePriorityChange(Number(e.target.value))}
            className={`px-2 py-1 rounded text-xs font-medium bg-slate-700 cursor-pointer ${getPriorityColor(issue.priority)}`}
          >
            {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-400">Assignee</span>
          {editing === 'assignee' ? (
            <input
              type="text"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onBlur={() => saveEdit('assignee')}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveEdit('assignee');
                if (e.key === 'Escape') cancelEdit();
              }}
              placeholder="Unassigned"
              className="px-2 py-1 bg-slate-700 border border-slate-600 rounded text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
              autoFocus
            />
          ) : (
            <span
              className="text-sm text-slate-300 cursor-pointer hover:text-white"
              onClick={() => startEdit('assignee', issue.assignee || '')}
            >
              {issue.assignee || 'Unassigned'}
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Description */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-slate-300">Description</h3>
            {editing !== 'description' && (
              <button
                onClick={() => startEdit('description', issue.description || '')}
                className="text-xs text-indigo-400 hover:text-indigo-300"
              >
                Edit
              </button>
            )}
          </div>
          {editing === 'description' ? (
            <div className="space-y-2">
              <MarkdownEditor
                value={editValue}
                onChange={setEditValue}
                placeholder="Add a description..."
              />
              <div className="flex gap-2">
                <button
                  onClick={() => saveEdit('description')}
                  disabled={saving}
                  className="px-3 py-1 bg-indigo-600 text-white rounded text-xs font-medium hover:bg-indigo-700 disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
                <button
                  onClick={cancelEdit}
                  className="px-3 py-1 bg-slate-700 text-slate-300 rounded text-xs font-medium hover:bg-slate-600"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div
              className="text-sm text-slate-400 cursor-pointer hover:text-slate-300 min-h-[2rem]"
              onClick={() => startEdit('description', issue.description || '')}
            >
              {issue.description || 'No description'}
            </div>
          )}
        </div>

        {/* Design Notes */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-slate-300">Design Notes</h3>
            {editing !== 'design' && (
              <button
                onClick={() => startEdit('design', issue.design || '')}
                className="text-xs text-indigo-400 hover:text-indigo-300"
              >
                Edit
              </button>
            )}
          </div>
          {editing === 'design' ? (
            <div className="space-y-2">
              <MarkdownEditor
                value={editValue}
                onChange={setEditValue}
                placeholder="Add design notes..."
              />
              <div className="flex gap-2">
                <button
                  onClick={() => saveEdit('design')}
                  disabled={saving}
                  className="px-3 py-1 bg-indigo-600 text-white rounded text-xs font-medium hover:bg-indigo-700 disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
                <button
                  onClick={cancelEdit}
                  className="px-3 py-1 bg-slate-700 text-slate-300 rounded text-xs font-medium hover:bg-slate-600"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div
              className="text-sm text-slate-400 cursor-pointer hover:text-slate-300 min-h-[2rem]"
              onClick={() => startEdit('design', issue.design || '')}
            >
              {issue.design || 'No design notes'}
            </div>
          )}
        </div>

        {/* Acceptance Criteria */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-slate-300">Acceptance Criteria</h3>
            {editing !== 'acceptance_criteria' && (
              <button
                onClick={() => startEdit('acceptance_criteria', issue.acceptance_criteria || '')}
                className="text-xs text-indigo-400 hover:text-indigo-300"
              >
                Edit
              </button>
            )}
          </div>
          {editing === 'acceptance_criteria' ? (
            <div className="space-y-2">
              <MarkdownEditor
                value={editValue}
                onChange={setEditValue}
                placeholder="Add acceptance criteria..."
              />
              <div className="flex gap-2">
                <button
                  onClick={() => saveEdit('acceptance_criteria')}
                  disabled={saving}
                  className="px-3 py-1 bg-indigo-600 text-white rounded text-xs font-medium hover:bg-indigo-700 disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
                <button
                  onClick={cancelEdit}
                  className="px-3 py-1 bg-slate-700 text-slate-300 rounded text-xs font-medium hover:bg-slate-600"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div
              className="text-sm text-slate-400 cursor-pointer hover:text-slate-300 min-h-[2rem]"
              onClick={() => startEdit('acceptance_criteria', issue.acceptance_criteria || '')}
            >
              {issue.acceptance_criteria || 'No acceptance criteria'}
            </div>
          )}
        </div>

        {/* Labels */}
        <div>
          <h3 className="text-sm font-medium text-slate-300 mb-2">Labels</h3>
          <div className="flex flex-wrap gap-1">
            {issue.labels.length > 0 ? (
              issue.labels.map((label) => (
                <span
                  key={label}
                  className="px-2 py-0.5 bg-slate-700 text-slate-300 rounded text-xs"
                >
                  {label}
                </span>
              ))
            ) : (
              <span className="text-sm text-slate-500">No labels</span>
            )}
          </div>
        </div>

        {/* Dependencies */}
        {issue.dependencies.length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-slate-300 mb-2">Dependencies</h3>
            <div className="space-y-1">
              {issue.dependencies.map((dep) => (
                <div
                  key={`${dep.issue_id}-${dep.depends_on_id}`}
                  className="flex items-center gap-2 text-xs"
                >
                  <span className="text-slate-500">{dep.type}:</span>
                  <span className="text-slate-300">{dep.depends_on_id}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-slate-700 text-xs text-slate-500">
        <div>Created: {formatDate(issue.created_at)}</div>
        <div>Updated: {getRelativeTime(issue.updated_at)}</div>
        {issue.closed_at && <div>Closed: {formatDate(issue.closed_at)}</div>}
      </div>
    </div>
  );
}
