import { useMemo, useCallback, useRef, useEffect, useState } from 'react';
import type { Issue } from '../../lib/types';
import { issuesToGraphData } from '../../lib/transformers';

interface DependencyGraphProps {
  issues: Issue[];
  onNodeClick: (issueId: string) => void;
  selectedIssueId?: string;
}

// Status colors
const STATUS_COLORS: Record<string, string> = {
  open: '#3b82f6',      // blue
  in_progress: '#eab308', // yellow
  blocked: '#ef4444',    // red
  closed: '#22c55e',     // green
};

// Type shapes (used in node rendering logic below)

// Edge colors by dependency type
const EDGE_COLORS: Record<string, string> = {
  blocks: '#ef4444',        // red
  'parent-child': '#8b5cf6', // purple
  related: '#6b7280',        // gray
  'discovered-from': '#f59e0b', // amber
};

export function DependencyGraph({
  issues,
  onNodeClick,
  selectedIssueId,
}: DependencyGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [dragging, setDragging] = useState<string | null>(null);
  const [nodePositions, setNodePositions] = useState<Record<string, { x: number; y: number }>>({});

  // Convert issues to graph data
  const graphData = useMemo(() => issuesToGraphData(issues), [issues]);

  // Initialize node positions using force-directed layout simulation
  useEffect(() => {
    const nodes = Object.values(graphData.nodes);
    if (nodes.length === 0) return;

    // Simple force-directed layout
    const positions: Record<string, { x: number; y: number }> = {};
    const centerX = dimensions.width / 2;
    const centerY = dimensions.height / 2;

    // Initialize positions in a circle
    nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / nodes.length;
      const radius = Math.min(dimensions.width, dimensions.height) * 0.3;
      positions[node.id] = {
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
      };
    });

    // Simple force simulation (10 iterations)
    for (let iter = 0; iter < 50; iter++) {
      // Repulsion between nodes
      nodes.forEach((nodeA) => {
        nodes.forEach((nodeB) => {
          if (nodeA.id === nodeB.id) return;

          const posA = positions[nodeA.id];
          const posB = positions[nodeB.id];
          const dx = posA.x - posB.x;
          const dy = posA.y - posB.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = 5000 / (dist * dist);

          posA.x += (dx / dist) * force;
          posA.y += (dy / dist) * force;
        });
      });

      // Attraction along edges
      graphData.edges.forEach((edge) => {
        const posA = positions[edge.src];
        const posB = positions[edge.dst];
        if (!posA || !posB) return;

        const dx = posB.x - posA.x;
        const dy = posB.y - posA.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = dist * 0.01;

        posA.x += (dx / dist) * force;
        posA.y += (dy / dist) * force;
        posB.x -= (dx / dist) * force;
        posB.y -= (dy / dist) * force;
      });

      // Center gravity
      nodes.forEach((node) => {
        const pos = positions[node.id];
        pos.x += (centerX - pos.x) * 0.01;
        pos.y += (centerY - pos.y) * 0.01;
      });
    }

    setNodePositions(positions);
  }, [graphData, dimensions]);

  // Handle resize
  useEffect(() => {
    const updateDimensions = () => {
      if (svgRef.current?.parentElement) {
        const { width, height } = svgRef.current.parentElement.getBoundingClientRect();
        setDimensions({ width, height });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

  // Handle zoom
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const scaleDelta = e.deltaY > 0 ? 0.9 : 1.1;
    setTransform((prev) => ({
      ...prev,
      scale: Math.min(Math.max(prev.scale * scaleDelta, 0.1), 5),
    }));
  }, []);

  // Handle pan
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.target === svgRef.current) {
      setDragging('pan');
    }
  }, []);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (dragging === 'pan') {
        setTransform((prev) => ({
          ...prev,
          x: prev.x + e.movementX,
          y: prev.y + e.movementY,
        }));
      } else if (dragging) {
        setNodePositions((prev) => ({
          ...prev,
          [dragging]: {
            x: (prev[dragging]?.x || 0) + e.movementX / transform.scale,
            y: (prev[dragging]?.y || 0) + e.movementY / transform.scale,
          },
        }));
      }
    },
    [dragging, transform.scale]
  );

  const handleMouseUp = useCallback(() => {
    setDragging(null);
  }, []);

  // Render node shape
  const renderNode = (nodeId: string) => {
    const node = graphData.nodes[nodeId];
    const pos = nodePositions[nodeId];
    if (!node || !pos) return null;

    const isSelected = selectedIssueId === nodeId;
    const color = STATUS_COLORS[node.attributes.status] || '#6b7280';
    const size = node.kind === 'epic' ? 24 : 16;

    return (
      <g
        key={nodeId}
        transform={`translate(${pos.x}, ${pos.y})`}
        onClick={() => onNodeClick(nodeId)}
        onMouseDown={(e) => {
          e.stopPropagation();
          setDragging(nodeId);
        }}
        style={{ cursor: 'pointer' }}
      >
        {/* Shape based on type */}
        {node.kind === 'task' ? (
          <circle
            r={size}
            fill={color}
            stroke={isSelected ? '#ffffff' : 'transparent'}
            strokeWidth={isSelected ? 3 : 0}
          />
        ) : node.kind === 'bug' ? (
          <polygon
            points={`0,${-size} ${size},0 0,${size} ${-size},0`}
            fill={color}
            stroke={isSelected ? '#ffffff' : 'transparent'}
            strokeWidth={isSelected ? 3 : 0}
          />
        ) : node.kind === 'epic' ? (
          <polygon
            points={`${-size},0 ${-size / 2},${-size * 0.866} ${size / 2},${-size * 0.866} ${size},0 ${size / 2},${size * 0.866} ${-size / 2},${size * 0.866}`}
            fill={color}
            stroke={isSelected ? '#ffffff' : 'transparent'}
            strokeWidth={isSelected ? 3 : 0}
          />
        ) : (
          <rect
            x={-size}
            y={-size}
            width={size * 2}
            height={size * 2}
            rx={node.kind === 'feature' ? 4 : 0}
            fill={color}
            stroke={isSelected ? '#ffffff' : 'transparent'}
            strokeWidth={isSelected ? 3 : 0}
          />
        )}

        {/* Label */}
        <text
          y={size + 14}
          textAnchor="middle"
          fontSize="10"
          fill="#94a3b8"
          className="pointer-events-none select-none"
        >
          {node.id}
        </text>
      </g>
    );
  };

  // Render edge
  const renderEdge = (edge: typeof graphData.edges[0], index: number) => {
    const srcPos = nodePositions[edge.src];
    const dstPos = nodePositions[edge.dst];
    if (!srcPos || !dstPos) return null;

    const color = EDGE_COLORS[edge.kind] || '#6b7280';

    return (
      <g key={`edge-${index}`}>
        <line
          x1={srcPos.x}
          y1={srcPos.y}
          x2={dstPos.x}
          y2={dstPos.y}
          stroke={color}
          strokeWidth={2}
          strokeOpacity={0.6}
          markerEnd="url(#arrowhead)"
        />
      </g>
    );
  };

  return (
    <div className="w-full h-full bg-slate-900 overflow-hidden">
      {/* Legend */}
      <div className="absolute top-4 left-4 bg-slate-800 rounded-lg p-3 shadow-lg z-10 text-xs">
        <div className="font-medium text-slate-300 mb-2">Status</div>
        <div className="space-y-1">
          {Object.entries(STATUS_COLORS).map(([status, color]) => (
            <div key={status} className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-slate-400 capitalize">{status.replace('_', ' ')}</span>
            </div>
          ))}
        </div>
        <div className="font-medium text-slate-300 mt-3 mb-2">Dependencies</div>
        <div className="space-y-1">
          {Object.entries(EDGE_COLORS).map(([type, color]) => (
            <div key={type} className="flex items-center gap-2">
              <span className="w-4 h-0.5" style={{ backgroundColor: color }} />
              <span className="text-slate-400 capitalize">{type.replace('-', ' ')}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Controls */}
      <div className="absolute top-4 right-4 bg-slate-800 rounded-lg p-2 shadow-lg z-10 flex gap-2">
        <button
          onClick={() => setTransform((prev) => ({ ...prev, scale: prev.scale * 1.2 }))}
          className="p-2 text-slate-300 hover:bg-slate-700 rounded"
          title="Zoom In"
        >
          +
        </button>
        <button
          onClick={() => setTransform((prev) => ({ ...prev, scale: prev.scale * 0.8 }))}
          className="p-2 text-slate-300 hover:bg-slate-700 rounded"
          title="Zoom Out"
        >
          -
        </button>
        <button
          onClick={() => setTransform({ x: 0, y: 0, scale: 1 })}
          className="p-2 text-slate-300 hover:bg-slate-700 rounded"
          title="Reset View"
        >
          Reset
        </button>
      </div>

      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{ cursor: dragging === 'pan' ? 'grabbing' : 'grab' }}
      >
        <defs>
          <marker
            id="arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#6b7280" />
          </marker>
        </defs>

        <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.scale})`}>
          {/* Edges */}
          {graphData.edges.map(renderEdge)}

          {/* Nodes */}
          {Object.keys(graphData.nodes).map(renderNode)}
        </g>
      </svg>

      {/* Stats */}
      <div className="absolute bottom-4 left-4 bg-slate-800 rounded-lg px-3 py-2 shadow-lg z-10 text-xs text-slate-400">
        {Object.keys(graphData.nodes).length} nodes, {graphData.edges.length} edges
      </div>
    </div>
  );
}
