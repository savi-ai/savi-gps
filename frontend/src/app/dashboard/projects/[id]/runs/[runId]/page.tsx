'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import './timeline.css'

const STAGES = [
  { key: 'idea', label: 'Idea' },
  { key: 'features', label: 'Features' },
  { key: 'stories', label: 'Stories' },
  { key: 'architecture', label: 'Architecture' },
  { key: 'code', label: 'Code' },
  { key: 'tests', label: 'Tests' },
  { key: 'deploy', label: 'Deploy' },
]

type StageStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'awaiting_approval'

interface PendingApproval {
  approval_id: string
  stage_name: string
}

interface TimelineStage {
  stage_name: string
  status: StageStatus
  started_at: string | null
  completed_at: string | null
  output_summary?: Record<string, unknown> | null
  validation_result?: Record<string, unknown> | null
  error?: string | null
  pending_approval?: PendingApproval | null
}

interface WorkflowRun {
  run_id: string
  status: string
  current_stage: string
  execution_mode: string
  approval_required: boolean
  deployment_url: string | null
  error: string | null
  timeline: TimelineStage[]
  created_at: string | null
  updated_at: string | null
}

function statusIcon(status: StageStatus): string {
  switch (status) {
    case 'completed': return '✓'
    case 'in_progress': return '⟳'
    case 'failed': return '✗'
    case 'awaiting_approval': return '⏸'
    default: return '○'
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/* ── Approval Checkpoint Panel ── */
function ApprovalPanel({
  stage,
  runId,
  userId,
  onActionComplete,
}: {
  stage: TimelineStage
  runId: string
  userId: string
  onActionComplete: () => void
}) {
  const [editedOutput, setEditedOutput] = useState(
    stage.output_summary ? JSON.stringify(stage.output_summary, null, 2) : ''
  )
  const [comments, setComments] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const approvalId = stage.pending_approval?.approval_id

  const violations = stage.validation_result as Record<string, unknown> | null
  const policyViolations = (violations?.policy_violations ?? []) as Array<Record<string, string>>
  const sopViolations = (violations?.sop_violations ?? []) as Array<Record<string, string>>
  const hasViolations = policyViolations.length > 0 || sopViolations.length > 0

  const handleApprove = async () => {
    if (!approvalId) return
    setSubmitting(true)
    setActionError(null)
    try {
      let parsedOutput: Record<string, unknown> | undefined
      try {
        parsedOutput = editedOutput ? JSON.parse(editedOutput) : undefined
      } catch {
        parsedOutput = undefined
      }
      await apiClient.post(`/api/v1/golden-path/workflow/runs/${runId}/approve`, {
        approval_id: approvalId,
        decision: 'approved',
        approver_id: userId,
        comments: comments || undefined,
        edited_output: parsedOutput,
      })
      onActionComplete()
    } catch (err: any) {
      setActionError(err.response?.data?.detail || err.message || 'Approval failed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleReject = async () => {
    if (!approvalId) return
    setSubmitting(true)
    setActionError(null)
    try {
      await apiClient.post(`/api/v1/golden-path/workflow/runs/${runId}/approve`, {
        approval_id: approvalId,
        decision: 'rejected',
        approver_id: userId,
        comments: comments || 'Rejected by reviewer',
      })
      onActionComplete()
    } catch (err: any) {
      setActionError(err.response?.data?.detail || err.message || 'Rejection failed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSwitchToAutopilot = async () => {
    setSubmitting(true)
    setActionError(null)
    try {
      await apiClient.post(`/api/v1/golden-path/workflow/runs/${runId}/switch-mode`)
      onActionComplete()
    } catch (err: any) {
      setActionError(err.response?.data?.detail || err.message || 'Switch failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="approval-panel">
      <div className="approval-panel-header">
        <span className="approval-panel-icon">⏸</span>
        <span className="approval-panel-title">Approval Required — {stage.stage_name}</span>
      </div>

      {/* Policy / SOP violations */}
      {hasViolations && (
        <div className="approval-violations">
          <h4 className="approval-violations-title">⚠ Policy Violations</h4>
          <ul className="approval-violations-list">
            {policyViolations.map((v, i) => (
              <li key={`pv-${i}`}>
                <strong>{v.policy_name}</strong>: {v.rule_violated}
                {v.remediation_hint && <span className="approval-hint"> — {v.remediation_hint}</span>}
              </li>
            ))}
            {sopViolations.map((v, i) => (
              <li key={`sv-${i}`}>
                <strong>SOP</strong>: {v.rule_violated || v.message || JSON.stringify(v)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Stage output (editable) */}
      <div className="approval-section">
        <label className="approval-label">Stage Output (editable)</label>
        <textarea
          className="approval-textarea approval-output"
          value={editedOutput}
          onChange={(e) => setEditedOutput(e.target.value)}
          rows={8}
        />
      </div>

      {/* Comments / feedback */}
      <div className="approval-section">
        <label className="approval-label">Comments / Feedback</label>
        <textarea
          className="approval-textarea"
          value={comments}
          onChange={(e) => setComments(e.target.value)}
          placeholder="Optional comments or rejection feedback…"
          rows={3}
        />
      </div>

      {actionError && <div className="approval-error">{actionError}</div>}

      {/* Action buttons */}
      <div className="approval-actions">
        <button
          className="approval-btn approve"
          onClick={handleApprove}
          disabled={submitting || !approvalId}
        >
          {submitting ? '…' : '✓ Approve'}
        </button>
        <button
          className="approval-btn reject"
          onClick={handleReject}
          disabled={submitting || !approvalId}
        >
          {submitting ? '…' : '✗ Reject'}
        </button>
        <button
          className="approval-btn autopilot"
          onClick={handleSwitchToAutopilot}
          disabled={submitting}
        >
          Switch to Autopilot
        </button>
      </div>
    </div>
  )
}

/* ── Main Page ── */
export default function WorkflowTimelinePage() {
  const router = useRouter()
  const params = useParams()
  const projectId = params.id as string
  const runId = params.runId as string
  const { token, user } = useAuth()

  const [run, setRun] = useState<WorkflowRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedStage, setExpandedStage] = useState<string | null>(null)

  const fetchRun = useCallback(async () => {
    try {
      const response = await apiClient.get(`/api/v1/golden-path/workflow/runs/${runId}`)
      setRun(response.data)
      setError(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to load workflow run')
    } finally {
      setLoading(false)
    }
  }, [runId])

  const isTerminal = run?.status === 'completed' || run?.status === 'failed' || run?.status === 'cancelled'

  // Initial fetch
  useEffect(() => {
    if (token) fetchRun()
  }, [token, fetchRun])

  // Poll every 3 seconds while run is not terminal
  useEffect(() => {
    if (!token || isTerminal) return
    const interval = setInterval(fetchRun, 3000)
    return () => clearInterval(interval)
  }, [token, fetchRun, isTerminal])

  // Build a map from stage_name -> timeline data
  const stageMap = new Map<string, TimelineStage>()
  if (run?.timeline) {
    for (const s of run.timeline) {
      stageMap.set(s.stage_name, s)
    }
  }

  const handleStageClick = (stageKey: string) => {
    const stageData = stageMap.get(stageKey)
    if (stageData?.status === 'completed' || stageData?.status === 'failed') {
      setExpandedStage(expandedStage === stageKey ? null : stageKey)
    }
  }

  if (loading) {
    return (
      <div className="timeline-page">
        <div className="timeline-loading">Loading workflow run…</div>
      </div>
    )
  }

  if (error && !run) {
    return (
      <div className="timeline-page">
        <div className="timeline-error">
          <p>{error}</p>
          <button className="timeline-btn" onClick={() => router.push(`/dashboard/projects/${projectId}`)}>
            Back to Project
          </button>
        </div>
      </div>
    )
  }

  if (!run) return null

  return (
    <div className="timeline-page">
      <div className="timeline-header">
        <button
          className="timeline-back"
          onClick={() => router.push(`/dashboard/projects/${projectId}`)}
        >
          ← Back to Project
        </button>
        <div className="timeline-title-row">
          <h1 className="timeline-title">Workflow Run</h1>
          <span className={`timeline-mode-badge ${run.execution_mode}`}>
            {run.execution_mode === 'autopilot' ? 'Autopilot' : 'Copilot'}
          </span>
          <span className={`timeline-status-badge ${run.status}`}>
            {run.status}
          </span>
        </div>
        <p className="timeline-run-id">Run ID: {run.run_id}</p>
        {run.error && (
          <div className="timeline-run-error">{run.error}</div>
        )}
      </div>

      <div className="timeline-container">
        {STAGES.map((stage, idx) => {
          const data = stageMap.get(stage.key)
          const status: StageStatus = data?.status || 'pending'
          const isActive = run.current_stage === stage.key && status === 'in_progress'
          const isExpanded = expandedStage === stage.key
          const isClickable = status === 'completed' || status === 'failed'
          const isAwaitingApproval = status === 'awaiting_approval'

          return (
            <div key={stage.key} className="timeline-node-wrapper">
              {idx > 0 && (
                <div className={`timeline-connector ${status !== 'pending' ? 'active' : ''}`} />
              )}
              <div
                className={`timeline-node ${status} ${isActive ? 'active-stage' : ''} ${isClickable ? 'clickable' : ''}`}
                onClick={() => handleStageClick(stage.key)}
                role={isClickable ? 'button' : undefined}
                tabIndex={isClickable ? 0 : undefined}
                onKeyDown={(e) => { if (isClickable && (e.key === 'Enter' || e.key === ' ')) handleStageClick(stage.key) }}
              >
                <div className={`timeline-icon ${status}`}>
                  {statusIcon(status)}
                </div>
                <div className="timeline-node-content">
                  <span className="timeline-stage-label">{stage.label}</span>
                  <span className={`timeline-stage-status ${status}`}>{status.replace('_', ' ')}</span>
                  {data?.started_at && (
                    <span className="timeline-stage-time">
                      {formatTime(data.started_at)}
                      {data.completed_at ? ` → ${formatTime(data.completed_at)}` : ''}
                    </span>
                  )}
                </div>
                {isClickable && (
                  <span className="timeline-expand-icon">{isExpanded ? '▾' : '▸'}</span>
                )}
              </div>

              {/* Expanded detail panel for completed/failed stages */}
              {isExpanded && data && (
                <div className="timeline-expanded">
                  {data.output_summary && (
                    <div className="timeline-detail-section">
                      <h4>Output Summary</h4>
                      <pre className="timeline-detail-pre">
                        {JSON.stringify(data.output_summary, null, 2)}
                      </pre>
                    </div>
                  )}
                  {data.validation_result && (
                    <div className="timeline-detail-section">
                      <h4>Validation Result</h4>
                      <pre className="timeline-detail-pre">
                        {JSON.stringify(data.validation_result, null, 2)}
                      </pre>
                    </div>
                  )}
                  {data.error && (
                    <div className="timeline-detail-section timeline-detail-error">
                      <h4>Error</h4>
                      <p>{data.error}</p>
                    </div>
                  )}
                  {!data.output_summary && !data.validation_result && !data.error && (
                    <p className="timeline-detail-empty">No additional details available.</p>
                  )}
                </div>
              )}

              {/* Approval checkpoint panel for awaiting_approval stages */}
              {isAwaitingApproval && data && (
                <ApprovalPanel
                  stage={data}
                  runId={runId}
                  userId={user?.id || ''}
                  onActionComplete={fetchRun}
                />
              )}
            </div>
          )
        })}
      </div>

      {run.deployment_url && (
        <div className="timeline-deployment">
          <span className="timeline-deployment-label">Deployment URL:</span>
          <a href={run.deployment_url} target="_blank" rel="noopener noreferrer" className="timeline-deployment-link">
            {run.deployment_url}
          </a>
        </div>
      )}
    </div>
  )
}
