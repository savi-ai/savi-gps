'use client'

import { useState, useEffect } from 'react'
import apiClient from '@/lib/axios'
import { useAuth } from '@/contexts/AuthContext'
import type { Project, StepContentProps } from '../types'
import { CheckCircle2 } from 'lucide-react'

// Features List Component
interface Feature {
  title: string
  description: string
  business_value: string
  actors: string[]
  high_level_flow: string | string[]
  acceptance_criteria: string[]
}

function FeaturesList({ features, canEdit, projectId, onUpdate }: { features: any[]; canEdit: boolean; projectId: string; onUpdate: () => void }) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editedFeatures, setEditedFeatures] = useState<Feature[]>(features)
  const [saving, setSaving] = useState(false)
  const [deletingIndex, setDeletingIndex] = useState<number | null>(null)

  useEffect(() => {
    // Normalize features to ensure acceptance_criteria is always an array
    const normalizedFeatures = features.map(feature => ({
      ...feature,
      acceptance_criteria: Array.isArray(feature.acceptance_criteria) 
        ? feature.acceptance_criteria 
        : (feature.acceptance_criteria ? [String(feature.acceptance_criteria)] : [])
    }))
    setEditedFeatures(normalizedFeatures)
  }, [features])

  const getFlowSteps = (flow: any): string[] => {
    if (Array.isArray(flow)) {
      return flow.map(item => String(item))
    }
    if (typeof flow === 'string') {
      // Split by comma or newline, then filter empty strings
      return flow.split(/[,\n]/).map(s => s.trim()).filter(s => s.length > 0)
    }
    return []
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      // Ensure high_level_flow is always an array when saving
      const featuresToSave = editedFeatures.map(feature => ({
        ...feature,
        high_level_flow: Array.isArray(feature.high_level_flow) 
          ? feature.high_level_flow 
          : getFlowSteps(feature.high_level_flow)
      }))
      await apiClient.put(`/api/v1/golden-path/projects/${projectId}/features`, featuresToSave)
      onUpdate()
      setEditingIndex(null)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to save features')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (index: number) => {
    if (!confirm('Are you sure you want to delete this feature?')) return

    try {
      setDeletingIndex(index)
      const newFeatures = editedFeatures.filter((_, i) => i !== index)
      await apiClient.put(`/api/v1/golden-path/projects/${projectId}/features`, newFeatures)
      setEditedFeatures(newFeatures)
      onUpdate()
      if (expandedIndex === index) {
        setExpandedIndex(null)
      } else if (expandedIndex !== null && expandedIndex > index) {
        setExpandedIndex(expandedIndex - 1)
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to delete feature')
    } finally {
      setDeletingIndex(null)
    }
  }

  const handleFeatureChange = (index: number, field: string, value: any) => {
    const updated = [...editedFeatures]
    updated[index] = { ...updated[index], [field]: value }
    setEditedFeatures(updated)
  }

  const handleAddCriteria = (index: number) => {
    const updated = [...editedFeatures]
    // Ensure acceptance_criteria is always an array
    if (!Array.isArray(updated[index].acceptance_criteria)) {
      updated[index].acceptance_criteria = []
    }
    updated[index].acceptance_criteria.push('')
    setEditedFeatures(updated)
  }

  const handleRemoveCriteria = (index: number, criteriaIndex: number) => {
    const updated = [...editedFeatures]
    // Ensure acceptance_criteria is always an array
    if (!Array.isArray(updated[index].acceptance_criteria)) {
      updated[index].acceptance_criteria = []
    }
    updated[index].acceptance_criteria = updated[index].acceptance_criteria.filter((_, i) => i !== criteriaIndex)
    setEditedFeatures(updated)
  }

  const handleCriteriaChange = (index: number, criteriaIndex: number, value: string) => {
    const updated = [...editedFeatures]
    // Ensure acceptance_criteria is always an array
    if (!Array.isArray(updated[index].acceptance_criteria)) {
      updated[index].acceptance_criteria = []
    }
    updated[index].acceptance_criteria[criteriaIndex] = value
    setEditedFeatures(updated)
  }

  const handleAddFlowStep = (index: number) => {
    const updated = [...editedFeatures]
    const currentSteps = getFlowSteps(updated[index].high_level_flow)
    updated[index].high_level_flow = [...currentSteps, '']
    setEditedFeatures(updated)
  }

  const handleRemoveFlowStep = (index: number, stepIndex: number) => {
    const updated = [...editedFeatures]
    const currentSteps = getFlowSteps(updated[index].high_level_flow)
    currentSteps.splice(stepIndex, 1)
    updated[index].high_level_flow = currentSteps
    setEditedFeatures(updated)
  }

  const handleFlowStepChange = (index: number, stepIndex: number, value: string) => {
    const updated = [...editedFeatures]
    const currentSteps = getFlowSteps(updated[index].high_level_flow)
    currentSteps[stepIndex] = value
    updated[index].high_level_flow = currentSteps
    setEditedFeatures(updated)
  }

  return (
    <div className="features-list">
      {editedFeatures.map((feature, index) => (
        <div key={index} className="feature-card">
          <div 
            className="feature-header"
            onClick={() => setExpandedIndex(expandedIndex === index ? null : index)}
          >
            <div className="feature-header-content">
              <span className="feature-toggle">{expandedIndex === index ? '▼' : '▶'}</span>
              <h3 className="feature-title">{feature.title || `Feature ${index + 1}`}</h3>
            </div>
            {canEdit && (
              <div className="feature-actions" onClick={(e) => e.stopPropagation()}>
                {editingIndex === index ? (
                  <>
                    <button 
                      className="button-small button-save"
                      onClick={handleSave}
                      disabled={saving}
                    >
                      {saving ? 'Saving...' : 'Save'}
                    </button>
                    <button 
                      className="button-small button-cancel"
                      onClick={() => {
                        setEditingIndex(null)
                        setEditedFeatures(features)
                      }}
                      disabled={saving}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button 
                      className="button-small button-edit"
                      onClick={() => setEditingIndex(index)}
                    >
                      Edit
                    </button>
                    <button 
                      className="button-small button-delete"
                      onClick={() => handleDelete(index)}
                      disabled={deletingIndex === index}
                    >
                      {deletingIndex === index ? 'Deleting...' : 'Delete'}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          
          {expandedIndex === index && (
            <div className="feature-content">
              {editingIndex === index ? (
                <div className="feature-edit-form">
                  <div className="form-field">
                    <label>Title</label>
                    <input
                      type="text"
                      value={feature.title || ''}
                      onChange={(e) => handleFeatureChange(index, 'title', e.target.value)}
                      className="input"
                    />
                  </div>
                  <div className="form-field">
                    <label>Description</label>
                    <textarea
                      value={feature.description || ''}
                      onChange={(e) => handleFeatureChange(index, 'description', e.target.value)}
                      className="textarea"
                      rows={3}
                    />
                  </div>
                  <div className="form-field">
                    <label>Business Value</label>
                    <textarea
                      value={feature.business_value || ''}
                      onChange={(e) => handleFeatureChange(index, 'business_value', e.target.value)}
                      className="textarea"
                      rows={2}
                    />
                  </div>
                  <div className="form-field">
                    <label>Actors (comma-separated)</label>
                    <input
                      type="text"
                      value={Array.isArray(feature.actors) ? feature.actors.join(', ') : (feature.actors || '')}
                      onChange={(e) => handleFeatureChange(index, 'actors', e.target.value.split(',').map(a => a.trim()).filter(a => a))}
                      className="input"
                    />
                  </div>
                  <div className="form-field">
                    <label>High-Level Flow</label>
                    {getFlowSteps(feature.high_level_flow).map((step, si) => (
                      <div key={si} className="criteria-item">
                        <input
                          type="text"
                          value={step}
                          onChange={(e) => handleFlowStepChange(index, si, e.target.value)}
                          className="input"
                          placeholder="Enter flow step"
                        />
                        <button
                          className="button-small button-remove"
                          onClick={() => handleRemoveFlowStep(index, si)}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                    <button
                      className="button-small button-add"
                      onClick={() => handleAddFlowStep(index)}
                    >
                      + Add Step
                    </button>
                  </div>
                  <div className="form-field">
                    <label>Acceptance Criteria</label>
                    {Array.isArray(feature.acceptance_criteria) && feature.acceptance_criteria.map((criteria, ci) => (
                      <div key={ci} className="criteria-item">
                        <input
                          type="text"
                          value={criteria}
                          onChange={(e) => handleCriteriaChange(index, ci, e.target.value)}
                          className="input"
                          placeholder="Enter acceptance criteria"
                        />
                        <button
                          className="button-small button-remove"
                          onClick={() => handleRemoveCriteria(index, ci)}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                    <button
                      className="button-small button-add"
                      onClick={() => handleAddCriteria(index)}
                    >
                      + Add Criteria
                    </button>
                  </div>
                </div>
              ) : (
                <div className="feature-view">
                  <div className="feature-field">
                    <label>Description</label>
                    <p>{feature.description || 'No description provided'}</p>
                  </div>
                  <div className="feature-field">
                    <label>Business Value</label>
                    <p>{feature.business_value || 'No business value specified'}</p>
                  </div>
                  <div className="feature-field">
                    <label>Actors</label>
                    <p>{Array.isArray(feature.actors) && feature.actors.length > 0 ? feature.actors.join(', ') : 'No actors specified'}</p>
                  </div>
                  <div className="feature-field">
                    <label>High-Level Flow</label>
                    {feature.high_level_flow ? (
                      <ul className="flow-list">
                        {Array.isArray(feature.high_level_flow) 
                          ? feature.high_level_flow.map((line, idx) => (
                              <li key={idx}>{typeof line === 'string' ? line : String(line)}</li>
                            ))
                          : typeof feature.high_level_flow === 'string'
                          ? feature.high_level_flow
                              .split('\n')
                              .filter(line => line.trim())
                              .map((line, idx) => (
                                <li key={idx}>{line.trim()}</li>
                              ))
                          : [<li key={0}>{String(feature.high_level_flow)}</li>]
                        }
                      </ul>
                    ) : (
                      <p>No flow specified</p>
                    )}
                  </div>
                  <div className="feature-field">
                    <label>Acceptance Criteria</label>
                    {Array.isArray(feature.acceptance_criteria) && feature.acceptance_criteria.length > 0 ? (
                      <ul>
                        {feature.acceptance_criteria.map((criteria, ci) => (
                          <li key={ci}>{criteria}</li>
                        ))}
                      </ul>
                    ) : (
                      <p>No acceptance criteria specified</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export function FeaturesStepContent({ project, canEdit, onUpdate, onStepChange }: StepContentProps) {
  const { hasPermission } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    // Poll for status if generation is in progress
    if (project.feature_generation_status === 'started') {
      const pollInterval = setInterval(async () => {
        try {
          const response = await apiClient.get(`/api/v1/golden-path/wizard/features-status/${encodeURIComponent(project.name)}`)
          const currentStatus = response.data.status
          setStatus(currentStatus)
          
          if (currentStatus === 'completed') {
            clearInterval(pollInterval)
            setLoading(false)
            onUpdate() // Refresh to get the generated features
          } else if (currentStatus === 'failed') {
            clearInterval(pollInterval)
            setLoading(false)
            setError('Feature generation failed')
          }
        } catch (err: any) {
          console.error('Error polling features status:', err)
        }
      }, 2000) // Poll every 2 seconds

      return () => clearInterval(pollInterval)
    }
  }, [project.feature_generation_status, project.name, onUpdate])

  const handleGenerateFeatures = async () => {
    if (!canEdit) return

    try {
      setLoading(true)
      setError(null)
      setStatus('starting')
      
      // Get conversation history for context
      const conversationHistory = project.conversation_history || []
      
      const response = await apiClient.post('/api/v1/golden-path/wizard/generate-features', {
        project_name: project.name,
        conversation_history: conversationHistory,
        vision: project.vision
      })

      // Start polling for status
      setStatus('started')
      // The useEffect will handle polling
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate features')
      setLoading(false)
      setStatus(null)
      console.error('Error generating features:', err)
    }
  }

  const handleApproveAndSubmit = async () => {
    if (!hasPermission('can_use_product_manager_agent')) return

    try {
      setSubmitting(true)
      // Update step to architecture
      await apiClient.patch(`/api/v1/golden-path/projects/${project.id}/step?step=architecture`)
      onUpdate()
      // Switch to architecture step if onStepChange is provided
      if (onStepChange) {
        onStepChange('architecture')
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to submit for architecture')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="step-panel">
      <div className="step-panel-header">
        <h2>Product Manager - Features</h2>
        {!canEdit && <span className="read-only-indicator">Read Only</span>}
      </div>
      
      {error && (
        <div className="error-message" style={{ margin: '1rem 0', padding: '0.75rem', background: '#fee2e2', color: '#dc2626', borderRadius: '8px' }}>
          {error}
        </div>
      )}

      {status && status !== 'completed' && (
        <div className="status-message generating-features">
          <div className="generating-animation">
            <div className="spinner"></div>
          </div>
          <div className="status-text">
            {status === 'started' ? 'Generating features... This may take a few moments.' : `Status: ${status}`}
          </div>
        </div>
      )}

      {project.features && Array.isArray(project.features) && project.features.length > 0 ? (
        <>
          <FeaturesList 
            features={project.features} 
            canEdit={canEdit}
            projectId={project.id}
            onUpdate={onUpdate}
          />
          {hasPermission('can_use_product_manager_agent') && canEdit && (
            <div className="approve-section">
              <div className="approve-message">
                <CheckCircle2 className="h-5 w-5" />
                <span>Review the features above. When ready, approve and submit for architecture design.</span>
              </div>
              <button 
                className="button approve-button"
                onClick={handleApproveAndSubmit}
                disabled={submitting}
              >
                {submitting ? 'Submitting...' : 'Approve and Submit for Architecture'}
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="empty-state">
          <p>No features generated yet.</p>
          {canEdit && (
            <button 
              className="button" 
              onClick={handleGenerateFeatures}
              disabled={loading || project.feature_generation_status === 'started'}
            >
              {loading || project.feature_generation_status === 'started' ? 'Generating Features...' : 'Generate Features'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

