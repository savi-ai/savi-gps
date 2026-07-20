'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type NodeMouseHandler,
  type OnSelectionChangeParams,
} from 'reactflow';
import 'reactflow/dist/style.css';

import type { FlowNode, FlowEdge, DiagramType, NodeType } from './types';
import { NODE_STYLE_MAP } from './types';
import { nodeTypes } from './ArchitectureNodeTypes';
import { applyLayout } from './useAutoLayout';
import { DiagramToolbar } from './DiagramToolbar';
import { NodeEditPanel } from './NodeEditPanel';

interface ArchitectureFlowProps {
  nodes: FlowNode[];
  edges: FlowEdge[];
  diagramType: DiagramType;
  canEdit: boolean;
  onSave: (nodes: FlowNode[], edges: FlowEdge[]) => Promise<void>;
}

/** Check if any node is missing a real position (all zeros = needs layout) */
function needsLayout(nodes: FlowNode[]): boolean {
  if (nodes.length === 0) return false;
  return nodes.every((n) => n.position.x === 0 && n.position.y === 0);
}

let idCounter = 0;
function nextId(prefix: string) {
  idCounter += 1;
  return `${prefix}_${Date.now()}_${idCounter}`;
}

export function ArchitectureFlow({ nodes: initialNodes, edges: initialEdges, diagramType, canEdit, onSave }: ArchitectureFlowProps) {
  // Apply layout on mount if nodes lack positions
  const layoutApplied = useRef(false);
  const initialData = useMemo(() => {
    if (needsLayout(initialNodes) && !layoutApplied.current) {
      layoutApplied.current = true;
      return applyLayout(initialNodes, initialEdges);
    }
    return { nodes: initialNodes, edges: initialEdges };
  }, [initialNodes, initialEdges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialData.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialData.edges);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [editingNode, setEditingNode] = useState<FlowNode | null>(null);
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<string>>(new Set());

  // Sync when parent data changes (e.g. switching diagram type)
  useEffect(() => {
    layoutApplied.current = false;
    const data = needsLayout(initialNodes)
      ? applyLayout(initialNodes, initialEdges)
      : { nodes: initialNodes, edges: initialEdges };
    setNodes(data.nodes);
    setEdges(data.edges);
    setHasUnsavedChanges(false);
    setEditingNode(null);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  // Track unsaved changes in edit mode
  const markDirty = useCallback(() => {
    if (canEdit) setHasUnsavedChanges(true);
  }, [canEdit]);

  // Handle new edge connections
  const onConnect = useCallback(
    (connection: Connection) => {
      if (!canEdit) return;
      const label = prompt('Edge label (optional):') ?? '';
      setEdges((eds) =>
        addEdge({ ...connection, id: nextId('edge'), label, animated: true }, eds)
      );
      markDirty();
    },
    [canEdit, setEdges, markDirty]
  );

  // Node click → open edit panel
  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      if (canEdit) setEditingNode(node as FlowNode);
    },
    [canEdit]
  );

  // Selection tracking
  const onSelectionChange = useCallback(({ nodes: sel }: OnSelectionChangeParams) => {
    setSelectedNodeIds(new Set(sel.map((n) => n.id)));
  }, []);

  // Toolbar: add node
  const handleAddNode = useCallback(
    (type: NodeType) => {
      const newNode: FlowNode = {
        id: nextId('node'),
        type,
        position: { x: 100 + Math.random() * 200, y: 100 + Math.random() * 200 },
        data: { label: 'New Node', description: '', technology: '', nodeType: type },
      };
      setNodes((nds) => [...nds, newNode]);
      markDirty();
    },
    [setNodes, markDirty]
  );

  // Toolbar: auto layout
  const handleAutoLayout = useCallback(() => {
    const result = applyLayout(nodes, edges);
    setNodes(result.nodes);
    setEdges(result.edges);
    markDirty();
  }, [nodes, edges, setNodes, setEdges, markDirty]);

  // Toolbar: delete selected (cascade edges)
  const handleDeleteSelected = useCallback(() => {
    if (selectedNodeIds.size === 0) return;
    setNodes((nds) => nds.filter((n) => !selectedNodeIds.has(n.id)));
    setEdges((eds) => eds.filter((e) => !selectedNodeIds.has(e.source) && !selectedNodeIds.has(e.target)));
    setSelectedNodeIds(new Set());
    markDirty();
  }, [selectedNodeIds, setNodes, setEdges, markDirty]);

  // Toolbar: save
  const handleSave = useCallback(async () => {
    try {
      await onSave(nodes as FlowNode[], edges as FlowEdge[]);
      setHasUnsavedChanges(false);
    } catch {
      // Parent handles error display
    }
  }, [nodes, edges, onSave]);

  // Edit panel: save node
  const handleNodeSave = useCallback(
    (updatedNode: FlowNode) => {
      setNodes((nds) => nds.map((n) => (n.id === updatedNode.id ? updatedNode : n)));
      markDirty();
    },
    [setNodes, markDirty]
  );

  // Edit panel: delete node (cascade edges)
  const handleNodeDelete = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      markDirty();
    },
    [setNodes, setEdges, markDirty]
  );

  // Handle nodes change — only mark dirty in edit mode
  const handleNodesChange = useCallback(
    (changes: any) => {
      onNodesChange(changes);
      // Don't mark dirty for view-mode drags
      if (canEdit) {
        const hasMeaningfulChange = changes.some(
          (c: any) => c.type === 'position' && c.dragging === false
        );
        if (hasMeaningfulChange) markDirty();
      }
    },
    [onNodesChange, canEdit, markDirty]
  );

  // Minimap node color
  const minimapNodeColor = useCallback((node: any) => {
    const nt = node.data?.nodeType as NodeType;
    return NODE_STYLE_MAP[nt]?.color ?? '#94a3b8';
  }, []);

  return (
    <div className="arch-flow-wrapper">
      {canEdit && (
        <DiagramToolbar
          onAddNode={handleAddNode}
          onAutoLayout={handleAutoLayout}
          onSave={handleSave}
          onDeleteSelected={handleDeleteSelected}
          hasUnsavedChanges={hasUnsavedChanges}
        />
      )}

      {!canEdit && <div className="arch-readonly-badge">Read Only</div>}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={canEdit ? onEdgesChange : undefined}
        onConnect={canEdit ? onConnect : undefined}
        onNodeClick={onNodeClick}
        onSelectionChange={onSelectionChange}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.2}
        maxZoom={2}
        nodesDraggable
        nodesConnectable={canEdit}
        elementsSelectable={canEdit}
        deleteKeyCode={canEdit ? 'Delete' : null}
        className={canEdit ? '' : 'react-flow--view-mode'}
      >
        <Background gap={20} size={1} color="#e2e8f0" />
        <Controls showInteractive={false} />
        <MiniMap nodeColor={minimapNodeColor} pannable zoomable />
      </ReactFlow>

      <NodeEditPanel
        node={editingNode}
        isOpen={!!editingNode}
        onClose={() => setEditingNode(null)}
        onSave={handleNodeSave}
        onDelete={handleNodeDelete}
      />
    </div>
  );
}
