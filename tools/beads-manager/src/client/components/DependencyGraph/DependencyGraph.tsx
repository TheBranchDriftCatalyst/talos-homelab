import { useMemo, useCallback, useState } from 'react';
import {
  ReactFlow,
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  ConnectionMode,
  MarkerType,
  NodeProps,
  Handle,
  Position,
} from '@xyflow/react';
import dagre from 'dagre';
import type { Issue } from '../../lib/types';
import '@xyflow/react/dist/style.css';

interface DependencyGraphProps {
  issues: Issue[];
  onNodeClick: (issueId: string) => void;
  selectedIssueId?: string;
  onCreateDependency?: (fromId: string, toId: string) => void;
}

// Status colors
const STATUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  open: { bg: '#1e3a5f', border: '#3b82f6', text: '#93c5fd' },
  in_progress: { bg: '#422006', border: '#eab308', text: '#fde047' },
  blocked: { bg: '#450a0a', border: '#ef4444', text: '#fca5a5' },
  closed: { bg: '#14532d', border: '#22c55e', text: '#86efac' },
};

// Type icons/badges
const TYPE_BADGES: Record<string, { icon: string; color: string }> = {
  bug: { icon: '🐛', color: '#ef4444' },
  feature: { icon: '✨', color: '#8b5cf6' },
  task: { icon: '📋', color: '#3b82f6' },
  epic: { icon: '🎯', color: '#f59e0b' },
  chore: { icon: '🔧', color: '#6b7280' },
};

// Priority indicators
const PRIORITY_COLORS: Record<number, string> = {
  0: '#6b7280', // none
  1: '#ef4444', // urgent
  2: '#f59e0b', // high
  3: '#3b82f6', // normal
  4: '#22c55e', // low
};

// Edge colors by dependency type
const EDGE_STYLES: Record<string, { stroke: string; strokeDasharray?: string; animated?: boolean }> = {
  blocks: { stroke: '#ef4444', animated: true },
  'parent-child': { stroke: '#8b5cf6', strokeDasharray: '5,5' },
  related: { stroke: '#6b7280', strokeDasharray: '2,2' },
  'discovered-from': { stroke: '#f59e0b' },
};

// Node data type
type IssueNodeData = {
  id: string;
  title: string;
  status: string;
  priority: number;
  issue_type: string;
  assignee?: string;
  childCount: number;
  isCollapsed: boolean;
  onToggleCollapse?: () => void;
  [key: string]: unknown;
};

// Epic group node data type
type EpicGroupData = {
  label: string;
  epicId: string;
  childCount: number;
  status: string;
  [key: string]: unknown;
};

// Epic group colors
const EPIC_GROUP_COLORS = [
  { bg: 'rgba(139, 92, 246, 0.15)', border: '#8b5cf6' },  // purple
  { bg: 'rgba(59, 130, 246, 0.15)', border: '#3b82f6' },  // blue
  { bg: 'rgba(16, 185, 129, 0.15)', border: '#10b981' },  // emerald
  { bg: 'rgba(245, 158, 11, 0.15)', border: '#f59e0b' },  // amber
  { bg: 'rgba(236, 72, 153, 0.15)', border: '#ec4899' },  // pink
  { bg: 'rgba(99, 102, 241, 0.15)', border: '#6366f1' },  // indigo
];

// Custom Epic Group Node Component (container for children)
function EpicGroupNode({ data }: NodeProps<Node<EpicGroupData>>) {
  const colorIndex = Math.abs(data.epicId.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0)) % EPIC_GROUP_COLORS.length;
  const colors = EPIC_GROUP_COLORS[colorIndex];
  const status = STATUS_COLORS[data.status] || STATUS_COLORS.open;

  return (
    <div
      className="rounded-xl min-w-[300px] min-h-[200px]"
      style={{
        backgroundColor: colors.bg,
        borderWidth: 2,
        borderStyle: 'dashed',
        borderColor: colors.border,
        padding: '40px 20px 20px 20px',
      }}
    >
      {/* Epic header */}
      <div
        className="absolute top-2 left-3 right-3 flex items-center justify-between"
        style={{ color: colors.border }}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">🎯</span>
          <span className="font-semibold text-sm">{data.label}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] px-1.5 py-0.5 rounded capitalize"
            style={{
              backgroundColor: `${status.border}33`,
              color: status.text,
            }}
          >
            {data.status.replace('_', ' ')}
          </span>
          <span className="text-xs opacity-70">
            {data.childCount} {data.childCount === 1 ? 'issue' : 'issues'}
          </span>
        </div>
      </div>
    </div>
  );
}

