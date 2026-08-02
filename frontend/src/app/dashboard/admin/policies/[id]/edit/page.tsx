'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { ArrowLeft } from 'lucide-react'
import '../../policies.css'

const CATEGORIES = [
  'ideation',
  'requirements',
  'stories',
  'architecture',
  'coding',
  'testing',
  'security',
  'performance',
  'modernize',
  'infra',
  'ci_cd',
  'building_blocks',
]

interface PolicyMeta {
  id: string
  policy_id: string
  name: string
  description: string | null
  category: string
  status: string
  applies_to: string[] | null
  tags: string[] | null
  active_version_id: string | null
}

interface PolicyVersion {
  id: string
  version_number: string
  content: Record<string, unknown> | null
  is_draft: boolean
}

export default function PolicyEditPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const { hasPermission } = useAuth()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('modernize')
  const [appliesTo, setAppliesTo] = useState('')
  const [tags, setTags] = useState('')
  const [contentJson, setContentJson] = useState('{\n  "rules": []\n}')
  const [policyKey, setPolicyKey] = useState('')

  useEffect(() => {
    if (!hasPermission('can_manage_policies')) {
      router.push('/dashboard')
      return
    }
    if (!id) return
    ;(async () => {
      try {
        setLoading(true)
        setError(null)
        const [metaRes, versionsRes] = await Promise.all([
          apiClient.get(`/api/v1/policies/${id}`),
          apiClient.get(`/api/v1/policies/${id}/versions`),
        ])
        const meta = metaRes.data as PolicyMeta
        const versions = (versionsRes.data || []) as PolicyVersion[]
        const active =
          versions.find((v) => v.id === meta.active_version_id) || versions[0] || null

        setPolicyKey(meta.policy_id)
        setName(meta.name || '')
        setDescription(meta.description || '')
        setCategory(meta.category || 'modernize')
        setAppliesTo((meta.applies_to || []).join(', '))
        setTags((meta.tags || []).join(', '))
        setContentJson(JSON.stringify(active?.content || { rules: [] }, null, 2))
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Failed to load policy')
      } finally {
        setLoading(false)
      }
    })()
  }, [id, hasPermission, router])

  const parseList = (raw: string) =>
    raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

  const handleSave = async (publish: boolean) => {
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      let content: Record<string, unknown>
      try {
        content = JSON.parse(contentJson)
      } catch {
        setError('Content must be valid JSON')
        setSaving(false)
        return
      }

      await apiClient.put(`/api/v1/policies/${id}`, {
        name,
        description,
        category,
        applies_to: parseList(appliesTo),
        tags: parseList(tags),
        content,
      })

      if (publish) {
        const versionsRes = await apiClient.get(`/api/v1/policies/${id}/versions`)
        const versions = (versionsRes.data || []) as PolicyVersion[]
        const draft = versions.find((v) => v.is_draft) || versions[0]
        if (draft) {
          await apiClient.post(`/api/v1/policies/${id}/publish`, null, {
            params: { version_id: draft.id },
          })
        }
        setSuccess('Saved and published. Re-run assessments to apply new rules.')
      } else {
        setSuccess('Saved as draft. Publish to make it active for assessments.')
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save policy')
    } finally {
      setSaving(false)
    }
  }

  if (!hasPermission('can_manage_policies')) return null

  if (loading) {
    return (
      <div className="policies-page">
        <div className="loading-state">Loading policy...</div>
      </div>
    )
  }

  return (
    <div className="policies-page">
      <div className="policies-header">
        <div>
          <button
            className="btn-secondary back-btn"
            onClick={() => router.push(`/dashboard/admin/policies/${id}`)}
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </button>
          <h1 className="policies-title" style={{ marginTop: '0.75rem' }}>
            Edit policy
          </h1>
          <p className="policies-header-sub">
            {policyKey} — metadata and JSON content (rules for modernize readiness live under{' '}
            <code>content.rules</code>).
          </p>
        </div>
      </div>

      <div className="policy-detail-card">
        <div className="policy-form">
          <div>
            <label>Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label>Description</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div>
            <label>Category</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label>Applies to (comma-separated)</label>
            <input
              value={appliesTo}
              onChange={(e) => setAppliesTo(e.target.value)}
              placeholder="backend, architecture"
            />
          </div>
          <div>
            <label>Tags (comma-separated)</label>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="modernize-readiness, sop"
            />
          </div>
          <div>
            <label>Content JSON</label>
            <textarea
              value={contentJson}
              onChange={(e) => setContentJson(e.target.value)}
              spellCheck={false}
            />
            <p className="policy-form-hint">
              Modernize example rule: {'{"id":"min_java_17","signal":"runtime","op":"runtime_min_java","value":17}'}
            </p>
          </div>

          {error && <p className="form-error">{error}</p>}
          {success && <p className="form-success">{success}</p>}

          <div className="policy-form-actions">
            <button
              className="btn-secondary"
              disabled={saving}
              onClick={() => handleSave(false)}
            >
              {saving ? 'Saving…' : 'Save draft'}
            </button>
            <button
              className="btn-primary"
              disabled={saving}
              onClick={() => handleSave(true)}
            >
              {saving ? 'Saving…' : 'Save & publish'}
            </button>
            <button
              className="btn-secondary"
              onClick={() => router.push('/dashboard/admin/policies')}
            >
              Catalog
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
