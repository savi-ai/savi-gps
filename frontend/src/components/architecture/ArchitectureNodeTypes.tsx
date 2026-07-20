'use client';

import React, { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import type { ArchitectureNodeData, NodeType } from './types';
import { NODE_STYLE_MAP } from './types';

/** Shared node shell — renders header bar, icon, label, description, tech badge, and handles */
function ArchitectureNode({ data, selected }: NodeProps<ArchitectureNodeData>) {
  const style = NODE_STYLE_MAP[data.nodeType] ?? NODE_STYLE_MAP.system;

  return (
    <div
      className={`arch-node arch-node--${data.nodeType}${selected ? ' arch-node--selected' : ''}`}
      style={{
        borderColor: style.color,
        borderStyle: style.borderStyle,
        borderRadius: style.borderRadius,
      }}
    >
      {/* Coloured header bar */}
      <div className="arch-node__header" style={{ background: style.color }}>
        <span className="arch-node__icon">{style.icon}</span>
        <span className="arch-node__label">{data.label}</span>
      </div>

      {/* Body */}
      <div className="arch-node__body">
        {data.description && (
          <p className="arch-node__desc">{data.description}</p>
        )}
        {data.technology && (
          <span className="arch-node__tech" style={{ borderColor: style.color, color: style.color }}>
            {data.technology}
          </span>
        )}
      </div>

      {/* Connection handles — hidden in view mode via CSS class .react-flow--view-mode */}
      <Handle type="target" position={Position.Top} className="arch-handle" />
      <Handle type="source" position={Position.Bottom} className="arch-handle" />
    </div>
  );
}

const MemoNode = memo(ArchitectureNode);

/**
 * Map every NodeType string to the same visual component.
 * React Flow uses this object to resolve `node.type` → component.
 *
 * We register one entry per NodeType so the type field on each node
 * can be set to the NodeType value directly (e.g. type: 'database').
 */
export const nodeTypes: Record<NodeType, React.ComponentType<NodeProps<ArchitectureNodeData>>> = {
  person: MemoNode,
  system: MemoNode,
  external_system: MemoNode,
  container: MemoNode,
  component: MemoNode,
  database: MemoNode,
};
