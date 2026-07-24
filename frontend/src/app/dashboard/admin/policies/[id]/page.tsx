'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { ArrowLeft } from 'lucide-react'
import '../policies.css'

interface PolicyMeta {
  id: string
  policy_id: string
  name: string
  description: string | null
  category: string
  status: string
  applies_to: string[] | null
  stacks: string[] | null
  tags: string[] | null
  active_version_id: string | null
  active_version_number: string | null
}

interface PolicyVersion {
  id: string
  version_number: string
  content: Record<string, unknown> | null
  content_yaml: string | null
  is_draft: boolean
}

export default function PolicyDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const { hasPermission } = useAuth()
  const [policy, setPolicy] = useState<PolicyMeta | null>(null)
  const [version, setVersion] = useState<PolicyVersion | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!hasPermission('can_manage_policies')) {
      router.push('/dashboard')
      return
    }
    if (!id) return
    ;(async () => {
      try {
        setLoading(true)
        const [metaRes, versionsRes] = await Promise.all([
          apiClient.get(`/api/v1/policies/${id}`),
          apiClient.get(`/api/v1/policies/${id}/versions`),
        ])
        const meta = metaRes.data as PolicyMeta
        setPolicy(meta)
        const versions = (versionsRes.data || []) as PolicyVersion[]
        const active =
          versions.find((v) => v.id === meta.active_version_id) || versions[0] || null
        setVersion(active)
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Failed to load policy')
      } finally {
        setLoading(false)
      }
    })()
  }, [id, hasPermission, router])

  if (!hasPermission('can_manage_policies')) return null

  if (loading) {
    return (
      <div className="policies-page">
        <div className="loading-state">Loading policy...</div>
      </div>
    )
  }

  if (error || !policy) {
    return (
      <div className="policies-page">
        <div className="error-state">{error || 'Policy not found'}</div>
        <button className="btn-secondary" onClick={() => router.push('/dashboard/admin/policies')}>
          Back to catalog
        </button>
      </div>
    )
  }

  const content = (version?.content || {}) as Record<string, any>
  const rules = (content.rules || []) as Array<{
    id?: string
    title?: string
    description?: string
    severity?: string
    guidelines?: string[]
  }>
  const checks = (content.checks || []) as Array<{
    type?: string
    description?: string
    pattern?: string
    questions?: string[]
  }>
  const remediation = (content.remediation_hints || {}) as Record<string, string>
  const markdown = typeof content.markdown === 'string' ? content.markdown : null

  return (
    <div className="policies-page">
      <div className="policies-header">
        <div>
          <button
            className="btn-secondary back-btn"
            onClick={() => router.push('/dashboard/admin/policies')}
          >
            <ArrowLeft className="h-4 w-4" />
            Catalog
          </button>
          <h1 className="policies-title" style={{ marginTop: '0.75rem' }}>
            {policy.name}
          </h1>
          <p className="policies-header-sub">
            {policy.policy_id} · {policy.category} · {policy.status}
            {policy.active_version_number ? ` · v${policy.active_version_number}` : ''}
          </p>
        </div>
      </div>

      <div className="policy-detail-card">
        {policy.description && (
          <section className="policy-detail-section">
            <h2>Description</h2>
            <p>{policy.description}</p>
          </section>
        )}

        <section className="policy-detail-section">
          <h2>Applies to</h2>
          <div className="applies-to-chips">
            {(policy.applies_to || []).length ? (
              policy.applies_to!.map((a) => (
                <span key={a} className="chip">
                  {a}
                </span>
              ))
            ) : (
              <span className="chip-empty">—</span>
            )}
          </div>
        </section>

        {(policy.tags || []).length > 0 && (
          <section className="policy-detail-section">
            <h2>Tags</h2>
            <div className="applies-to-chips">
              {policy.tags!.map((t) => (
                <span key={t} className="chip chip-tag">
                  {t}
                </span>
              ))}
            </div>
          </section>
        )}

        {rules.length > 0 && (
          <section className="policy-detail-section">
            <h2>Rules</h2>
            <div className="checks-list">
              {rules.map((rule, idx) => (
                <div key={rule.id || idx} className="check-item">
                  <div className="check-header">
                    <span className="check-type">{rule.severity || 'rule'}</span>
                    <span className="check-description">
                      {rule.id ? `${rule.id}: ` : ''}
                      {rule.title || rule.description}
                    </span>
                  </div>
                  {rule.description && rule.title && (
                    <p className="check-body">{rule.description}</p>
                  )}
                  {rule.guidelines && rule.guidelines.length > 0 && (
                    <ul>
                      {rule.guidelines.map((g, i) => (
                        <li key={i}>{g}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {checks.length > 0 && (
          <section className="policy-detail-section">
            <h2>Validation checks</h2>
            <div className="checks-list">
              {checks.map((check, index) => (
                <div key={index} className="check-item">
                  <div className="check-header">
                    <span className="check-type">{check.type || 'check'}</span>
                    <span className="check-description">{check.description}</span>
                  </div>
                  {check.pattern && (
                    <div className="check-detail">
                      <strong>Pattern:</strong> <code>{check.pattern}</code>
                    </div>
                  )}
                  {check.questions && check.questions.length > 0 && (
                    <div className="check-detail">
                      <strong>Questions:</strong>
                      <ul>
                        {check.questions.map((q, qIndex) => (
                          <li key={qIndex}>{q}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {Object.keys(remediation).length > 0 && (
          <section className="policy-detail-section">
            <h2>Remediation hints</h2>
            <div className="remediation-hints">
              {Object.entries(remediation).map(([key, value]) => (
                <div key={key} className="remediation-item">
                  <strong>{key}:</strong> {value}
                </div>
              ))}
            </div>
          </section>
        )}

        {markdown && (
          <section className="policy-detail-section">
            <h2>Content</h2>
            <pre className="policy-markdown">{markdown}</pre>
          </section>
        )}

        {!rules.length && !checks.length && !markdown && (
          <section className="policy-detail-section">
            <p className="chip-empty">No structured content on the active version.</p>
          </section>
        )}
      </div>
    </div>
  )
}
