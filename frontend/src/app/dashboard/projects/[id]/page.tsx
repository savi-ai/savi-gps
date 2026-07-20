'use client'

import { useState, useEffect } from 'react'
import { useRouter, useParams, useSearchParams } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { CheckCircle2 } from 'lucide-react'
import {
  ProjectLineageBanner,
  ProjectContextStrip,
} from '@/components/build/ProjectLineageBanner'
import { useProject } from '@/hooks/queries/useProjects'
import type { Project } from './types'
import { WORKFLOW_STEPS, STEP_ORDER } from './types'
import { IdeaStepContent } from './steps/IdeaStep'
import { FeaturesStepContent } from './steps/FeaturesStep'
import { ArchitectureStepContent } from './steps/ArchitectureStep'
import { StoriesStepContent } from './steps/StoriesStep'
import { DeveloperStepContent } from './steps/DeveloperStep'
import { TestingStepContent } from './steps/TestingStep'
import './project-detail.css'

export default function ProjectDetailPage() {
  const router = useRouter()
  const params = useParams()
  const searchParams = useSearchParams()
  const projectId = params.id as string
  const spawnedFromPlan = searchParams.get('spawned') === '1'
  const fromPlanId = searchParams.get('from_plan')
  const { user, hasPermission, hasRole } = useAuth()
  
  const { data: project, isLoading: loading, error: queryError, refetch } = useProject(projectId)
  const error = queryError ? (queryError as Error).message : null
  const [activeStep, setActiveStep] = useState<string>('idea')
  const [executionMode, setExecutionMode] = useState<'autopilot' | 'copilot'>('copilot')
  const [runningWorkflow, setRunningWorkflow] = useState(false)
  const [workflowRunError, setWorkflowRunError] = useState<string | null>(null)
  const [workflowRunId, setWorkflowRunId] = useState<string | null>(null)

  useEffect(() => {
    if (project?.current_step) {
      setActiveStep(project.current_step)
    }
    if (project?.default_execution_mode) {
      setExecutionMode(project.default_execution_mode as 'autopilot' | 'copilot')
    }
  }, [project?.current_step, project?.default_execution_mode])

  const fetchProject = () => {
    refetch()
  }

  const canEditStep = (stepId: string): boolean => {
    if (!project) return false

    // Check if user has permission for this step type
    const hasStepPermission = (() => {
      switch (stepId) {
        case 'idea':
          return hasPermission('can_use_idea_agent')
        case 'features':
          return hasPermission('can_use_product_manager_agent')
        case 'architecture':
          return hasPermission('can_use_architecture_agent')
        case 'stories':
          return hasPermission('can_use_story_agent')
        case 'developer':
          return hasPermission('can_use_developer_agent')
        case 'testing':
          return hasPermission('can_use_testing_agent')
        default:
          return false
      }
    })()

    if (!hasStepPermission) return false

    // Check if this step is current or previous (sequential editing)
    const stepOrder = STEP_ORDER as readonly string[]
    const currentIndex = stepOrder.indexOf(project.current_step)
    const stepIndex = stepOrder.indexOf(stepId)

    // Can edit if it's the current step or a previous step
    return stepIndex <= currentIndex
  }

  const getStepStatus = (stepId: string): 'completed' | 'active' | 'pending' => {
    if (!project) return 'pending'
    
    const stepOrder = STEP_ORDER as readonly string[]
    const currentIndex = stepOrder.indexOf(project.current_step)
    const stepIndex = stepOrder.indexOf(stepId)
    
    if (stepIndex < currentIndex) return 'completed'
    if (stepId === project.current_step) return 'active'
    return 'pending'
  }

  const hasStepData = (stepId: string): boolean => {
    if (!project) return false
    
    switch (stepId) {
      case 'idea':
        return !!(project.vision || (project.conversation_history && project.conversation_history.length > 0))
      case 'features':
        return !!project.features
      case 'architecture':
        return !!project.architecture
      case 'stories':
        return !!project.stories
      case 'developer':
        return !!project.code_implementation
      case 'testing':
        return !!project.tests
      default:
        return false
    }
  }

  const handleRunWorkflow = async () => {
    if (!project) return
    try {
      setRunningWorkflow(true)
      setWorkflowRunError(null)
      const response = await apiClient.post('/api/v1/workflow/run', {
        idea: project.vision || project.description || '',
        execution_mode: executionMode,
        options: { project_id: project.id }
      })
      setWorkflowRunId(response.data.run_id)
    } catch (err: any) {
      setWorkflowRunError(err.response?.data?.detail || err.message || 'Failed to start workflow run')
    } finally {
      setRunningWorkflow(false)
    }
  }

  if (loading) {
    return (
      <div className="dashboard-page">
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <p>Loading project...</p>
        </div>
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="dashboard-page">
        <div className="error-card">
          <p>{error || 'Project not found'}</p>
          <button className="button" onClick={() => router.push('/dashboard/projects')}>
            Back to Projects
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="dashboard-page">
      <div className="project-detail-header">
        <div>
          <button 
            className="back-button"
            onClick={() => router.push('/dashboard/projects')}
          >
            ← Back to Projects
          </button>
          <h1 className="project-detail-title">{project.name}</h1>
          {project.pillar && project.pillar !== 'build' && (
            <span className="project-pillar-badge capitalize">{project.pillar}</span>
          )}
          {project.description && (
            <p className="project-detail-description">{project.description}</p>
          )}
          {project.linked_repositories && project.linked_repositories.length > 0 && (
            <div className="project-linked-repos">
              <span className="project-linked-repos-label">Linked repos:</span>
              {project.linked_repositories.map((repo) => (
                <button
                  key={repo.id}
                  type="button"
                  className="project-linked-repo-chip"
                  onClick={() => router.push(`/dashboard/intelligence/repositories/${repo.id}`)}
                >
                  {repo.github_full_name || repo.name}
                  {repo.link_type && repo.link_type !== 'context' && (
                    <span className="project-linked-repo-type"> ({repo.link_type})</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <ProjectLineageBanner
        spawnedFromPlan={spawnedFromPlan}
        sourceApplication={project.source_application}
        sourcePlanId={project.source_plan_id}
        fromPlanId={fromPlanId}
        linkedRepositories={project.linked_repositories}
      />

      {/* Workflow Steps */}
      <div className="workflow-wizard">
        <div className="workflow-steps">
          {WORKFLOW_STEPS.map((step, index) => {
            const IconComponent = step.icon
            const status = getStepStatus(step.id)
            const canEdit = canEditStep(step.id)
            const hasData = hasStepData(step.id)
            const isActive = activeStep === step.id
            
            // Check if step is locked (future step)
            const stepOrder = STEP_ORDER as readonly string[]
            const currentIndex = stepOrder.indexOf(project.current_step)
            const stepIndex = stepOrder.indexOf(step.id)
            const isLocked = stepIndex > currentIndex

            return (
              <div
                key={step.id}
                className={`workflow-step ${status} ${isActive ? 'selected' : ''} ${canEdit ? 'editable' : 'read-only'} ${isLocked ? 'locked' : ''}`}
                onClick={() => setActiveStep(step.id)}
              >
                {index > 0 && (
                  <div className="step-connector">
                    <div className={`step-line ${status === 'completed' ? 'completed' : status === 'active' ? 'active' : ''}`}></div>
                  </div>
                )}
                <div className="step-content">
                  <div className={`step-number ${status}`}>
                    {status === 'completed' ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      <IconComponent className="h-4 w-4" />
                    )}
                  </div>
                  <div className="step-label">{step.label}</div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <ProjectContextStrip
        activeStep={activeStep}
        linkedRepositories={project.linked_repositories}
      />

      {/* Execution Mode Selector */}
      <div className="execution-mode-selector" style={{
        margin: '1.5rem 0',
        padding: '1.25rem',
        background: '#f8fafc',
        borderRadius: '12px',
        border: '1px solid #e2e8f0'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '0.95rem', fontWeight: 600, color: '#1e293b' }}>
              Execution Mode
            </h3>
            <p style={{ margin: 0, fontSize: '0.8rem', color: '#64748b' }}>
              Choose how the workflow should run
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.6rem 1rem',
              borderRadius: '8px',
              border: executionMode === 'copilot' ? '2px solid #3b82f6' : '2px solid #e2e8f0',
              background: executionMode === 'copilot' ? '#eff6ff' : '#fff',
              cursor: 'pointer',
              fontSize: '0.85rem',
              transition: 'all 0.15s ease'
            }}>
              <input
                type="radio"
                name="execution_mode"
                value="copilot"
                checked={executionMode === 'copilot'}
                onChange={() => setExecutionMode('copilot')}
                style={{ accentColor: '#3b82f6' }}
              />
              <div>
                <div style={{ fontWeight: 600, color: '#1e293b' }}>Copilot</div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Human-in-the-loop stage-by-stage review</div>
              </div>
            </label>
            <label style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.6rem 1rem',
              borderRadius: '8px',
              border: executionMode === 'autopilot' ? '2px solid #3b82f6' : '2px solid #e2e8f0',
              background: executionMode === 'autopilot' ? '#eff6ff' : '#fff',
              cursor: 'pointer',
              fontSize: '0.85rem',
              transition: 'all 0.15s ease'
            }}>
              <input
                type="radio"
                name="execution_mode"
                value="autopilot"
                checked={executionMode === 'autopilot'}
                onChange={() => setExecutionMode('autopilot')}
                style={{ accentColor: '#3b82f6' }}
              />
              <div>
                <div style={{ fontWeight: 600, color: '#1e293b' }}>Autopilot</div>
                <div style={{ fontSize: '0.75rem', color: '#64748b' }}>Fully automated end-to-end delivery</div>
              </div>
            </label>
            <button
              className="button"
              onClick={handleRunWorkflow}
              disabled={runningWorkflow}
              style={{ marginLeft: '0.5rem' }}
            >
              {runningWorkflow ? 'Starting...' : 'Run Workflow'}
            </button>
          </div>
        </div>
        {workflowRunError && (
          <div style={{ marginTop: '0.75rem', padding: '0.5rem 0.75rem', background: '#fee2e2', color: '#dc2626', borderRadius: '6px', fontSize: '0.85rem' }}>
            {workflowRunError}
          </div>
        )}
        {workflowRunId && !workflowRunError && (
          <div style={{ marginTop: '0.75rem', padding: '0.5rem 0.75rem', background: '#dcfce7', color: '#16a34a', borderRadius: '6px', fontSize: '0.85rem' }}>
            Workflow started (Run ID: {workflowRunId})
          </div>
        )}
      </div>

      {/* Step Content */}
      <div className="step-content-area">
        {activeStep === 'idea' && (
          <IdeaStepContent 
            project={project} 
            canEdit={canEditStep('idea')}
            onUpdate={fetchProject}
            onStepChange={setActiveStep}
          />
        )}
        {activeStep === 'features' && (
          <FeaturesStepContent 
            project={project} 
            canEdit={canEditStep('features')}
            onUpdate={fetchProject}
            onStepChange={setActiveStep}
          />
        )}
        {activeStep === 'architecture' && (
          <ArchitectureStepContent 
            project={project} 
            canEdit={canEditStep('architecture')}
            onUpdate={fetchProject}
          />
        )}
        {activeStep === 'stories' && (
          <StoriesStepContent 
            project={project} 
            canEdit={canEditStep('stories')}
            onUpdate={fetchProject}
          />
        )}
        {activeStep === 'developer' && (
          <DeveloperStepContent 
            project={project} 
            canEdit={canEditStep('developer')}
            onUpdate={fetchProject}
          />
        )}
        {activeStep === 'testing' && (
          <TestingStepContent 
            project={project} 
            canEdit={canEditStep('testing')}
            onUpdate={fetchProject}
          />
        )}
      </div>
    </div>
  )
}