// Custom Issue Node Component
function IssueNode({ data, selected }: NodeProps<Node<IssueNodeData>>) {
  const status = STATUS_COLORS[data.status] || STATUS_COLORS.open;
  const typeBadge = TYPE_BADGES[data.issue_type] || TYPE_BADGES.task;
  const priorityColor = PRIORITY_COLORS[data.priority] || PRIORITY_COLORS[3];

  const handleCollapseClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    data.onToggleCollapse?.();
  };

  return (
    <div
      className={`
        relative px-3 py-2 rounded-lg shadow-lg min-w-[180px] max-w-[240px]
        transition-all duration-200 cursor-pointer
        ${selected ? 'ring-2 ring-white ring-offset-2 ring-offset-slate-900' : ''}
      `}
      style={{
        backgroundColor: status.bg,
        borderWidth: 2,
        borderStyle: 'solid',
        borderColor: status.border,
      }}
    >
      {/* Input handle (top) - for incoming dependencies */}
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-slate-500 !border-slate-400 !w-3 !h-3"
      />

      {/* Header with type badge and priority */}
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono text-slate-400">{data.id}</span>
        <div className="flex items-center gap-1">
          {/* Collapse/Expand button */}
          {data.childCount > 0 && (
            <button
              onClick={handleCollapseClick}
              className="flex items-center justify-center w-5 h-5 rounded bg-slate-700/80 hover:bg-slate-600 text-slate-300 text-[10px] font-bold transition-colors"
              title={data.isCollapsed ? `Expand ${data.childCount} children` : `Collapse ${data.childCount} children`}
            >
              {data.isCollapsed ? `+${data.childCount}` : '−'}
            </button>
          )}
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: priorityColor }}
            title={`Priority: ${data.priority}`}
          />
          <span title={data.issue_type}>{typeBadge.icon}</span>
        </div>
      </div>

      {/* Title */}
      <div
        className="text-sm font-medium truncate"
        style={{ color: status.text }}
        title={data.title}
      >
        {data.title}
      </div>

      {/* Status badge and collapsed indicator */}
      <div className="mt-1 flex items-center gap-2">
        <span
          className="text-[10px] px-1.5 py-0.5 rounded capitalize"
          style={{
            backgroundColor: `${status.border}33`,
            color: status.text,
          }}
        >
          {data.status.replace('_', ' ')}
        </span>
        {data.isCollapsed && data.childCount > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/30 text-purple-300">
            📁 {data.childCount} hidden
          </span>
        )}
        {data.assignee && !data.isCollapsed && (
          <span className="text-[10px] text-slate-400 truncate">
            @{data.assignee}
          </span>
        )}
      </div>

      {/* Output handle (bottom) - for outgoing dependencies */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-slate-500 !border-slate-400 !w-3 !h-3"
      />
    </div>
  );
}

// Node types registry
const nodeTypes = {
  issue: IssueNode,
  epicGroup: EpicGroupNode,
};

// Dagre layout helper
function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  direction: 'TB' | 'LR' = 'TB'
) {
  if (nodes.length === 0) {
    return { nodes: [], edges: [] };
  }

  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({ rankdir: direction, nodesep: 50, ranksep: 80 });

  // Add nodes to dagre
  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: 200, height: 80 });
  });

  // Add edges to dagre
  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  // Calculate layout
  dagre.layout(dagreGraph);

  // Apply positions to nodes
  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      ...node,
      position: {
        x: nodeWithPosition.x - 100, // center node
        y: nodeWithPosition.y - 40,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}

