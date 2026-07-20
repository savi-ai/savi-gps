'use client';

import React, { useState, useEffect } from 'react';
import type { FlowNode, NodeType, ArchitectureNodeData } from './types';
import { NODE_STYLE_MAP } from './types';

interface NodeEditPanelProps {
  node: FlowNode | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (updatedNode: FlowNode) => void;
  onDelete: (nodeId: string) => void;
}

const NODE_TYPE_OPTIONS: { value: NodeType; label: string }[] = [
  { value: 'person', label: 'Person' },
  { value: 'system', label: 'System' },
  { value: 'external_system', label: 'External System' },
  { value: 'container', label: 'Container' },
  { value: 'component', label: 'Component' },
  { value: 'database', label: 'Database' },
];

export function NodeEditPanel({ node, isOpen, onClose, onSave, onDelete }: NodeEditPanelProps) {
  const [label, setLabel] = useState('');
  const [description, setDescription] = useState('');
  const [technology, setTechnology] = useState('');
  const [nodeType, setNodeType] = useState<NodeType>('system');

  useEffect(() => {
    if (node) {
      setLabel(node.data.label);
      setDescription(node.data.description);
      setTechnology(node.data.technology);
      setNodeType(node.data.nodeType);
    }
  }, [node]);

  if (!isOpen || !node) return null;

  const style = NODE_STYLE_MAP[nodeType];

  const handleSave = () => {
    const updatedNode: FlowNode = {
      ...node,
      type: nodeType,
      data: { label, description, technology, nodeType },
    };
    onSave(updatedNode);
    onClose();
  };

  const handleDelete = () => {
    onDelete(node.id);
    onClose();
  };

  return (
    <div className="node-edit-overlay" onClick={onClose}>
      <div className="node-edit-panel" onClick={(e) => e.stopPropagation()}>
        <div className="node-edit-header" style={{ borderBottomColor: style.color }}>
          <span className="node-edit-title">Edit Node</span>
          <button className="node-edit-close" onClick={onClose} aria-label="Close panel">×</button>
        </div>

        <div className="node-edit-body">
          <div className="node-edit-field">
            <label htmlFor="node-label">Name</label>
            <input
              id="node-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Node name"
            />
          </div>

          <div className="node-edit-field">
            <label htmlFor="node-desc">Description</label>
            <textarea
              id="node-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this element do?"
              rows={3}
            />
          </div>

          <div className="node-edit-field">
            <label htmlFor="node-tech">Technology</label>
            <input
              id="node-tech"
              type="text"
              value={technology}
              onChange={(e) => setTechnology(e.target.value)}
              placeholder="e.g. Next.js, PostgreSQL"
            />
          </div>

          <div className="node-edit-field">
            <label htmlFor="node-type">Type</label>
            <select
              id="node-type"
              value={nodeType}
              onChange={(e) => setNodeType(e.target.value as NodeType)}
            >
              {NODE_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {NODE_STYLE_MAP[opt.value].icon} {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="node-edit-actions">
          <button className="node-edit-btn node-edit-btn--delete" onClick={handleDelete}>
            Delete Node
          </button>
          <div className="node-edit-actions-right">
            <button className="node-edit-btn node-edit-btn--cancel" onClick={onClose}>
              Cancel
            </button>
            <button className="node-edit-btn node-edit-btn--save" onClick={handleSave} disabled={!label.trim()}>
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
