'use client';

import React, { useState } from 'react';
import type { NodeType } from './types';
import { NODE_STYLE_MAP } from './types';

interface DiagramToolbarProps {
  onAddNode: (type: NodeType) => void;
  onAutoLayout: () => void;
  onSave: () => void;
  onDeleteSelected: () => void;
  hasUnsavedChanges: boolean;
}

const ADD_OPTIONS: { value: NodeType; label: string }[] = [
  { value: 'person', label: 'Person' },
  { value: 'system', label: 'System' },
  { value: 'external_system', label: 'External System' },
  { value: 'container', label: 'Container' },
  { value: 'component', label: 'Component' },
  { value: 'database', label: 'Database' },
];

export function DiagramToolbar({
  onAddNode,
  onAutoLayout,
  onSave,
  onDeleteSelected,
  hasUnsavedChanges,
}: DiagramToolbarProps) {
  const [showAddMenu, setShowAddMenu] = useState(false);

  return (
    <div className="diagram-toolbar">
      <div className="diagram-toolbar__left">
        {/* Add Node dropdown */}
        <div className="diagram-toolbar__dropdown-wrap">
          <button
            className="diagram-toolbar__btn diagram-toolbar__btn--add"
            onClick={() => setShowAddMenu(!showAddMenu)}
          >
            + Add Node
          </button>
          {showAddMenu && (
            <div className="diagram-toolbar__dropdown">
              {ADD_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  className="diagram-toolbar__dropdown-item"
                  onClick={() => {
                    onAddNode(opt.value);
                    setShowAddMenu(false);
                  }}
                >
                  <span>{NODE_STYLE_MAP[opt.value].icon}</span>
                  <span>{opt.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <button className="diagram-toolbar__btn" onClick={onAutoLayout}>
          ⊞ Auto Layout
        </button>

        <button className="diagram-toolbar__btn diagram-toolbar__btn--danger" onClick={onDeleteSelected}>
          🗑 Delete Selected
        </button>
      </div>

      <div className="diagram-toolbar__right">
        {hasUnsavedChanges && <span className="diagram-toolbar__unsaved">Unsaved changes</span>}
        <button
          className="diagram-toolbar__btn diagram-toolbar__btn--save"
          onClick={onSave}
          disabled={!hasUnsavedChanges}
        >
          💾 Save
        </button>
      </div>
    </div>
  );
}