// Build dependency graph structure
function buildDependencyTree(issues: Issue[]) {
  const childrenMap = new Map<string, Set<string>>();
  const parentMap = new Map<string, string>();

  issues.forEach((issue) => {
    issue.dependencies?.forEach((dep) => {
      // For "blocks" type: the depends_on_id blocks this issue
      // So depends_on_id is the "parent" and issue.id is the "child"
      if (dep.type === 'blocks' || dep.type === 'parent-child') {
        const parentId = dep.depends_on_id;
        if (!childrenMap.has(parentId)) {
          childrenMap.set(parentId, new Set());
        }
        childrenMap.get(parentId)!.add(issue.id);
        parentMap.set(issue.id, parentId);
      }
    });
  });

  return { childrenMap, parentMap };
}

// Get all descendants of a node (recursively)
function getDescendants(nodeId: string, childrenMap: Map<string, Set<string>>): Set<string> {
  const descendants = new Set<string>();
  const children = childrenMap.get(nodeId);

  if (children) {
    children.forEach((childId) => {
      descendants.add(childId);
      getDescendants(childId, childrenMap).forEach((d) => descendants.add(d));
    });
  }

  return descendants;
}

// Get Epic parent for an issue (via parent-child dependency)
function getEpicParent(issue: Issue, issues: Issue[]): Issue | null {
  const parentChildDep = issue.dependencies?.find((dep) => dep.type === 'parent-child');
  if (!parentChildDep) return null;

  const parent = issues.find((i) => i.id === parentChildDep.depends_on_id);
  if (parent?.issue_type === 'epic') return parent;

  // Check if parent has an epic ancestor
  if (parent) return getEpicParent(parent, issues);
  return null;
}

