import { useMemo, useCallback } from 'react';
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
  [key: string]: unknown;
};

// Custom Issue Node Component
function IssueNode({ data, selected }: NodeProps<Node<IssueNodeData>>) {
  const status = STATUS_COLORS[data.status] || STATUS_COLORS.open;
  const typeBadge = TYPE_BADGES[data.issue_type] || TYPE_BADGES.task;
  const priorityColor = PRIORITY_COLORS[data.priority] || PRIORITY_COLORS[3];

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

      {/* Status badge */}
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
        {data.assignee && (
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
};

// Dagre layout helper
function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  direction: 'TB' | 'LR' = 'TB'
) {
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

// Transform issues to React Flow format
function issuesToReactFlow(issues: Issue[], selectedIssueId?: string) {
  const nodes: Node[] = issues.map((issue) => ({
    id: issue.id,
    type: 'issue',
    position: { x: 0, y: 0 }, // Will be set by dagre
    data: {
      id: issue.id,
      title: issue.title,
      status: issue.status,
      priority: issue.priority,
      issue_type: issue.issue_type,
      assignee: issue.assignee,
    },
    selected: issue.id === selectedIssueId,
  }));

  const edges: Edge[] = [];
  const issueIds = new Set(issues.map((i) => i.id));

  issues.forEach((issue) => {
    issue.dependencies?.forEach((dep) => {
      // Only add edge if both nodes exist in filtered set
      if (issueIds.has(dep.depends_on_id)) {
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
  // Transform issues to React Flow format
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => issuesToReactFlow(issues, selectedIssueId),
    [issues, selectedIssueId]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes when issues change
  useMemo(() => {
    const { nodes: newNodes, edges: newEdges } = issuesToReactFlow(issues, selectedIssueId);
    setNodes(newNodes);
    setEdges(newEdges);
  }, [issues, selectedIssueId, setNodes, setEdges]);

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
        <div className="mt-3 pt-2 border-t border-slate-700 text-slate-500">
          Drag between handles to create dependencies
        </div>
      </div>

      {/* Stats */}
      <div className="absolute bottom-4 left-4 bg-slate-800/95 backdrop-blur rounded-lg px-3 py-2 shadow-lg z-10 text-xs text-slate-400 border border-slate-700">
        {nodes.length} issues, {edges.length} dependencies
      </div>
    </div>
  );
}
