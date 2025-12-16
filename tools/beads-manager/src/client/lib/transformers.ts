import type { Issue, GraphData, GraphNode, GraphEdge } from './types';

/**
 * Transform beads issues into ForceGraph data format
 */
export function issuesToGraphData(issues: Issue[]): GraphData {
  // Create nodes from issues
  const nodes: Record<string, GraphNode> = {};

  for (const issue of issues) {
    nodes[issue.id] = {
      id: issue.id,
      kind: issue.issue_type,
      name: issue.title,
      attributes: {
        status: issue.status,
        priority: issue.priority,
        assignee: issue.assignee,
        labels: issue.labels,
        description: issue.description,
      },
    };
  }

  // Create edges from dependencies
  const edges: GraphEdge[] = [];
  const issueIds = new Set(issues.map(i => i.id));

  for (const issue of issues) {
    for (const dep of issue.dependencies || []) {
      // Only create edge if both nodes exist
      if (issueIds.has(dep.depends_on_id)) {
        const sourceNode = nodes[dep.issue_id];
        const targetNode = nodes[dep.depends_on_id];

        if (sourceNode && targetNode) {
          edges.push({
            id: `${dep.issue_id}-${dep.depends_on_id}`,
            src: dep.issue_id,
            dst: dep.depends_on_id,
            kind: dep.type,
            source: sourceNode,
            target: targetNode,
          });
        }
      }
    }
  }

  return { nodes, edges };
}

/**
 * Get status color class
 */
export function getStatusColor(status: string): string {
  switch (status) {
    case 'open': return 'bg-status-open';
    case 'in_progress': return 'bg-status-progress';
    case 'blocked': return 'bg-status-blocked';
    case 'closed': return 'bg-status-closed';
    default: return 'bg-slate-500';
  }
}

/**
 * Get status text color class
 */
export function getStatusTextColor(status: string): string {
  switch (status) {
    case 'open': return 'text-status-open';
    case 'in_progress': return 'text-status-progress';
    case 'blocked': return 'text-status-blocked';
    case 'closed': return 'text-status-closed';
    default: return 'text-slate-500';
  }
}

/**
 * Get type color class
 */
export function getTypeColor(type: string): string {
  switch (type) {
    case 'epic': return 'bg-type-epic';
    case 'feature': return 'bg-type-feature';
    case 'task': return 'bg-type-task';
    case 'bug': return 'bg-type-bug';
    case 'chore': return 'bg-type-chore';
    default: return 'bg-slate-500';
  }
}

/**
 * Get priority color class
 */
export function getPriorityColor(priority: number): string {
  switch (priority) {
    case 0:
    case 1: return 'text-priority-urgent';
    case 2: return 'text-priority-high';
    case 3: return 'text-priority-normal';
    case 4: return 'text-priority-low';
    default: return 'text-slate-500';
  }
}

/**
 * Format date for display
 */
export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Get relative time string
 */
export function getRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(dateString);
}