// Transform issues to React Flow format
function issuesToReactFlow(
  issues: Issue[],
  selectedIssueId: string | undefined,
  collapsedNodes: Set<string>,
  onToggleCollapse: (nodeId: string) => void,
  groupByEpic: boolean = false
) {
  const { childrenMap } = buildDependencyTree(issues);
  const issueIds = new Set(issues.map((i) => i.id));

  // Calculate which nodes should be hidden (descendants of collapsed nodes)
  const hiddenNodes = new Set<string>();
  collapsedNodes.forEach((collapsedId) => {
    getDescendants(collapsedId, childrenMap).forEach((descendant) => {
      hiddenNodes.add(descendant);
    });
  });

  // Filter out hidden nodes
  const visibleIssues = issues.filter((issue) => !hiddenNodes.has(issue.id));

  const nodes: Node[] = [];
  const epicGroups = new Map<string, { epic: Issue; children: Issue[] }>();

  // If grouping by epic, identify epics and their children
  if (groupByEpic) {
    visibleIssues.forEach((issue) => {
      if (issue.issue_type === 'epic') {
        if (!epicGroups.has(issue.id)) {
          epicGroups.set(issue.id, { epic: issue, children: [] });
        }
      } else {
        const epicParent = getEpicParent(issue, issues);
        if (epicParent && visibleIssues.some((i) => i.id === epicParent.id)) {
          if (!epicGroups.has(epicParent.id)) {
            epicGroups.set(epicParent.id, { epic: epicParent, children: [] });
          }
          epicGroups.get(epicParent.id)!.children.push(issue);
        }
      }
    });

    // Create Epic group nodes
    epicGroups.forEach(({ epic, children }, epicId) => {
      nodes.push({
        id: `epic-group-${epicId}`,
        type: 'epicGroup',
        position: { x: 0, y: 0 },
        data: {
          label: epic.title,
          epicId: epicId,
          childCount: children.length,
          status: epic.status,
        },
        style: {
          width: Math.max(350, children.length * 120),
          height: Math.max(250, Math.ceil(children.length / 2) * 120),
        },
      });
    });
  }

  // Create issue nodes
  visibleIssues.forEach((issue) => {
    const childCount = childrenMap.get(issue.id)?.size || 0;
    const isCollapsed = collapsedNodes.has(issue.id);

    // Determine if this issue belongs to an epic group
    let parentId: string | undefined;
    if (groupByEpic && issue.issue_type !== 'epic') {
      const epicParent = getEpicParent(issue, issues);
      if (epicParent && epicGroups.has(epicParent.id)) {
        parentId = `epic-group-${epicParent.id}`;
      }
    }

    // Skip epic issues when grouping (they become group headers)
    if (groupByEpic && issue.issue_type === 'epic') {
      return;
    }

    nodes.push({
      id: issue.id,
      type: 'issue',
      position: { x: 0, y: 0 }, // Will be set by dagre
      parentId,
      extent: parentId ? 'parent' as const : undefined,
      data: {
        id: issue.id,
        title: issue.title,
        status: issue.status,
        priority: issue.priority,
        issue_type: issue.issue_type,
        assignee: issue.assignee,
        childCount,
        isCollapsed,
        onToggleCollapse: () => onToggleCollapse(issue.id),
      },
      selected: issue.id === selectedIssueId,
    });
  });

  const visibleIds = new Set(visibleIssues.map((i) => i.id));
  const edges: Edge[] = [];

  visibleIssues.forEach((issue) => {
    issue.dependencies?.forEach((dep) => {
      // Skip parent-child edges when grouping by epic (visual grouping replaces them)
      if (groupByEpic && dep.type === 'parent-child') {
        const parent = issues.find((i) => i.id === dep.depends_on_id);
        if (parent?.issue_type === 'epic') return;
      }

      // Only add edge if both nodes exist and are visible
      if (issueIds.has(dep.depends_on_id) && visibleIds.has(dep.depends_on_id)) {
        // Skip edges to/from epics when grouping
        if (groupByEpic) {
          const sourceIssue = issues.find((i) => i.id === dep.depends_on_id);
          if (sourceIssue?.issue_type === 'epic') return;
        }

        const edgeStyle = EDGE_STYLES[dep.type] || EDGE_STYLES.blocks;
        edges.push({
          id: `${issue.id}-${dep.depends_on_id}`,
          source: dep.depends_on_id, // dependency points FROM blocker TO blocked
          target: issue.id,
          type: 'smoothstep',
          animated: edgeStyle.animated,
          style: {
            stroke: edgeStyle.stroke,
            strokeWidth: 2,
            strokeDasharray: edgeStyle.strokeDasharray,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: edgeStyle.stroke,
          },
          data: { type: dep.type },
        });
      }
    });
  });

  return getLayoutedElements(nodes, edges);
}

