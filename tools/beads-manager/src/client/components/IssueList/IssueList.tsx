import { useState, useMemo } from 'react';
import type { Issue, IssueStatus } from '../../lib/types';
import { STATUS_LABELS, TYPE_LABELS, PRIORITY_LABELS } from '../../lib/types';
import {
  getStatusColor,
  getTypeColor,
  getPriorityColor,
  getRelativeTime,
} from '../../lib/transformers';

interface IssueListProps {
  issues: Issue[];
  onIssueClick: (issue: Issue) => void;
  onUpdateIssue: (id: string, changes: Partial<Issue>) => Promise<Issue | null>;
}

type SortField = 'id' | 'title' | 'status' | 'priority' | 'type' | 'updated_at';
type SortDirection = 'asc' | 'desc';

export function IssueList({ issues, onIssueClick, onUpdateIssue }: IssueListProps) {
  const [sortField, setSortField] = useState<SortField>('updated_at');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [search, setSearch] = useState('');

  // Filter and sort issues
  const filteredIssues = useMemo(() => {
    let result = [...issues];

    // Search filter
    if (search) {
      const searchLower = search.toLowerCase();
      result = result.filter(
        (issue) =>
          issue.id.toLowerCase().includes(searchLower) ||
          issue.title.toLowerCase().includes(searchLower) ||
          issue.description?.toLowerCase().includes(searchLower)
      );
    }

    // Sort
    result.sort((a, b) => {
      let comparison = 0;

      switch (sortField) {
        case 'id':
          comparison = a.id.localeCompare(b.id);
          break;
        case 'title':
          comparison = a.title.localeCompare(b.title);
          break;
        case 'status':
          comparison = a.status.localeCompare(b.status);
          break;
        case 'priority':
          comparison = a.priority - b.priority;
          break;
        case 'type':
          comparison = a.issue_type.localeCompare(b.issue_type);
          break;
        case 'updated_at':
          comparison = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
          break;
      }

      return sortDirection === 'asc' ? comparison : -comparison;
    });

    return result;
  }, [issues, search, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return null;
    return (
      <span className="ml-1 text-indigo-400">
        {sortDirection === 'asc' ? '↑' : '↓'}
      </span>
    );
  };

  const handleStatusChange = async (issue: Issue, newStatus: IssueStatus, e: React.MouseEvent) => {
    e.stopPropagation();
    await onUpdateIssue(issue.id, { status: newStatus });
  };

  return (
    <div className="h-full flex flex-col bg-slate-900">
      {/* Search */}
      <div className="p-4 border-b border-slate-700">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search issues..."
          className="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
        />
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-slate-800 z-10">
            <tr className="text-left text-sm text-slate-400">
              <th
                className="px-4 py-3 font-medium cursor-pointer hover:text-slate-200"
                onClick={() => handleSort('id')}
              >
                ID <SortIcon field="id" />
              </th>
              <th
                className="px-4 py-3 font-medium cursor-pointer hover:text-slate-200"
                onClick={() => handleSort('title')}
              >
                Title <SortIcon field="title" />
              </th>
              <th
                className="px-4 py-3 font-medium cursor-pointer hover:text-slate-200"
                onClick={() => handleSort('type')}
              >
                Type <SortIcon field="type" />
              </th>
              <th
                className="px-4 py-3 font-medium cursor-pointer hover:text-slate-200"
                onClick={() => handleSort('status')}
              >
                Status <SortIcon field="status" />
              </th>
              <th
                className="px-4 py-3 font-medium cursor-pointer hover:text-slate-200"
                onClick={() => handleSort('priority')}
              >
                Priority <SortIcon field="priority" />
              </th>
              <th
                className="px-4 py-3 font-medium cursor-pointer hover:text-slate-200"
                onClick={() => handleSort('updated_at')}
              >
                Updated <SortIcon field="updated_at" />
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {filteredIssues.map((issue) => (
              <tr
                key={issue.id}
                onClick={() => onIssueClick(issue)}
                className="hover:bg-slate-800 cursor-pointer transition-colors"
              >
                <td className="px-4 py-3">
                  <span className="text-sm font-mono text-slate-500">{issue.id}</span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-200 truncate max-w-md">
                      {issue.title}
                    </span>
                    {(issue.labels?.length ?? 0) > 0 && (
                      <div className="flex gap-1">
                        {issue.labels.slice(0, 2).map((label) => (
                          <span
                            key={label}
                            className="px-1.5 py-0.5 bg-slate-700 text-slate-400 rounded text-xs"
                          >
                            {label}
                          </span>
                        ))}
                        {issue.labels.length > 2 && (
                          <span className="text-xs text-slate-500">
                            +{issue.labels.length - 2}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium ${getTypeColor(issue.issue_type)} text-white`}
                  >
                    {TYPE_LABELS[issue.issue_type]}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <select
                    value={issue.status}
                    onChange={(e) =>
                      handleStatusChange(issue, e.target.value as IssueStatus, e as any)
                    }
                    onClick={(e) => e.stopPropagation()}
                    className={`px-2 py-0.5 rounded text-xs font-medium ${getStatusColor(issue.status)} text-white bg-opacity-80 cursor-pointer border-0`}
                  >
                    {Object.entries(STATUS_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-sm ${getPriorityColor(issue.priority)}`}>
                    {PRIORITY_LABELS[issue.priority]}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="text-sm text-slate-500">
                    {getRelativeTime(issue.updated_at)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filteredIssues.length === 0 && (
          <div className="flex items-center justify-center h-64 text-slate-500">
            {search ? 'No issues match your search' : 'No issues found'}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-slate-700 text-sm text-slate-500">
        Showing {filteredIssues.length} of {issues.length} issues
      </div>
    </div>
  );
}
