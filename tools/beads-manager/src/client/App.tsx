import { useState } from 'react';
import { Sidebar } from './components/Sidebar/Sidebar';
import { DependencyGraph } from './components/DependencyGraph/DependencyGraph';
import { IssueDetail } from './components/IssueDetail/IssueDetail';
import { IssueList } from './components/IssueList/IssueList';
import { useIssues } from './hooks/useIssues';
import { useWebSocket } from './hooks/useWebSocket';
import type { Issue } from './lib/types';

function App() {
  const { issues, loading, error, refresh, createIssue, updateIssue, closeIssue } = useIssues();
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null);
  const [view, setView] = useState<'graph' | 'list'>('graph');
  const [filters, setFilters] = useState({
    status: [] as string[],
    type: [] as string[],
    priority: [] as number[],
  });

  // WebSocket for real-time updates
  useWebSocket({
    onMessage: (msg) => {
      if (msg.type === 'refresh') {
        refresh();
      }
    },
  });

  // Filter issues
  const filteredIssues = issues.filter((issue) => {
    if (filters.status.length > 0 && !filters.status.includes(issue.status)) return false;
    if (filters.type.length > 0 && !filters.type.includes(issue.issue_type)) return false;
    if (filters.priority.length > 0 && !filters.priority.includes(issue.priority)) return false;
    return true;
  });

  const handleNodeClick = (issueId: string) => {
    const issue = issues.find((i) => i.id === issueId);
    setSelectedIssue(issue || null);
  };

  const handleCloseDetail = () => {
    setSelectedIssue(null);
  };

  const handleUpdateIssue = async (id: string, changes: Partial<Issue>): Promise<Issue | null> => {
    const result = await updateIssue(id, changes);
    // Update selected issue if it's the one being edited
    if (selectedIssue?.id === id && result) {
      setSelectedIssue({ ...selectedIssue, ...changes });
    }
    return result;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900">
        <div className="text-slate-300 text-lg">Loading issues...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900">
        <div className="text-red-400 text-lg">Error: {error}</div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-slate-900 text-slate-100">
      <Sidebar
        view={view}
        onViewChange={setView}
        filters={filters}
        onFiltersChange={setFilters}
        issues={issues}
        onCreateIssue={createIssue}
      />

      <main className="flex-1 relative overflow-hidden">
        {view === 'graph' ? (
          <DependencyGraph
            issues={filteredIssues}
            onNodeClick={handleNodeClick}
            selectedIssueId={selectedIssue?.id}
          />
        ) : (
          <IssueList
            issues={filteredIssues}
            onIssueClick={(issue) => setSelectedIssue(issue)}
            onUpdateIssue={handleUpdateIssue}
          />
        )}
      </main>

      {selectedIssue && (
        <IssueDetail
          issue={selectedIssue}
          onClose={handleCloseDetail}
          onUpdate={handleUpdateIssue}
          onCloseIssue={closeIssue}
        />
      )}
    </div>
  );
}

export default App;
