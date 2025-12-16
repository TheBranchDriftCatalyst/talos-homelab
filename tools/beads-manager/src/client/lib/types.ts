// Beads issue types - matches the bd data model

export type IssueStatus = 'open' | 'in_progress' | 'blocked' | 'closed';
export type IssueType = 'bug' | 'feature' | 'task' | 'epic' | 'chore';
export type DependencyType = 'blocks' | 'parent-child' | 'related' | 'discovered-from';

export interface Dependency {
  issue_id: string;
  depends_on_id: string;
  type: DependencyType;
  created_at: string;
  created_by?: string;
}

export interface Issue {
  id: string;
  title: string;
  description: string | null;
  design: string | null;
  acceptance_criteria: string | null;
  notes: string | null;
  external_ref: string | null;
  status: IssueStatus;
  priority: number; // 0=highest, 4=lowest
  issue_type: IssueType;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  assignee: string | null;
  labels: string[];
  dependencies: Dependency[];
}

// Graph types for ForceGraph integration
export interface GraphNode {
  id: string;
  kind: IssueType;
  name: string;
  attributes: {
    status: IssueStatus;
    priority: number;
    assignee: string | null;
    labels: string[];
    description: string | null;
  };
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

export interface GraphEdge {
  id: string;
  src: string;
  dst: string;
  kind: DependencyType;
  source: GraphNode;
  target: GraphNode;
}

export interface GraphData {
  nodes: Record<string, GraphNode>;
  edges: GraphEdge[];
}

// API response types
export interface ApiResponse<T> {
  data?: T;
  error?: string;
}

export interface WebSocketMessage {
  type: 'refresh' | 'issues' | 'issue' | 'updated' | 'error';
  data?: Issue[] | Issue;
  id?: string;
  message?: string;
}

// Filter state
export interface FilterState {
  status: IssueStatus[];
  type: IssueType[];
  priority: number[];
  assignee?: string;
  search?: string;
}

// Priority helpers
export const PRIORITY_LABELS: Record<number, string> = {
  0: 'Highest',
  1: 'Urgent',
  2: 'High',
  3: 'Normal',
  4: 'Low',
};

export const STATUS_LABELS: Record<IssueStatus, string> = {
  open: 'Open',
  in_progress: 'In Progress',
  blocked: 'Blocked',
  closed: 'Closed',
};

export const TYPE_LABELS: Record<IssueType, string> = {
  bug: 'Bug',
  feature: 'Feature',
  task: 'Task',
  epic: 'Epic',
  chore: 'Chore',
};
