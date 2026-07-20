'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import './deploy.css'

interface DeploymentData {
  deployment_id: string
  workflow_run_id: string
  project_id: string
  status: string
  provider: string | null
  region: string | null
  resource_type: string | null
  resource_identifiers: Record<string, unknown> | null
  environment_url: string | null
  health_check_status: string | null
  infrastructure_artifacts: Record<string, unknown> | null
  failure_reason: string | null
  last_successful_step: string | null
  logs: Array<{ message: string; timestamp?: string; level?: string }> | null
  created_at: string | null
  updated_at: string | null
}

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  provisioning: { label: 'Provisioning', color: 'blue', icon: '⟳' },
  deploying: { label: 'Deploying', color: 'blue', icon: '⟳' },
  health_checking: { label: 'Health Checking', color: 'amber', icon: '⟳' },
  live: { label: 'Live', color: 'green', icon: '✓' },
  failed: { label: 'Failed', color: 'red', icon: '✗' },
  torn_down: { label: 'Torn Down', color: 'gray', icon: '⊘' },
}

function isInProgress(status: string): boolean {
  return ['provisioning', 'deploying', 'health_checking'].includes(status)
}

export default function DeploymentViewPage() {
  const router = useRouter()
  const params = useParams()
  const projectId = params.id as string
  const runId = params.runId as string
  const { token } = useAuth()

  const [deployment, setDeployment] = useState<DeploymentData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchDeployment = useCallback(async () => {
    try {
      const response = await apiClient.get(`/api/v1/deployments/${runId}`)
      setDeployment(response.data)
      setError(null)
    } catch (err: any) {
      if (err.response?.status === 404) {
        setError('No deployment found for this run.')
      } else {
        setError(err.response?.data?.detail || err.message || 'Failed to load deployment')
      }
    } finally {
      setLoading(false)
    }
  }, [runId])

  // Initial fetch
  useEffect(() => {
    if (token) fetchDeployment()
  }, [token, fetchDeployment])

  // Poll every 5 seconds while deployment is in progress
  useEffect(() => {
    if (!token || !deployment || !isInProgress(deployment.status)) return
    const interval = setInterval(fetchDeployment, 5000)
    return () => clearInterval(interval)
  }, [token, deployment, fetchDeployment])

  const statusInfo = deployment ? STATUS_CONFIG[deployment.status] || { label: deployment.status, color: 'gray', icon: '?' } : null

  if (loading) {
    return (
      <div className="deploy-page">
        <div className="deploy-loading">Loading deployment…</div>
      </div>
    )
  }

  if (error && !deployment) {
    return (
      <div className="deploy-page">
        <div className="deploy-error">
          <p>{error}</p>
          <button className="deploy-btn" onClick={() => router.push(`/dashboard/projects/${projectId}/runs/${runId}`)}>
            Back to Timeline
          </button>
        </div>
      </div>
    )
  }

  if (!deployment) return null

  return (
    <div className="deploy-page">
      <button
        className="deploy-back"
        onClick={() => router.push(`/dashboard/projects/${projectId}/runs/${runId}`)}
      >
        ← Back to Timeline
      </button>
      <h1 className="deploy-title">Deployment View</h1>
      <p className="deploy-run-id">Run ID: {runId}</p>

      {/* Status badge */}
      <div className="deploy-status-section">
        <span className={`deploy-status-badge ${statusInfo?.color}`}>
          <span className="deploy-status-icon">{statusInfo?.icon}</span>
          {statusInfo?.label}
        </span>
        {isInProgress(deployment.status) && (
          <span className="deploy-polling-hint">Updating every 5s…</span>
        )}
      </div>

      {/* Environment URL */}
      {deployment.environment_url && deployment.status === 'live' && (
        <div className="deploy-url-section">
          <span className="deploy-url-label">Environment URL</span>
          <a
            href={deployment.environment_url}
            target="_blank"
            rel="noopener noreferrer"
            className="deploy-url-link"
          >
            {deployment.environment_url}
          </a>
        </div>
      )}

      {/* Failure info */}
      {deployment.status === 'failed' && (
        <div className="deploy-failure-section">
          {deployment.failure_reason && (
            <div className="deploy-failure-reason">
              <h3>Failure Reason</h3>
              <p>{deployment.failure_reason}</p>
            </div>
          )}
          {deployment.last_successful_step && (
            <div className="deploy-last-step">
              <h3>Last Successful Step</h3>
              <p>{deployment.last_successful_step}</p>
            </div>
          )}
        </div>
      )}

      {/* Infrastructure details */}
      <div className="deploy-infra-section">
        <h2 className="deploy-section-title">Infrastructure Details</h2>
        <div className="deploy-infra-grid">
          <div className="deploy-infra-item">
            <span className="deploy-infra-label">Provider</span>
            <span className="deploy-infra-value">{deployment.provider || '—'}</span>
          </div>
          <div className="deploy-infra-item">
            <span className="deploy-infra-label">Region</span>
            <span className="deploy-infra-value">{deployment.region || '—'}</span>
          </div>
          <div className="deploy-infra-item">
            <span className="deploy-infra-label">Resource Type</span>
            <span className="deploy-infra-value">{deployment.resource_type || '—'}</span>
          </div>
        </div>
        {deployment.resource_identifiers && Object.keys(deployment.resource_identifiers).length > 0 && (
          <div className="deploy-identifiers">
            <h3>Resource Identifiers</h3>
            <pre className="deploy-pre">{JSON.stringify(deployment.resource_identifiers, null, 2)}</pre>
          </div>
        )}
      </div>

      {/* Deployment logs */}
      {deployment.logs && deployment.logs.length > 0 && (
        <div className="deploy-logs-section">
          <h2 className="deploy-section-title">Deployment Logs</h2>
          <div className="deploy-logs-container">
            {deployment.logs.map((entry, idx) => (
              <div key={idx} className="deploy-log-entry">
                {entry.timestamp && <span className="deploy-log-time">{entry.timestamp}</span>}
                {entry.level && <span className={`deploy-log-level ${entry.level}`}>{entry.level}</span>}
                <span className="deploy-log-message">{entry.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
