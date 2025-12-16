import { useState, useEffect, useCallback } from 'react';
import type { Issue } from '../lib/types';

const API_BASE = '/api';

export function useIssues() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchIssues = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/issues`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const data = await response.json();
      setIssues(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch issues');
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await fetchIssues();
  }, [fetchIssues]);

  const createIssue = useCallback(async (issue: Partial<Issue>): Promise<Issue | null> => {
    try {
      const response = await fetch(`${API_BASE}/issues`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(issue),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      const newIssue = await response.json();
      setIssues((prev) => [...prev, newIssue]);
      return newIssue;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create issue');
      return null;
    }
  }, []);

  const updateIssue = useCallback(async (id: string, changes: Partial<Issue>): Promise<Issue | null> => {
    try {
      const response = await fetch(`${API_BASE}/issues/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      const updatedIssue = await response.json();
      setIssues((prev) =>
        prev.map((issue) => (issue.id === id ? { ...issue, ...updatedIssue } : issue))
      );
      return updatedIssue;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update issue');
      return null;
    }
  }, []);

  const closeIssue = useCallback(async (id: string, reason?: string): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE}/issues/${id}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      setIssues((prev) =>
        prev.map((issue) =>
          issue.id === id
            ? { ...issue, status: 'closed' as const, closed_at: new Date().toISOString() }
            : issue
        )
      );
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to close issue');
      return false;
    }
  }, []);

  const reopenIssue = useCallback(async (id: string): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE}/issues/${id}/reopen`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP ${response.status}`);
      }

      setIssues((prev) =>
        prev.map((issue) =>
          issue.id === id ? { ...issue, status: 'open' as const, closed_at: null } : issue
        )
      );
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reopen issue');
      return false;
    }
  }, []);

  const addDependency = useCallback(
    async (issueId: string, dependsOnId: string, type: string): Promise<boolean> => {
      try {
        const response = await fetch(`${API_BASE}/issues/${issueId}/dependencies`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ depends_on_id: dependsOnId, type }),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        await refresh();
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to add dependency');
        return false;
      }
    },
    [refresh]
  );

  useEffect(() => {
    fetchIssues();
  }, [fetchIssues]);

  return {
    issues,
    loading,
    error,
    refresh,
    createIssue,
    updateIssue,
    closeIssue,
    reopenIssue,
    addDependency,
  };
}
