'use client'

import { useState, useEffect } from 'react'
import apiClient from '@/lib/axios'
import { useAuth } from '@/contexts/AuthContext'
import type { StepContentProps } from '../types'
import { CheckCircle2 } from 'lucide-react'

export function StoriesStepContent({ project, canEdit, onUpdate, onStepChange }: StepContentProps) {
  const { hasPermission } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [expandedStories, setExpandedStories] = useState<Set<string>>(new Set())
  const [editingStory, setEditingStory] = useState<string | null>(null)
  const [editedStories, setEditedStories] = useState<any[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    // Initialize edited stories from project
    if (project.stories && Array.isArray(project.stories)) {
      setEditedStories(JSON.parse(JSON.stringify(project.stories)))
    }
  }, [project.stories])

  useEffect(() => {
    // Poll for task status if we have a taskId
    if (taskId) {
      const pollInterval = setInterval(async () => {
        try {
          const response = await apiClient.get(`/api/v1/tasks/${taskId}`)
          const task = response.data
          
          if (task.status === 'completed') {
            clearInterval(pollInterval)
            setLoading(false)
            setTaskId(null)
            onUpdate() // Refresh to get the generated stories
          } else if (task.status === 'failed') {
            clearInterval(pollInterval)
            setLoading(false)
            setTaskId(null)
            setError(task.error || 'Story generation failed')
          }
        } catch (err: any) {
          console.error('Error polling task status:', err)
        }
      }, 2000) // Poll every 2 seconds

      return () => clearInterval(pollInterval)
    }
  }, [taskId, onUpdate])

  const handleGenerateStories = async () => {
    if (!canEdit) return

    try {
      setLoading(true)
      setError(null)
      
      const response = await apiClient.post(`/api/v1/golden-path/wizard/generate-stories?project_id=${project.id}`)
      
      setTaskId(response.data.task_id)
      // Polling will start via useEffect
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate stories')
      setLoading(false)
      console.error('Error generating stories:', err)
    }
  }

  const toggleStory = (storyId: string) => {
    const newExpanded = new Set(expandedStories)
    if (newExpanded.has(storyId)) {
      newExpanded.delete(storyId)
    } else {
      newExpanded.add(storyId)
    }
    setExpandedStories(newExpanded)
  }

  const handleEditStory = (storyId: string) => {
    setEditingStory(storyId)
  }

  const handleSaveStory = async (storyId: string) => {
    try {
      await apiClient.put(`/api/v1/golden-path/projects/${project.id}/stories`, editedStories)
      setEditingStory(null)
      onUpdate()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save story')
    }
  }

  const handleCancelEdit = () => {
    setEditingStory(null)
    // Reset edited stories to original
    if (project.stories) {
      setEditedStories(JSON.parse(JSON.stringify(project.stories)))
    }
  }

  const handleStoryChange = (storyId: string, field: string, value: any) => {
    setEditedStories(prev => prev.map(story => 
      story.id === storyId ? { ...story, [field]: value } : story
    ))
  }

  const handleDeleteStory = async (storyId: string) => {
    if (!confirm('Are you sure you want to delete this story?')) return

    try {
      await apiClient.delete(`/api/v1/golden-path/projects/${project.id}/stories/${storyId}`)
      onUpdate()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete story')
    }
  }

  const handleApproveStory = async (storyId: string) => {
    try {
      await apiClient.post(`/api/v1/golden-path/projects/${project.id}/stories/${storyId}/approve`)
      onUpdate()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to approve story')
    }
  }

  const handleApproveAll = async () => {
    if (!hasPermission('can_use_story_agent')) return

    try {
      setSubmitting(true)
      // Update step to architecture
      await apiClient.patch(`/api/v1/golden-path/projects/${project.id}/step?step=architecture`)
      onUpdate()
      if (onStepChange) {
        onStepChange('architecture')
      }
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to submit for architecture')
    } finally {
      setSubmitting(false)
    }
  }

  const stories = editedStories.length > 0 ? editedStories : (project.stories || [])

  return (
    <div className="step-panel">
      <div className="step-panel-header">
        <h2>Story Agent - User Stories</h2>
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
            Generating stories... This may take a few moments.
          </div>
        </div>
      )}

      {stories && Array.isArray(stories) && stories.length > 0 ? (
        <>
          <div className="stories-list">
            {stories.map((story, index) => {
              const isExpanded = expandedStories.has(story.id)
              const isEditing = editingStory === story.id
              
              return (
                <div key={story.id || index} className="story-card">
                  <div className="story-header" onClick={() => !isEditing && toggleStory(story.id)}>
                    <div className="story-title-row">
                      <h3>{story.title}</h3>
                      <div className="story-actions">
                        {story.status === 'approved' && (
                          <span className="story-badge approved">Approved</span>
                        )}
                        {canEdit && !isEditing && (
                          <>
                            <button 
                              className="button-icon"
                              onClick={(e) => { e.stopPropagation(); handleEditStory(story.id); }}
                              title="Edit story"
                            >
                              ✏️
                            </button>
                            {story.status !== 'approved' && (
                              <button 
                                className="button-icon"
                                onClick={(e) => { e.stopPropagation(); handleApproveStory(story.id); }}
                                title="Approve story"
                              >
                                ✓
                              </button>
                            )}
                            <button 
                              className="button-icon"
                              onClick={(e) => { e.stopPropagation(); handleDeleteStory(story.id); }}
                              title="Delete story"
                            >
                              🗑️
                            </button>
                          </>
                        )}
                        <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
                      </div>
                    </div>
                    <div className="story-meta">
                      <span className="story-persona">👤 {story.persona}</span>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="story-content">
                      {isEditing ? (
                        <div className="story-edit-form">
                          <div className="form-field">
                            <label>Title</label>
                            <input
                              type="text"
                              value={story.title}
                              onChange={(e) => handleStoryChange(story.id, 'title', e.target.value)}
                              className="input"
                            />
                          </div>
                          <div className="form-field">
                            <label>Description</label>
                            <textarea
                              value={story.description}
                              onChange={(e) => handleStoryChange(story.id, 'description', e.target.value)}
                              className="textarea"
                              rows={4}
                            />
                          </div>
                          <div className="form-field">
                            <label>Persona</label>
                            <input
                              type="text"
                              value={story.persona}
                              onChange={(e) => handleStoryChange(story.id, 'persona', e.target.value)}
                              className="input"
                            />
                          </div>
                          <div className="form-field">
                            <label>Goal</label>
                            <textarea
                              value={story.goal}
                              onChange={(e) => handleStoryChange(story.id, 'goal', e.target.value)}
                              className="textarea"
                              rows={2}
                            />
                          </div>
                          <div className="form-field">
                            <label>Acceptance Criteria (Gherkin)</label>
                            <textarea
                              value={story.gherkin_acceptance_criteria}
                              onChange={(e) => handleStoryChange(story.id, 'gherkin_acceptance_criteria', e.target.value)}
                              className="textarea"
                              rows={6}
                              style={{ fontFamily: 'monospace', fontSize: '0.9rem' }}
                            />
                          </div>
                          <div className="edit-actions">
                            <button className="button" onClick={() => handleSaveStory(story.id)}>
                              Save Changes
                            </button>
                            <button className="button button-secondary" onClick={handleCancelEdit}>
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="story-view">
                          <div className="story-field">
                            <label>Description</label>
                            <p className="story-description">{story.description}</p>
                          </div>
                          <div className="story-field">
                            <label>Goal</label>
                            <p>{story.goal}</p>
                          </div>
                          <div className="story-field">
                            <label>Acceptance Criteria</label>
                            <pre className="gherkin-criteria">{story.gherkin_acceptance_criteria}</pre>
                          </div>
                          {story.nfrs && story.nfrs.length > 0 && (
                            <div className="story-field">
                              <label>Non-Functional Requirements</label>
                              <ul className="nfr-list">
                                {story.nfrs.map((nfr: string, idx: number) => (
                                  <li key={idx}>{nfr}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {hasPermission('can_use_story_agent') && canEdit && (
            <div className="approve-section">
              <div className="approve-message">
                <CheckCircle2 className="h-5 w-5" />
                <span>Review the stories above. When ready, approve and submit for architecture design.</span>
              </div>
              <button 
                className="button approve-button"
                onClick={handleApproveAll}
                disabled={submitting}
              >
                {submitting ? 'Submitting...' : 'Approve and Submit for Architecture'}
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="empty-state">
          <p>No stories created yet. Generate stories from your features to continue.</p>
          {canEdit && (
            <button 
              className="button" 
              onClick={handleGenerateStories}
              disabled={loading || !Array.isArray(project.features) || project.features.length === 0}
            >
              {loading ? 'Generating Stories...' : 'Generate Stories'}
            </button>
          )}
          {(!Array.isArray(project.features) || project.features.length === 0) && (
            <p className="hint-text">You need to generate features first before creating stories.</p>
          )}
        </div>
      )}
    </div>
  )
}

