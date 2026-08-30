'use client'

import { useState, useEffect, useCallback } from 'react'
import apiClient from '@/lib/axios'
import { useAuth } from '@/contexts/AuthContext'
import type { StepContentProps } from '../types'
import { CheckCircle2, Plus, Pencil, Trash2 } from 'lucide-react'

function formatFeatureGenerationError(raw: string): string {
  if (raw.includes('high_level_flow') && raw.includes('string_type')) {
    return 'Feature generation failed while formatting results. Please click Generate Features again.'
  }
  if (raw.length > 240) {
    return `${raw.slice(0, 240)}…`
  }
  return raw
}

interface Feature {
  title: string
  description: string
  business_value: string
  actors: string[]
  high_level_flow: string | string[]
  acceptance_criteria: string[]
}

function emptyFeature(): Feature {
  return {
    title: '',
    description: '',
    business_value: '',
    actors: [],
    high_level_flow: [],
    acceptance_criteria: [''],
  }
}

function normalizeFeature(feature: Partial<Feature> | Record<string, unknown>): Feature {
  const acceptance = feature.acceptance_criteria
  return {
    title: String(feature.title || ''),
    description: String(feature.description || ''),
    business_value: String(feature.business_value || ''),
    actors: Array.isArray(feature.actors)
      ? feature.actors.map(String)
      : feature.actors
        ? [String(feature.actors)]
        : [],
    high_level_flow: feature.high_level_flow ?? [],
    acceptance_criteria: Array.isArray(acceptance)
      ? acceptance.map(String)
      : acceptance
        ? [String(acceptance)]
        : [],
  }
}

function getFlowSteps(flow: Feature['high_level_flow']): string[] {
  if (Array.isArray(flow)) {
    return flow.map((item) => String(item))
  }
  if (typeof flow === 'string') {
    return flow
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
  }
  return []
}

