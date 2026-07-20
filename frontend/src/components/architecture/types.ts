import type { Node, Edge } from 'reactflow';

/** Classification of a node that determines its visual style */
export type NodeType =
  | 'person'
  | 'system'
  | 'external_system'
  | 'container'
  | 'component'
  | 'database';

/** Data payload carried by each architecture node */
export interface ArchitectureNodeData {
  label: string;
  description: string;
  technology: string;
  nodeType: NodeType;
}

/** A React Flow node with architecture-specific data */
export type FlowNode = Node<ArchitectureNodeData>;

/** A React Flow edge between architecture nodes */
export type FlowEdge = Edge & {
  animated?: boolean;
};

/** Nodes + edges for a single diagram type */
export interface FlowData {
  nodes: FlowNode[];
  edges: FlowEdge[];
}

/** One of the three C4 diagram levels */
export type DiagramType = 'context' | 'container' | 'component';

/** Result returned by the Mermaid-to-Flow converter */
export interface ConversionResult {
  nodes: FlowNode[];
  edges: FlowEdge[];
  warnings: string[];
}

/** Visual style config for each node type */
export interface NodeStyleConfig {
  color: string;
  icon: string;
  borderStyle: 'solid' | 'dashed';
  borderRadius: number;
}

/** Map of node type to visual style */
export const NODE_STYLE_MAP: Record<NodeType, NodeStyleConfig> = {
  person:          { color: '#6366f1', icon: '👤', borderStyle: 'solid',  borderRadius: 12 },
  system:          { color: '#2563eb', icon: '🖥️', borderStyle: 'solid',  borderRadius: 12 },
  external_system: { color: '#64748b', icon: '☁️', borderStyle: 'dashed', borderRadius: 12 },
  container:       { color: '#0891b2', icon: '🗄️', borderStyle: 'solid',  borderRadius: 8 },
  component:       { color: '#059669', icon: '🧩', borderStyle: 'solid',  borderRadius: 8 },
  database:        { color: '#d97706', icon: '🛢️', borderStyle: 'solid',  borderRadius: 12 },
};
