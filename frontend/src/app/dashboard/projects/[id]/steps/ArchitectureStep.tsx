'use client'

import { useState, useEffect } from 'react'
import apiClient from '@/lib/axios'
import { useAuth } from '@/contexts/AuthContext'
import { ArchitectureFlow } from '@/components/architecture/ArchitectureFlow'
import { mermaidToFlowData } from '@/components/architecture/mermaidConverter'
import type { FlowNode, FlowEdge, DiagramType } from '@/components/architecture/types'
import type { StepContentProps } from '../types'
import { CheckCircle2 } from 'lucide-react'

export function ArchitectureStepContent({ project, canEdit, onUpdate }: StepContentProps) {
  const { hasPermission, hasRole } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'overview' | 'diagrams' | 'components' | 'tech'>('overview')
  const [selectedDiagram, setSelectedDiagram] = useState<DiagramType>('context')
  const [editing, setEditing] = useState(false)
  const [editedArchitecture, setEditedArchitecture] = useState<any>(null)
  const [submitting, setSubmitting] = useState(false)
  const [converting, setConverting] = useState(false)

  // Determine if user can edit diagrams (architect or admin only)
  const canEditDiagrams = hasPermission('can_use_architecture_agent') || hasRole('admin')

  useEffect(() => {
    // Initialize edited architecture from project
    if (project.architecture) {
      setEditedArchitecture(JSON.parse(JSON.stringify(project.architecture)))
    }
  }, [project.architecture])

  useEffect(() => {
    // Poll for task status if we have a taskId
    if (taskId) {
      const pollInterval = setInterval(async () => {
        try {
          const response = await apiClient.get(`/api/v1/golden-path/wizard/architecture-status/${project.id}`)
          const status = response.data.status
          
          if (status === 'completed') {
            clearInterval(pollInterval)
            setLoading(false)
            setTaskId(null)
            onUpdate() // Refresh to get the generated architecture
          } else if (status === 'failed') {
            clearInterval(pollInterval)
            setLoading(false)
            setTaskId(null)
            setError(response.data.error || 'Architecture generation failed')
          }
        } catch (err: any) {
          console.error('Error polling architecture status:', err)
        }
      }, 2000) // Poll every 2 seconds

      return () => clearInterval(pollInterval)
    }
  }, [taskId, project.id, onUpdate])

  const handleGenerateArchitecture = async () => {
    if (!canEdit) return

    try {
      setLoading(true)
      setError(null)
      
      const response = await apiClient.post(`/api/v1/golden-path/wizard/generate-architecture?project_id=${project.id}`)
      
      setTaskId(response.data.task_id)
      // Polling will start via useEffect
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate architecture')
      setLoading(false)
      console.error('Error generating architecture:', err)
    }
  }

  const handleSaveArchitecture = async () => {
    try {
      await apiClient.put(`/api/v1/golden-path/projects/${project.id}/architecture`, editedArchitecture)
      setEditing(false)
      onUpdate()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save architecture')
    }
  }

  const handleCancelEdit = () => {
    setEditing(false)
    if (project.architecture) {
      setEditedArchitecture(JSON.parse(JSON.stringify(project.architecture)))
    }
  }

  // Save React Flow diagram changes
  const handleDiagramSave = async (nodes: FlowNode[], edges: FlowEdge[]) => {
    try {
      const updatedArch = { ...(editedArchitecture || project.architecture) }
      if (!updatedArch.react_flow_diagrams) updatedArch.react_flow_diagrams = {}
      updatedArch.react_flow_diagrams[selectedDiagram] = { nodes, edges }
      await apiClient.put(`/api/v1/golden-path/projects/${project.id}/architecture`, updatedArch)
      onUpdate()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save diagram')
      throw err // Let ArchitectureFlow know save failed
    }
  }

  // Convert Mermaid diagram to React Flow
  const handleConvertMermaid = () => {
    if (!architecture?.diagrams?.[selectedDiagram]) return
    setConverting(true)
    try {
      const result = mermaidToFlowData(architecture.diagrams[selectedDiagram], selectedDiagram)
      const updatedArch = { ...(editedArchitecture || project.architecture) }
      if (!updatedArch.react_flow_diagrams) updatedArch.react_flow_diagrams = {}
      updatedArch.react_flow_diagrams[selectedDiagram] = { nodes: result.nodes, edges: result.edges }
      setEditedArchitecture(updatedArch)
      // Auto-save the conversion
      apiClient.put(`/api/v1/golden-path/projects/${project.id}/architecture`, updatedArch)
        .then(() => onUpdate())
        .catch((err: any) => setError(err.response?.data?.detail || 'Failed to save converted diagram'))
    } finally {
      setConverting(false)
    }
  }

  const handleApproveAndSubmit = async () => {
    if (!hasPermission('can_use_architecture_agent')) return

    try {
      setSubmitting(true)
      // Update step to stories
      await apiClient.patch(`/api/v1/golden-path/projects/${project.id}/step?step=stories`)
      onUpdate()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to submit for stories')
    } finally {
      setSubmitting(false)
    }
  }

  const architecture = editedArchitecture || project.architecture

  return (
    <div className="step-panel">
      <div className="step-panel-header">
        <h2>Architecture Agent - System Design</h2>
        {!canEdit && <span className="read-only-indicator">Read Only</span>}
      </div>
      
      {error && (
        <div className="error-message" style={{ margin: '1rem 0', padding: '0.75rem', background: '#fee2e2', color: '#dc2626', borderRadius: '8px' }}>
          {error}
        </div>
      )}

      {loading && (
        <div className="status-message generating-features">
          <div className="generating-animation">
            <div className="spinner"></div>
          </div>
          <div className="status-text">
            Generating architecture... This may take a few moments.
          </div>
        </div>
      )}

      {architecture ? (
        <>
          <div className="architecture-tabs">
            <button 
              className={`tab-button ${activeTab === 'overview' ? 'active' : ''}`}
              onClick={() => setActiveTab('overview')}
            >
              Overview
            </button>
            <button 
              className={`tab-button ${activeTab === 'diagrams' ? 'active' : ''}`}
              onClick={() => setActiveTab('diagrams')}
            >
              Diagrams
            </button>
            <button 
              className={`tab-button ${activeTab === 'components' ? 'active' : ''}`}
              onClick={() => setActiveTab('components')}
            >
              Components
            </button>
            <button 
              className={`tab-button ${activeTab === 'tech' ? 'active' : ''}`}
              onClick={() => setActiveTab('tech')}
            >
              Tech Stack
            </button>
          </div>

          <div className="architecture-content">
            {activeTab === 'overview' && (
              <div className="architecture-overview">
                <div className="architecture-section">
                  <h3>Architecture Pattern</h3>
                  <div className="pattern-badge">{architecture.pattern || 'Not specified'}</div>
                </div>

                <div className="architecture-section">
                  <h3>Description</h3>
                  <p>{architecture.description || 'No description provided'}</p>
                </div>

                {architecture.bounded_contexts && architecture.bounded_contexts.length > 0 && (
                  <div className="architecture-section">
                    <h3>Bounded Contexts (DDD)</h3>
                    <ul className="context-list">
                      {architecture.bounded_contexts.map((context: string, idx: number) => (
                        <li key={idx}>{context}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {architecture.domain_events && architecture.domain_events.length > 0 && (
                  <div className="architecture-section">
                    <h3>Domain Events</h3>
                    <ul className="events-list">
                      {architecture.domain_events.map((event: string, idx: number) => (
                        <li key={idx}>{event}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {canEdit && !editing && (
                  <button className="button button-secondary" onClick={() => setEditing(true)}>
                    Edit Architecture
                  </button>
                )}
              </div>
            )}

            {activeTab === 'diagrams' && (
              <div className="architecture-diagrams">
                <div className="diagram-selector">
                  <button 
                    className={`diagram-tab ${selectedDiagram === 'context' ? 'active' : ''}`}
                    onClick={() => setSelectedDiagram('context')}
                  >
                    Context Diagram
                  </button>
                  <button 
                    className={`diagram-tab ${selectedDiagram === 'container' ? 'active' : ''}`}
                    onClick={() => setSelectedDiagram('container')}
                  >
                    Container Diagram
                  </button>
                  <button 
                    className={`diagram-tab ${selectedDiagram === 'component' ? 'active' : ''}`}
                    onClick={() => setSelectedDiagram('component')}
                  >
                    Component Diagram
                  </button>
                </div>

                {/* React Flow interactive diagram */}
                {architecture.react_flow_diagrams?.[selectedDiagram] ? (
                  <ArchitectureFlow
                    nodes={architecture.react_flow_diagrams[selectedDiagram].nodes || []}
                    edges={architecture.react_flow_diagrams[selectedDiagram].edges || []}
                    diagramType={selectedDiagram}
                    canEdit={canEditDiagrams}
                    onSave={handleDiagramSave}
                  />
                ) : architecture.diagrams?.[selectedDiagram] ? (
                  <div className="diagram-convert-prompt">
                    <p>This diagram is in legacy Mermaid format.</p>
                    <button
                      className="button"
                      onClick={handleConvertMermaid}
                      disabled={converting}
                    >
                      {converting ? 'Converting...' : 'Convert to Interactive'}
                    </button>
                  </div>
                ) : (
                  <div className="diagram-container">
                    <p>No {selectedDiagram} diagram available</p>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'components' && (
              <div className="architecture-components">
                {architecture.containers && architecture.containers.length > 0 && (
                  <div className="architecture-section">
                    <h3>Containers</h3>
                    <div className="containers-grid">
                      {architecture.containers.map((container: any, idx: number) => (
                        <div key={idx} className="container-card">
                          <h4>{container.name}</h4>
                          <div className="container-type">{container.type}</div>
                          {container.technology && (
                            <div className="container-tech">Tech: {container.technology}</div>
                          )}
                          <p>{container.description}</p>
                          {container.responsibilities && container.responsibilities.length > 0 && (
                            <div className="responsibilities">
                              <strong>Responsibilities:</strong>
                              <ul>
                                {container.responsibilities.map((resp: string, ri: number) => (
                                  <li key={ri}>{resp}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {architecture.components && architecture.components.length > 0 && (
                  <div className="architecture-section">
                    <h3>Components</h3>
                    <div className="components-list">
                      {architecture.components.map((component: any, idx: number) => (
                        <div key={idx} className="component-card">
                          <h4>{component.name}</h4>
                          {component.container && (
                            <div className="component-container">Container: {component.container}</div>
                          )}
                          <p>{component.responsibility}</p>
                          {component.apis && component.apis.length > 0 && (
                            <div className="component-detail">
                              <strong>APIs:</strong> {component.apis.join(', ')}
                            </div>
                          )}
                          {component.data_stores && component.data_stores.length > 0 && (
                            <div className="component-detail">
                              <strong>Data Stores:</strong> {component.data_stores.join(', ')}
                            </div>
                          )}
                          {component.dependencies && component.dependencies.length > 0 && (
                            <div className="component-detail">
                              <strong>Dependencies:</strong> {component.dependencies.join(', ')}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'tech' && (
              <div className="architecture-tech-stack">
                {architecture.technology_stack ? (
                  <div className="tech-stack-grid">
                    {Object.entries(architecture.technology_stack).map(([category, technologies]: [string, any]) => (
                      <div key={category} className="tech-category">
                        <h3>{category.charAt(0).toUpperCase() + category.slice(1)}</h3>
                        <div className="tech-tags">
                          {Array.isArray(technologies) ? (
                            technologies.map((tech: string, idx: number) => (
                              <span key={idx} className="tech-tag">{tech}</span>
                            ))
                          ) : (
                            <span className="tech-tag">{String(technologies)}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p>No technology stack specified</p>
                )}
              </div>
            )}
          </div>

          {hasPermission('can_use_architecture_agent') && canEdit && !editing && (
            <div className="approve-section">
              <div className="approve-message">
                <CheckCircle2 className="h-5 w-5" />
                <span>Review the architecture above. When ready, approve and submit for story creation.</span>
              </div>
              <button 
                className="button approve-button"
                onClick={handleApproveAndSubmit}
                disabled={submitting}
              >
                {submitting ? 'Submitting...' : 'Approve and Submit for Stories'}
              </button>
            </div>
          )}

          {editing && (
            <div className="edit-actions">
              <button className="button" onClick={handleSaveArchitecture}>
                Save Changes
              </button>
              <button className="button button-secondary" onClick={handleCancelEdit}>
                Cancel
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="empty-state">
          <p>No architecture designed yet. Generate architecture from your features and stories to continue.</p>
          {canEdit && (
            <button 
              className="button" 
              onClick={handleGenerateArchitecture}
              disabled={loading || !Array.isArray(project.features) || project.features.length === 0}
            >
              {loading ? 'Generating Architecture...' : 'Generate Architecture'}
            </button>
          )}
          {(!Array.isArray(project.features) || project.features.length === 0) && (
            <p className="hint-text">You need to generate features first before creating architecture.</p>
          )}
        </div>
      )}
    </div>
  )
}

