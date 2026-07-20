import dagre from 'dagre';
import { useCallback } from 'react';
import type { FlowNode, FlowEdge } from './types';

const NODE_WIDTH = 280;
const NODE_HEIGHT = 140;
const GRID_COLS = 4;
const GRID_GAP_X = 320;
const GRID_GAP_Y = 200;

/**
 * Applies a dagre hierarchical layout to the given nodes and edges.
 * Falls back to a simple grid layout if dagre produces invalid positions.
 */
export function applyLayout(
  nodes: FlowNode[],
  edges: FlowEdge[],
  direction: 'TB' | 'LR' = 'TB'
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  if (nodes.length === 0) return { nodes: [], edges };

  try {
    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({
      rankdir: direction,
      nodesep: 80,
      ranksep: 120,
      edgesep: 40,
      marginx: 40,
      marginy: 40,
    });

    for (const node of nodes) {
      g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
    }

    for (const edge of edges) {
      if (g.hasNode(edge.source) && g.hasNode(edge.target)) {
        g.setEdge(edge.source, edge.target);
      }
    }

    dagre.layout(g);

    const laid = nodes.map((node) => {
      const pos = g.node(node.id);
      const x = pos?.x ?? NaN;
      const y = pos?.y ?? NaN;
      if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('invalid');
      return { ...node, position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 } };
    });

    // Check for duplicate positions
    const seen = new Set<string>();
    for (const n of laid) {
      const key = `${n.position.x},${n.position.y}`;
      if (seen.has(key)) throw new Error('duplicate');
      seen.add(key);
    }

    return { nodes: laid, edges };
  } catch {
    // Grid fallback
    return { nodes: gridFallback(nodes), edges };
  }
}

/** Simple grid layout as a fallback when dagre fails */
function gridFallback(nodes: FlowNode[]): FlowNode[] {
  return nodes.map((node, i) => ({
    ...node,
    position: {
      x: (i % GRID_COLS) * GRID_GAP_X + 40,
      y: Math.floor(i / GRID_COLS) * GRID_GAP_Y + 40,
    },
  }));
}

/**
 * React hook that exposes the applyLayout function.
 * Memoised so it can be passed as a stable reference.
 */
export function useAutoLayout() {
  const layout = useCallback(
    (nodes: FlowNode[], edges: FlowEdge[], direction: 'TB' | 'LR' = 'TB') =>
      applyLayout(nodes, edges, direction),
    []
  );

  return { applyLayout: layout };
}