function FeaturesList({
  features,
  canEdit,
  projectId,
  onUpdate,
}: {
  features: Feature[]
  canEdit: boolean
  projectId: string
  onUpdate: () => void
}) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editedFeatures, setEditedFeatures] = useState<Feature[]>(() =>
    features.map(normalizeFeature)
  )
  const [saving, setSaving] = useState(false)
  const [deletingIndex, setDeletingIndex] = useState<number | null>(null)

  useEffect(() => {
    if (editingIndex !== null) return
    setEditedFeatures(features.map(normalizeFeature))
  }, [features, editingIndex])

  const persistFeatures = async (next: Feature[]) => {
    const featuresToSave = next.map((feature) => ({
      ...feature,
      title: feature.title.trim() || 'Untitled Feature',
      actors: Array.isArray(feature.actors) ? feature.actors : [],
      high_level_flow: getFlowSteps(feature.high_level_flow).filter((s) => s.trim()),
      acceptance_criteria: Array.isArray(feature.acceptance_criteria)
        ? feature.acceptance_criteria.filter((c) => c.trim())
        : [],
    }))
    await apiClient.put(`/api/v1/golden-path/projects/${projectId}/features`, featuresToSave)
    setEditedFeatures(featuresToSave)
    onUpdate()
    return featuresToSave
  }

  const handleSave = async () => {
    if (editingIndex === null) return
    const draft = editedFeatures[editingIndex]
    if (!draft?.title?.trim()) {
      alert('Please enter a feature title before saving.')
      return
    }

    try {
      setSaving(true)
      await persistFeatures(editedFeatures)
      setEditingIndex(null)
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to save features'
      alert(detail)
    } finally {
      setSaving(false)
    }
  }

  const handleCancelEdit = () => {
    setEditedFeatures(features.map(normalizeFeature))
    setEditingIndex(null)
  }

  const handleDelete = async (index: number) => {
    const title = editedFeatures[index]?.title?.trim() || `Feature ${index + 1}`
    if (
      !confirm(
        `Delete "${title}"?\n\nThis removes it from the project immediately and cannot be undone from this screen.`
      )
    ) {
      return
    }

    try {
      setDeletingIndex(index)
      const newFeatures = editedFeatures.filter((_, i) => i !== index)
      await persistFeatures(newFeatures)
      if (editingIndex === index) {
        setEditingIndex(null)
      } else if (editingIndex !== null && editingIndex > index) {
        setEditingIndex(editingIndex - 1)
      }
      if (expandedIndex === index) {
        setExpandedIndex(null)
      } else if (expandedIndex !== null && expandedIndex > index) {
        setExpandedIndex(expandedIndex - 1)
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to delete feature'
      alert(detail)
    } finally {
      setDeletingIndex(null)
    }
  }

  const handleAddFeature = () => {
    const next = [...editedFeatures, emptyFeature()]
    const newIndex = next.length - 1
    setEditedFeatures(next)
    setExpandedIndex(newIndex)
    setEditingIndex(newIndex)
  }

  const handleFeatureChange = (index: number, field: keyof Feature, value: Feature[keyof Feature]) => {
    const updated = [...editedFeatures]
    updated[index] = { ...updated[index], [field]: value }
    setEditedFeatures(updated)
  }

  const handleAddCriteria = (index: number) => {
    const updated = [...editedFeatures]
    const criteria = Array.isArray(updated[index].acceptance_criteria)
      ? [...updated[index].acceptance_criteria]
      : []
    criteria.push('')
    updated[index] = { ...updated[index], acceptance_criteria: criteria }
    setEditedFeatures(updated)
  }

  const handleRemoveCriteria = (index: number, criteriaIndex: number) => {
    const updated = [...editedFeatures]
    const criteria = Array.isArray(updated[index].acceptance_criteria)
      ? updated[index].acceptance_criteria.filter((_, i) => i !== criteriaIndex)
      : []
    updated[index] = { ...updated[index], acceptance_criteria: criteria }
    setEditedFeatures(updated)
  }

  const handleCriteriaChange = (index: number, criteriaIndex: number, value: string) => {
    const updated = [...editedFeatures]
    const criteria = Array.isArray(updated[index].acceptance_criteria)
      ? [...updated[index].acceptance_criteria]
      : []
    criteria[criteriaIndex] = value
    updated[index] = { ...updated[index], acceptance_criteria: criteria }
    setEditedFeatures(updated)
  }

  const handleAddFlowStep = (index: number) => {
    const updated = [...editedFeatures]
    updated[index] = {
      ...updated[index],
      high_level_flow: [...getFlowSteps(updated[index].high_level_flow), ''],
    }
    setEditedFeatures(updated)
  }

  const handleRemoveFlowStep = (index: number, stepIndex: number) => {
    const updated = [...editedFeatures]
    const currentSteps = getFlowSteps(updated[index].high_level_flow)
    currentSteps.splice(stepIndex, 1)
    updated[index] = { ...updated[index], high_level_flow: currentSteps }
    setEditedFeatures(updated)
  }

  const handleFlowStepChange = (index: number, stepIndex: number, value: string) => {
    const updated = [...editedFeatures]
    const currentSteps = getFlowSteps(updated[index].high_level_flow)
    currentSteps[stepIndex] = value
    updated[index] = { ...updated[index], high_level_flow: currentSteps }
    setEditedFeatures(updated)
  }

  return (
    <div className="features-list">
      {canEdit && (
        <div className="features-toolbar">
          <p className="features-save-hint">
            Edits need <strong>Save</strong>. Delete asks for confirmation, then updates the
            database right away.
          </p>
          <button type="button" className="button button-add-feature" onClick={handleAddFeature}>
            <Plus className="h-4 w-4" />
            Add Feature
          </button>
        </div>
      )}

      {editedFeatures.length === 0 ? (
        <div className="features-empty-inline">
          <p>No features yet. Add one manually or generate from the idea conversation.</p>
        </div>
      ) : (
        editedFeatures.map((feature, index) => (
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
                        type="button"
                        className="button-small button-save"
                        onClick={handleSave}
                        disabled={saving}
                      >
                        {saving ? 'Saving...' : 'Save'}
                      </button>
                      <button
                        type="button"
                        className="button-small button-cancel"
                        onClick={handleCancelEdit}
                        disabled={saving}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="button-small button-edit"
                        onClick={() => {
                          setEditingIndex(index)
                          setExpandedIndex(index)
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden />
                        Edit
                      </button>
                      <button
                        type="button"
                        className="button-small button-delete"
                        onClick={() => handleDelete(index)}
                        disabled={deletingIndex === index}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
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
                        placeholder="Feature title"
                      />
                    </div>
                    <div className="form-field">
                      <label>Description</label>
                      <textarea
                        value={feature.description || ''}
                        onChange={(e) => handleFeatureChange(index, 'description', e.target.value)}
                        className="textarea"
                        rows={3}
                        placeholder="What does this feature do?"
                      />
                    </div>
                    <div className="form-field">
                      <label>Business Value</label>
                      <textarea
                        value={feature.business_value || ''}
                        onChange={(e) =>
                          handleFeatureChange(index, 'business_value', e.target.value)
                        }
                        className="textarea"
                        rows={2}
                        placeholder="Why does this matter?"
                      />
                    </div>
                    <div className="form-field">
                      <label>Actors (comma-separated)</label>
                      <input
                        type="text"
                        value={
                          Array.isArray(feature.actors)
                            ? feature.actors.join(', ')
                            : feature.actors || ''
                        }
                        onChange={(e) =>
                          handleFeatureChange(
                            index,
                            'actors',
                            e.target.value
                              .split(',')
                              .map((a) => a.trim())
                              .filter(Boolean)
                          )
                        }
                        className="input"
                        placeholder="Admin, Parent, Customer"
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
                            type="button"
                            className="button-small button-remove"
                            onClick={() => handleRemoveFlowStep(index, si)}
                          >
                            Remove
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        className="button-small button-add"
                        onClick={() => handleAddFlowStep(index)}
                      >
                        + Add Step
                      </button>
                    </div>
                    <div className="form-field">
                      <label>Acceptance Criteria</label>
                      {Array.isArray(feature.acceptance_criteria) &&
                        feature.acceptance_criteria.map((criteria, ci) => (
                          <div key={ci} className="criteria-item">
                            <input
                              type="text"
                              value={criteria}
                              onChange={(e) => handleCriteriaChange(index, ci, e.target.value)}
                              className="input"
                              placeholder="Enter acceptance criteria"
                            />
                            <button
                              type="button"
                              className="button-small button-remove"
                              onClick={() => handleRemoveCriteria(index, ci)}
                            >
                              Remove
                            </button>
                          </div>
                        ))}
                      <button
                        type="button"
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
                      <p>
                        {Array.isArray(feature.actors) && feature.actors.length > 0
                          ? feature.actors.join(', ')
                          : 'No actors specified'}
                      </p>
                    </div>
                    <div className="feature-field">
                      <label>High-Level Flow</label>
                      {getFlowSteps(feature.high_level_flow).length > 0 ? (
                        <ul className="flow-list">
                          {getFlowSteps(feature.high_level_flow).map((line, idx) => (
                            <li key={idx}>{line}</li>
                          ))}
                        </ul>
                      ) : (
                        <p>No flow specified</p>
                      )}
                    </div>
                    <div className="feature-field">
                      <label>Acceptance Criteria</label>
                      {Array.isArray(feature.acceptance_criteria) &&
                      feature.acceptance_criteria.length > 0 ? (
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
        ))
      )}
    </div>
  )
}

export function FeaturesStepContent({ project, canEdit, onUpdate, onStepChange }: StepContentProps) {
  const { hasPermission } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const features = Array.isArray(project.features) ? project.features : []
  const hasFeatures = features.length > 0
  const isGenerating =
    loading || project.feature_generation_status === 'started' || status === 'started'

  const pollFeaturesStatus = useCallback(async (): Promise<'completed' | 'failed' | 'pending'> => {
    try {
      const response = await apiClient.get(
        `/api/v1/golden-path/wizard/features-status/${encodeURIComponent(project.name)}`
      )
      const currentStatus = response.data.status as string
      setStatus(currentStatus)

      if (currentStatus === 'completed') {
        setLoading(false)
        onUpdate()
        return 'completed'
      }
      if (currentStatus === 'failed') {
        setLoading(false)
        setStatus(null)
        setError(formatFeatureGenerationError(response.data.error || 'Feature generation failed'))
        onUpdate()
        return 'failed'
      }
      return 'pending'
    } catch (err: unknown) {
      console.error('Error polling features status:', err)
      return 'pending'
    }
  }, [project.name, onUpdate])

  useEffect(() => {
    if (project.feature_generation_status !== 'started') return

    let cancelled = false

    const runPoll = async () => {
      if (cancelled) return
      const outcome = await pollFeaturesStatus()
      if (outcome !== 'pending') {
        cancelled = true
      }
    }

    void runPoll()
    const pollInterval = setInterval(runPoll, 2000)

    return () => {
      cancelled = true
      clearInterval(pollInterval)
    }
  }, [project.feature_generation_status, pollFeaturesStatus])

  const handleGenerateFeatures = async () => {
    if (!canEdit) return

    try {
      setLoading(true)
      setError(null)
      setStatus('starting')
      const conversationHistory = project.conversation_history || []

      await apiClient.post('/api/v1/golden-path/wizard/generate-features', {
        project_name: project.name,
        conversation_history: conversationHistory,
        vision: project.vision,
      })

      setStatus('started')
      onUpdate()
      void pollFeaturesStatus()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to generate features'
      setError(detail)
      setLoading(false)
      setStatus(null)
      console.error('Error generating features:', err)
    }
  }

  const handleApproveAndSubmit = async () => {
    if (!hasPermission('can_use_product_manager_agent')) return

    try {
      setSubmitting(true)
      const nextStep = project.pillar === 'modernize' ? 'stories' : 'architecture'
      await apiClient.patch(`/api/v1/golden-path/projects/${project.id}/step?step=${nextStep}`)
      onUpdate()
      if (onStepChange) {
        onStepChange(nextStep)
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        `Failed to submit for ${project.pillar === 'modernize' ? 'tasks' : 'architecture'}`
      alert(detail)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="step-panel">
      <div className="step-panel-header">
        <h2>{project.pillar === 'modernize' ? 'Requirements' : 'Product Manager - Features'}</h2>
        {!canEdit && <span className="read-only-indicator">Read Only</span>}
      </div>

      {error && (
        <div
          className="error-message"
          style={{
            margin: '1rem 0',
            padding: '0.75rem',
            background: '#fee2e2',
            color: '#dc2626',
            borderRadius: '8px',
          }}
        >
          {error}
        </div>
      )}

      {isGenerating && (
        <div className="status-message generating-features">
          <div className="generating-animation">
            <div className="spinner"></div>
          </div>
          <div className="status-text">Generating features... This may take a few moments.</div>
        </div>
      )}

      {!isGenerating && (
        <>
          <FeaturesList
            features={features}
            canEdit={canEdit}
            projectId={project.id}
            onUpdate={onUpdate}
          />

          {canEdit && (
            <div className="features-generate-row">
              <button
                type="button"
                className="button button-secondary"
                onClick={handleGenerateFeatures}
                disabled={loading || project.feature_generation_status === 'started'}
              >
                {error
                  ? 'Retry Generate Features'
                  : hasFeatures
                    ? 'Regenerate Features'
                    : 'Generate Features'}
              </button>
              {!hasFeatures && (
                <p className="hint-text">
                  Generate from the Idea Agent conversation, or use Add Feature above to create one
                  manually.
                </p>
              )}
            </div>
          )}

          {hasFeatures && hasPermission('can_use_product_manager_agent') && canEdit && (
            <div className="approve-section">
              <div className="approve-message">
                <CheckCircle2 className="h-5 w-5" />
                <span>
                  Review the features above. When ready, approve and submit for architecture design.
                </span>
              </div>
              <button
                type="button"
                className="button approve-button"
                onClick={handleApproveAndSubmit}
                disabled={submitting}
              >
                {submitting
                  ? 'Submitting...'
                  : project.pillar === 'modernize'
                    ? 'Approve and Continue to Tasks'
                    : 'Approve and Submit for Architecture'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