export function DependencyGraph({
  issues,
  onNodeClick,
  selectedIssueId,
  onCreateDependency,
}: DependencyGraphProps) {
  // Track collapsed nodes
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set());
  // Track group by epic mode
  const [groupByEpic, setGroupByEpic] = useState(false);

  const toggleCollapse = useCallback((nodeId: string) => {
    setCollapsedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  // Check if there are any epics to group by
  const hasEpics = useMemo(() => issues.some((i) => i.issue_type === 'epic'), [issues]);

  // Transform issues to React Flow format
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => issuesToReactFlow(issues, selectedIssueId, collapsedNodes, toggleCollapse, groupByEpic),
    [issues, selectedIssueId, collapsedNodes, toggleCollapse, groupByEpic]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes when issues or collapsed state changes
  useMemo(() => {
    const { nodes: newNodes, edges: newEdges } = issuesToReactFlow(
      issues,
      selectedIssueId,
      collapsedNodes,
      toggleCollapse,
      groupByEpic
    );
    setNodes(newNodes);
    setEdges(newEdges);
  }, [issues, selectedIssueId, collapsedNodes, toggleCollapse, groupByEpic, setNodes, setEdges]);

  // Handle node click
  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      onNodeClick(node.id);
    },
    [onNodeClick]
  );

  // Handle new connection (create dependency)
  const handleConnect = useCallback(
    (params: { source: string | null; target: string | null }) => {
      if (params.source && params.target && onCreateDependency) {
        onCreateDependency(params.target, params.source); // target depends on source
      }
    },
    [onCreateDependency]
  );

  // Mini-map node color
  const nodeColor = useCallback((node: Node) => {
    const status = node.data?.status as string;
    return STATUS_COLORS[status]?.border || '#6b7280';
  }, []);

  // Collapse/Expand all
  const collapseAll = useCallback(() => {
    const { childrenMap } = buildDependencyTree(issues);
    const nodesWithChildren = new Set<string>();
    childrenMap.forEach((children, parentId) => {
      if (children.size > 0) {
        nodesWithChildren.add(parentId);
      }
    });
    setCollapsedNodes(nodesWithChildren);
  }, [issues]);

  const expandAll = useCallback(() => {
    setCollapsedNodes(new Set());
  }, []);

  return (
    <div className="w-full h-full bg-slate-900">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onConnect={handleConnect}
        nodeTypes={nodeTypes}
        connectionMode={ConnectionMode.Loose}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={2}
        defaultEdgeOptions={{
          type: 'smoothstep',
        }}
      >
        <Background color="#334155" gap={20} />
        <Controls className="!bg-slate-800 !border-slate-700 !rounded-lg [&>button]:!bg-slate-700 [&>button]:!border-slate-600 [&>button]:!text-slate-300 [&>button:hover]:!bg-slate-600" />
        <MiniMap
          nodeColor={nodeColor}
          maskColor="rgba(15, 23, 42, 0.8)"
          className="!bg-slate-800 !border-slate-700 !rounded-lg"
        />
      </ReactFlow>

      {/* Legend */}
      <div className="absolute top-4 left-4 bg-slate-800/95 backdrop-blur rounded-lg p-3 shadow-lg z-10 text-xs border border-slate-700">
        <div className="font-medium text-slate-300 mb-2">Status</div>
        <div className="space-y-1 mb-3">
          {Object.entries(STATUS_COLORS).map(([status, colors]) => (
            <div key={status} className="flex items-center gap-2">
              <span
                className="w-3 h-3 rounded"
                style={{ backgroundColor: colors.border }}
              />
              <span className="text-slate-400 capitalize">{status.replace('_', ' ')}</span>
            </div>
          ))}
        </div>
        <div className="font-medium text-slate-300 mb-2">Dependencies</div>
        <div className="space-y-1">
          {Object.entries(EDGE_STYLES).map(([type, style]) => (
            <div key={type} className="flex items-center gap-2">
              <span
                className="w-4 h-0.5"
                style={{
                  backgroundColor: style.stroke,
                  ...(style.strokeDasharray && {
                    background: `repeating-linear-gradient(90deg, ${style.stroke} 0, ${style.stroke} 2px, transparent 2px, transparent 4px)`,
                  }),
                }}
              />
              <span className="text-slate-400 capitalize">{type.replace('-', ' ')}</span>
            </div>
          ))}
        </div>

        {/* Group by Epic toggle */}
        {hasEpics && (
          <div className="mt-3 pt-2 border-t border-slate-700">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={groupByEpic}
                onChange={(e) => setGroupByEpic(e.target.checked)}
                className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-indigo-500 focus:ring-indigo-500 focus:ring-offset-slate-800"
              />
              <span className="text-slate-300">Group by Epic</span>
              <span className="text-lg">🎯</span>
            </label>
          </div>
        )}

        {/* Collapse/Expand controls */}
        <div className="mt-3 pt-2 border-t border-slate-700 flex gap-2">
          <button
            onClick={collapseAll}
            className="flex-1 px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded text-slate-300 transition-colors"
          >
            📁 Collapse
          </button>
          <button
            onClick={expandAll}
            className="flex-1 px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded text-slate-300 transition-colors"
          >
            📂 Expand
          </button>
        </div>

        <div className="mt-2 text-slate-500">
          Click +N on nodes to toggle
        </div>
      </div>

      {/* Stats */}
      <div className="absolute bottom-4 left-4 bg-slate-800/95 backdrop-blur rounded-lg px-3 py-2 shadow-lg z-10 text-xs text-slate-400 border border-slate-700">
        {nodes.length} visible, {issues.length - nodes.length} collapsed, {edges.length} edges
      </div>
    </div>
  );
}
