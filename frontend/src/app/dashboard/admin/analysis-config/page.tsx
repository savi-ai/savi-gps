'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Settings2, Search, Plus, Save, Loader2 } from 'lucide-react'

interface AttributeDefinition {
  id: string
  key: string
  label: string
  category: string
  data_type: string
  extraction_hint?: string
  is_active: boolean
  use_in_assessment?: boolean
  assessment_weight?: number
  recommendation_template?: string | null
  remediation_scope?: 'simple_fix' | 'modernization' | 'either' | string
}

interface SearchResult {
  repository_name: string
  repository_full_name?: string
  attribute_key: string
  attribute_label: string
  value_text: string
  source_file?: string
  confidence: string
}

export default function AdminAnalysisConfigPage() {
  const router = useRouter()
  const { hasPermission } = useAuth()
  const [definitions, setDefinitions] = useState<AttributeDefinition[]>([])
  const [searchKey, setSearchKey] = useState('')
  const [searchValue, setSearchValue] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [newKey, setNewKey] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newHint, setNewHint] = useState('')
  const [newAssess, setNewAssess] = useState(true)
  const [message, setMessage] = useState<string | null>(null)

  const isAdmin = hasPermission('can_manage_tenant_config')

  const loadDefinitions = useCallback(async () => {
    const res = await apiClient.get('/api/v1/intelligence/analysis-config/definitions', {
      params: { active_only: false },
    })
    setDefinitions(res.data?.definitions || [])
  }, [])

  useEffect(() => {
    if (!isAdmin) {
      router.push('/dashboard')
      return
    }
    loadDefinitions().finally(() => setLoading(false))
  }, [isAdmin, router, loadDefinitions])

  const runSearch = async () => {
    const res = await apiClient.get('/api/v1/intelligence/analysis-config/search', {
      params: {
        attribute_key: searchKey || undefined,
        value_contains: searchValue || undefined,
      },
    })
    setResults(res.data?.results || [])
  }

  const addAttribute = async () => {
    if (!newKey || !newLabel) return
    setMessage(null)
    await apiClient.post('/api/v1/intelligence/analysis-config/definitions', {
      key: newKey,
      label: newLabel,
      extraction_hint: newHint || undefined,
      category: 'general',
      use_in_assessment: newAssess,
      assessment_weight: 2,
    })
    setNewKey('')
    setNewLabel('')
    setNewHint('')
    setNewAssess(true)
    await loadDefinitions()
    setMessage('Attribute created.')
  }

  const seedDefaults = async () => {
    setMessage(null)
    const res = await apiClient.post('/api/v1/intelligence/analysis-config/definitions/seed-defaults')
    await loadDefinitions()
    setMessage(`Seeded ${res.data?.created ?? 0} new default attributes (assessment flags backfilled where needed).`)
  }

  const saveDefinition = async (d: AttributeDefinition) => {
    setSavingId(d.id)
    setMessage(null)
    try {
      await apiClient.patch(`/api/v1/intelligence/analysis-config/definitions/${d.id}`, {
        label: d.label,
        extraction_hint: d.extraction_hint,
        category: d.category,
        is_active: d.is_active,
        use_in_assessment: d.use_in_assessment,
        assessment_weight: d.assessment_weight ?? 1,
        recommendation_template: d.recommendation_template || null,
        remediation_scope: d.remediation_scope || 'either',
      })
      setMessage(`Saved ${d.key}.`)
      await loadDefinitions()
    } finally {
      setSavingId(null)
    }
  }

  const updateLocal = (id: string, patch: Partial<AttributeDefinition>) => {
    setDefinitions((prev) => prev.map((d) => (d.id === id ? { ...d, ...patch } : d)))
  }

  if (loading) return <Skeleton className="h-48 w-full" />

  const assessmentCount = definitions.filter((d) => d.use_in_assessment && d.is_active).length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Settings2 className="h-6 w-6" />
          Analysis Configuration
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Define attributes extracted from code during indexing. Toggle{' '}
          <strong>Use in assessment</strong> and set <strong>Remediation scope</strong> so readiness
          can recommend a fix plan vs a modernize plan.
        </p>
      </div>

      {message && (
        <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">{message}</p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Attribute definitions</CardTitle>
          <CardDescription>
            Wiki Agent extracts these on index. {assessmentCount} active assessment signal
            {assessmentCount === 1 ? '' : 's'} configured.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={seedDefaults}>
              Seed / refresh defaults
            </Button>
          </div>
          <ul className="divide-y rounded-lg border">
            {definitions.map((d) => {
              const open = expandedId === d.id
              return (
                <li key={d.id} className="px-4 py-3">
                  <button
                    type="button"
                    className="flex w-full flex-col gap-1 text-left sm:flex-row sm:items-center sm:justify-between"
                    onClick={() => setExpandedId(open ? null : d.id)}
                  >
                    <div>
                      <span className="font-medium">{d.label}</span>
                      <code className="ml-2 text-xs text-muted-foreground">{d.key}</code>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Badge variant="outline">{d.category}</Badge>
                      {d.use_in_assessment && (
                        <Badge className="bg-amber-600 hover:bg-amber-600">Assessment</Badge>
                      )}
                      {d.use_in_assessment && d.remediation_scope && (
                        <Badge variant="outline" className="capitalize text-[10px]">
                          {d.remediation_scope === 'simple_fix'
                            ? 'Fix'
                            : d.remediation_scope === 'modernization'
                              ? 'Modernize'
                              : 'Either'}
                        </Badge>
                      )}
                      {!d.is_active && <Badge variant="secondary">inactive</Badge>}
                    </div>
                  </button>
                  {open && (
                    <div className="mt-3 grid gap-3 rounded-md border bg-muted/20 p-3 sm:grid-cols-2">
                      <div>
                        <Label>Label</Label>
                        <Input
                          value={d.label}
                          onChange={(e) => updateLocal(d.id, { label: e.target.value })}
                        />
                      </div>
                      <div>
                        <Label>Category</Label>
                        <Input
                          value={d.category}
                          onChange={(e) => updateLocal(d.id, { category: e.target.value })}
                        />
                      </div>
                      <div className="sm:col-span-2">
                        <Label>Extraction hint</Label>
                        <Input
                          value={d.extraction_hint || ''}
                          onChange={(e) => updateLocal(d.id, { extraction_hint: e.target.value })}
                        />
                      </div>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={Boolean(d.use_in_assessment)}
                          onChange={(e) =>
                            updateLocal(d.id, { use_in_assessment: e.target.checked })
                          }
                        />
                        Use in modernization assessment
                      </label>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={d.is_active}
                          onChange={(e) => updateLocal(d.id, { is_active: e.target.checked })}
                        />
                        Active
                      </label>
                      <div>
                        <Label>Assessment weight (1–5)</Label>
                        <Input
                          type="number"
                          min={1}
                          max={5}
                          value={d.assessment_weight ?? 1}
                          onChange={(e) =>
                            updateLocal(d.id, {
                              assessment_weight: Math.min(
                                5,
                                Math.max(1, Number(e.target.value) || 1)
                              ),
                            })
                          }
                        />
                      </div>
                      <div>
                        <Label>Remediation scope</Label>
                        <select
                          className="mt-1 flex h-9 w-full rounded-md border bg-background px-3 text-sm"
                          value={d.remediation_scope || 'either'}
                          onChange={(e) =>
                            updateLocal(d.id, { remediation_scope: e.target.value })
                          }
                          disabled={!d.use_in_assessment}
                        >
                          <option value="simple_fix">Simple fix (same-repo PR)</option>
                          <option value="modernization">Modernization theme</option>
                          <option value="either">Either</option>
                        </select>
                      </div>
                      <div className="sm:col-span-2">
                        <Label>Recommendation when warn/bad</Label>
                        <Input
                          value={d.recommendation_template || ''}
                          onChange={(e) =>
                            updateLocal(d.id, { recommendation_template: e.target.value })
                          }
                          placeholder="What should the plan recommend?"
                        />
                      </div>
                      <Button
                        className="w-fit"
                        size="sm"
                        disabled={savingId === d.id}
                        onClick={() => saveDefinition(d)}
                      >
                        {savingId === d.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Save className="h-4 w-4" />
                        )}
                        Save
                      </Button>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
          <div className="grid gap-3 rounded-lg border bg-muted/20 p-4 sm:grid-cols-3">
            <div>
              <Label htmlFor="newKey">Key</Label>
              <Input
                id="newKey"
                placeholder="java_version"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="newLabel">Label</Label>
              <Input
                id="newLabel"
                placeholder="Java Version"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="newHint">Extraction hint</Label>
              <Input
                id="newHint"
                placeholder="FROM line in Dockerfile"
                value={newHint}
                onChange={(e) => setNewHint(e.target.value)}
              />
            </div>
            <label className="flex items-center gap-2 text-sm sm:col-span-3">
              <input
                type="checkbox"
                checked={newAssess}
                onChange={(e) => setNewAssess(e.target.checked)}
              />
              Use in modernization assessment
            </label>
            <Button className="w-fit sm:col-span-3" onClick={addAttribute}>
              <Plus className="h-4 w-4" />
              Add attribute
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Search className="h-4 w-4" />
            Fleet search
          </CardTitle>
          <CardDescription>Find repositories by extracted attribute values.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Input
              placeholder="Attribute key (e.g. java_version)"
              value={searchKey}
              onChange={(e) => setSearchKey(e.target.value)}
              className="max-w-xs"
            />
            <Input
              placeholder="Value contains…"
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              className="max-w-xs"
            />
            <Button onClick={runSearch}>Search</Button>
          </div>
          {results.length > 0 && (
            <ul className="divide-y rounded-lg border text-sm">
              {results.map((r, i) => (
                <li key={i} className="px-4 py-3">
                  <div className="font-medium">{r.repository_full_name || r.repository_name}</div>
                  <div className="text-muted-foreground">
                    {r.attribute_label}: <strong>{r.value_text}</strong>
                    {r.source_file && (
                      <>
                        {' '}
                        — <code>{r.source_file}</code>
                      </>
                    )}
                    <Badge variant="outline" className="ml-2">
                      {r.confidence}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
