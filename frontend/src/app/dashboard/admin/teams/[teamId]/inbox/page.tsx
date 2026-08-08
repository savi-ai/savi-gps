'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, GitPullRequest, Loader2, Play, Plus, RefreshCw, Bot, MessageSquare } from 'lucide-react'

interface SaviInstance {
  id: string
  name: string
  slug: string
  status: string
}

interface ContextPack {
  brief_markdown?: string
  repositories?: Array<{ id: string; name: string; url?: string; role?: string }>
  extra_repositories?: Array<{ id: string; name: string }>
  human_refs?: Array<{
    type: string
    label?: string | null
    value: string
    fetch_status?: string
  }>
  assembled_at?: string
}

interface WorkItem {
  id: string
  title: string
  description?: string | null
  state: string
  priority?: number | null
  awaiting_priority: boolean
  ready_questions: Array<{ id: string; prompt: string }>
  application_id?: string | null
  application_name?: string | null
  assigned_by?: { username: string; full_name?: string | null } | null
  source: string
  pr_url?: string | null
  pr_number?: number | null
  orchestrator_phase?: string | null
  orchestrator_timeline?: Array<{
    phase: string
    at: string
    detail: string
    tokens?: number
  }>
  orchestrator_tokens?: number
  orchestrator_error?: string | null
  context_refs?: {
    refs?: Array<{ type: string; label?: string | null; value: string }>
    extra_repository_ids?: string[]
  }
  context_pack?: ContextPack | null
}

interface AppOption {
  id: string
  name: string
}

interface RepoOption {
  id: string
  name: string
  application_id: string
}

function stateVariant(state: string): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (state === 'in_progress') return 'default'
  if (state === 'needs_info' || state === 'blocked') return 'destructive'
  if (state === 'queued') return 'secondary'
  return 'outline'
}

function errDetail(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    return (
      (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
      fallback
    )
  }
  return fallback
}

export default function TeamSaviInboxPage() {
  const params = useParams()
  const teamId = String(params.teamId || '')
  const router = useRouter()
  const { hasPermission, hasRole } = useAuth()

  const [teamName, setTeamName] = useState('')
  const [savi, setSavi] = useState<SaviInstance | null>(null)
  const [items, setItems] = useState<WorkItem[]>([])
  const [apps, setApps] = useState<AppOption[]>([])
  const [repos, setRepos] = useState<RepoOption[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [applicationId, setApplicationId] = useState('')
  const [extraNotes, setExtraNotes] = useState('')
  const [extraUrls, setExtraUrls] = useState('')
  const [extraRepoIds, setExtraRepoIds] = useState<string[]>([])
  const [answers, setAnswers] = useState<Record<string, Record<string, string>>>({})
  const [priorities, setPriorities] = useState<Record<string, string>>({})

  const canAccess =
    hasPermission('can_manage_teams') ||
    hasPermission('can_manage_tenant_config') ||
    hasRole('admin') ||
    hasRole('developer')

  const load = useCallback(async () => {
    const teamRes = await apiClient.get(`/api/v1/teams/${teamId}`)
    setTeamName(teamRes.data.name || 'Team')
    const active =
      (teamRes.data.savi_instances || []).find(
        (s: SaviInstance) => s.status === 'active'
      ) || (teamRes.data.savi_instances || [])[0]
    setSavi(active || null)
    if (active) {
      const workRes = await apiClient.get(
        `/api/v1/teams/${teamId}/savi/${active.id}/work`
      )
      setItems(workRes.data.work_items || [])
    } else {
      setItems([])
    }
    const teamApps: AppOption[] = (teamRes.data.applications || []).map(
      (a: AppOption) => ({ id: a.id, name: a.name })
    )
    setApps(teamApps)

    const repoOpts: RepoOption[] = []
    await Promise.all(
      teamApps.map(async (a) => {
        try {
          const detail = await apiClient.get(
            `/api/v1/intelligence/applications/${a.id}`
          )
          for (const r of detail.data.repositories || []) {
            repoOpts.push({
              id: r.id,
              name: r.github_full_name || r.name,
              application_id: a.id,
            })
          }
        } catch {
          /* ignore per-app failures */
        }
      })
    )
    setRepos(repoOpts)
  }, [teamId])

  useEffect(() => {
    if (!canAccess) {
      router.push('/dashboard')
      return
    }
    ;(async () => {
      try {
        setLoading(true)
        setError(null)
        await load()
      } catch {
        setError('Failed to load Savi inbox')
      } finally {
        setLoading(false)
      }
    })()
  }, [canAccess, router, load])

  const awaitingPriority = useMemo(
    () => items.filter((i) => i.awaiting_priority),
    [items]
  )
  const needsInfo = useMemo(
    () => items.filter((i) => i.state === 'needs_info'),
    [items]
  )

  const selectableExtraRepos = useMemo(() => {
    if (!applicationId) return repos
    return repos.filter((r) => r.application_id !== applicationId)
  }, [repos, applicationId])

  const buildContextPayload = () => {
    const context_refs: Array<{ type: string; label?: string; value: string }> = []
    if (extraNotes.trim()) {
      context_refs.push({
        type: 'jira_text',
        label: 'Pasted story / notes',
        value: extraNotes.trim(),
      })
    }
    for (const line of extraUrls.split('\n')) {
      const url = line.trim()
      if (url) {
        context_refs.push({ type: 'url', label: 'Doc URL', value: url })
      }
    }
    return {
      context_refs: context_refs.length ? context_refs : undefined,
      extra_repository_ids: extraRepoIds.length ? extraRepoIds : undefined,
    }
  }

  const enqueue = async () => {
    if (!savi || !title.trim()) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/teams/${teamId}/savi/${savi.id}/work`, {
        title: title.trim(),
        description: description.trim() || undefined,
        application_id: applicationId || undefined,
        ...buildContextPayload(),
      })
      setTitle('')
      setDescription('')
      setApplicationId('')
      setExtraNotes('')
      setExtraUrls('')
      setExtraRepoIds([])
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to enqueue work'))
    } finally {
      setSaving(false)
    }
  }

  const submitAnswers = async (itemId: string) => {
    if (!savi) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(
        `/api/v1/teams/${teamId}/savi/${savi.id}/work/${itemId}/answer`,
        { answers: answers[itemId] || {} }
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to submit answers'))
    } finally {
      setSaving(false)
    }
  }

  const submitPriority = async (itemId: string) => {
    if (!savi) return
    const p = parseInt(priorities[itemId] || '', 10)
    if (!p || p < 1 || p > 100) {
      setError('Priority must be 1–100 (1 = highest)')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(
        `/api/v1/teams/${teamId}/savi/${savi.id}/work/${itemId}/priority`,
        { priority: p }
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to set priority'))
    } finally {
      setSaving(false)
    }
  }

  const startNext = async () => {
    if (!savi) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/teams/${teamId}/savi/${savi.id}/work/start-next`)
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to start next item'))
    } finally {
      setSaving(false)
    }
  }

  const transition = async (itemId: string, state: string) => {
    if (!savi) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(
        `/api/v1/teams/${teamId}/savi/${savi.id}/work/${itemId}/transition`,
        { state }
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to update state'))
    } finally {
      setSaving(false)
    }
  }

  const reassemble = async (itemId: string) => {
    if (!savi) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(
        `/api/v1/teams/${teamId}/savi/${savi.id}/work/${itemId}/assemble-context`
      )
      setExpandedId(itemId)
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to assemble context'))
    } finally {
      setSaving(false)
    }
  }

  const openPr = async (item: WorkItem) => {
    if (!savi) return
    const repos = [
      ...(item.context_pack?.repositories || []),
      ...(item.context_pack?.extra_repositories || []),
    ]
    const repositoryId = repos[0]?.id
    if (!repositoryId) {
      setError('No repository in context pack — assemble context first')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(
        `/api/v1/teams/${teamId}/savi/${savi.id}/work/${item.id}/open-pr`,
        { repository_id: repositoryId }
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to open PR'))
    } finally {
      setSaving(false)
    }
  }

  const runOrchestrator = async (itemId: string) => {
    if (!savi) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(
        `/api/v1/teams/${teamId}/savi/${savi.id}/work/${itemId}/orchestrate`,
        { background: true }
      )
      setExpandedId(itemId)
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Orchestrator failed'))
    } finally {
      setSaving(false)
    }
  }

  const pollFeedback = async (itemId: string) => {
    if (!savi) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(
        `/api/v1/teams/${teamId}/savi/${savi.id}/work/${itemId}/poll-feedback`,
        { iterate: true }
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Feedback poll failed'))
    } finally {
      setSaving(false)
    }
  }

  const toggleExtraRepo = (repoId: string) => {
    setExtraRepoIds((prev) =>
      prev.includes(repoId) ? prev.filter((id) => id !== repoId) : [...prev, repoId]
    )
  }

  if (!canAccess) return null

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link
            href="/dashboard/admin/teams"
            className="mb-2 inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" />
            Teams
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">
            {teamName ? `${teamName} · Savi inbox` : 'Savi inbox'}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Portal assign + context. Connectors:{' '}
            <Link
              href={`/dashboard/admin/teams/${teamId}/connectors`}
              className="underline"
            >
              configure GitHub / Jira / Slack / Confluence
            </Link>
            .
          </p>
        </div>
        {savi && (
          <Button variant="outline" onClick={startNext} disabled={saving}>
            <Play className="mr-1.5 h-3.5 w-3.5" />
            Start next
          </Button>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <Skeleton className="h-40 w-full" />
      ) : !savi ? (
        <Card>
          <CardContent className="py-8 text-sm text-muted-foreground">
            No Savi rostered on this team.{' '}
            <Link href="/dashboard/admin/teams" className="underline">
              Roster one in Admin → Teams
            </Link>
            .
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Enqueue work</CardTitle>
              <CardDescription>
                Assign to {savi.name} ({savi.slug}) · status {savi.status}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div>
                <Label htmlFor="title">Title</Label>
                <Input
                  id="title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Short summary"
                  disabled={saving || savi.status !== 'active'}
                />
              </div>
              <div>
                <Label htmlFor="app">Application</Label>
                <select
                  id="app"
                  className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
                  value={applicationId}
                  onChange={(e) => setApplicationId(e.target.value)}
                  disabled={saving}
                >
                  <option value="">Select application…</option>
                  {apps.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label htmlFor="desc">Description</Label>
                <textarea
                  id="desc"
                  className="mt-1 min-h-[100px] w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Include acceptance criteria (and repro steps for bugs)."
                  disabled={saving}
                />
              </div>
              <div className="rounded-md border p-3 space-y-3">
                <p className="text-xs font-medium text-muted-foreground">
                  Extra context (portal until T5 connectors)
                </p>
                <div>
                  <Label htmlFor="notes" className="text-xs">
                    Pasted Jira / story text
                  </Label>
                  <textarea
                    id="notes"
                    className="mt-1 min-h-[72px] w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={extraNotes}
                    onChange={(e) => setExtraNotes(e.target.value)}
                    placeholder="Paste ticket body or notes…"
                    disabled={saving}
                  />
                </div>
                <div>
                  <Label htmlFor="urls" className="text-xs">
                    Doc URLs (one per line — Confluence etc.; fetch pending T5)
                  </Label>
                  <textarea
                    id="urls"
                    className="mt-1 min-h-[56px] w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={extraUrls}
                    onChange={(e) => setExtraUrls(e.target.value)}
                    placeholder="https://confluence.example.com/…"
                    disabled={saving}
                  />
                </div>
                {selectableExtraRepos.length > 0 && (
                  <div>
                    <Label className="text-xs">
                      Extra team repos (dependencies / API specs)
                    </Label>
                    <ul className="mt-1 max-h-32 overflow-y-auto rounded-md border divide-y">
                      {selectableExtraRepos.map((r) => (
                        <li key={r.id} className="flex items-center gap-2 px-2 py-1.5 text-sm">
                          <input
                            type="checkbox"
                            checked={extraRepoIds.includes(r.id)}
                            onChange={() => toggleExtraRepo(r.id)}
                            disabled={saving}
                          />
                          <span className="truncate">{r.name}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              <Button
                onClick={enqueue}
                disabled={saving || !title.trim() || savi.status !== 'active'}
              >
                {saving ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="mr-1.5 h-4 w-4" />
                )}
                Enqueue
              </Button>
            </CardContent>
          </Card>

          <div className="space-y-4">
            {(awaitingPriority.length > 0 || needsInfo.length > 0) && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Needs attention</CardTitle>
                  <CardDescription>
                    Ready-check questions or priority before coding starts
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {needsInfo.map((item) => (
                    <div key={item.id} className="rounded-md border p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium">{item.title}</p>
                        <Badge variant="destructive">needs info</Badge>
                      </div>
                      {(item.ready_questions || []).map((q) => (
                        <div key={q.id}>
                          <Label className="text-xs">{q.prompt}</Label>
                          <Input
                            className="mt-1"
                            value={answers[item.id]?.[q.id] || ''}
                            onChange={(e) =>
                              setAnswers((prev) => ({
                                ...prev,
                                [item.id]: {
                                  ...(prev[item.id] || {}),
                                  [q.id]: e.target.value,
                                },
                              }))
                            }
                          />
                        </div>
                      ))}
                      <Button
                        size="sm"
                        onClick={() => submitAnswers(item.id)}
                        disabled={saving}
                      >
                        Submit answers
                      </Button>
                    </div>
                  ))}
                  {awaitingPriority.map((item) => (
                    <div key={item.id} className="rounded-md border p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium">{item.title}</p>
                        <Badge variant="outline">awaiting priority</Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Other work is already on this Savi&apos;s queue. Set priority
                        (1 = highest).
                      </p>
                      <div className="flex gap-2">
                        <Input
                          type="number"
                          min={1}
                          max={100}
                          placeholder="Priority 1–100"
                          value={priorities[item.id] || ''}
                          onChange={(e) =>
                            setPriorities((prev) => ({
                              ...prev,
                              [item.id]: e.target.value,
                            }))
                          }
                        />
                        <Button
                          size="sm"
                          onClick={() => submitPriority(item.id)}
                          disabled={saving}
                        >
                          Set
                        </Button>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Queue</CardTitle>
                <CardDescription>
                  {items.length} open item{items.length === 1 ? '' : 's'} on this Savi
                </CardDescription>
              </CardHeader>
              <CardContent>
                {items.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Queue is empty.</p>
                ) : (
                  <ul className="divide-y rounded-md border">
                    {items.map((item) => (
                      <li key={item.id} className="space-y-2 px-3 py-3">
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <p className="text-sm font-medium">{item.title}</p>
                            <p className="text-xs text-muted-foreground">
                              {item.application_name || 'No app'}
                              {item.assigned_by && (
                                <>
                                  {' '}
                                  ·{' '}
                                  {item.assigned_by.full_name ||
                                    item.assigned_by.username}
                                </>
                              )}
                              {item.priority != null && <> · P{item.priority}</>}
                              {item.context_pack && <> · context packed</>}
                              {item.orchestrator_phase && (
                                <> · orch:{item.orchestrator_phase}</>
                              )}
                            </p>
                          </div>
                          <Badge variant={stateVariant(item.state)} className="capitalize">
                            {item.state.replace('_', ' ')}
                          </Badge>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {(item.state === 'queued' ||
                            item.state === 'in_progress' ||
                            item.state === 'in_review') &&
                            item.application_id && (
                              <Button
                                size="sm"
                                onClick={() => runOrchestrator(item.id)}
                                disabled={saving}
                              >
                                <Bot className="mr-1 h-3.5 w-3.5" />
                                Run orchestrator
                              </Button>
                            )}
                          {item.pr_url && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => pollFeedback(item.id)}
                              disabled={saving}
                            >
                              <MessageSquare className="mr-1 h-3.5 w-3.5" />
                              Poll feedback
                            </Button>
                          )}
                          {item.application_id && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => reassemble(item.id)}
                              disabled={saving}
                            >
                              <RefreshCw className="mr-1 h-3.5 w-3.5" />
                              Re-assemble context
                            </Button>
                          )}
                          {item.context_pack && !item.pr_url && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => openPr(item)}
                              disabled={saving}
                            >
                              <GitPullRequest className="mr-1 h-3.5 w-3.5" />
                              Open PR
                            </Button>
                          )}
                          {item.pr_url && (
                            <a
                              href={item.pr_url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center text-xs text-primary underline"
                            >
                              PR #{item.pr_number}
                            </a>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              setExpandedId((id) => (id === item.id ? null : item.id))
                            }
                          >
                            {expandedId === item.id ? 'Hide brief' : 'Show brief'}
                          </Button>
                          {item.state === 'in_progress' && (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => transition(item.id, 'in_review')}
                                disabled={saving}
                              >
                                Mark in review
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => transition(item.id, 'done')}
                                disabled={saving}
                              >
                                Done
                              </Button>
                            </>
                          )}
                          {item.state === 'queued' && (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="text-destructive"
                              onClick={() => transition(item.id, 'cancelled')}
                              disabled={saving}
                            >
                              Cancel
                            </Button>
                          )}
                        </div>
                        {expandedId === item.id && (
                          <div className="rounded-md bg-muted/40 p-3 text-xs space-y-2">
                            {item.orchestrator_error && (
                              <p className="text-destructive">{item.orchestrator_error}</p>
                            )}
                            {(item.orchestrator_timeline || []).length > 0 && (
                              <div>
                                <p className="font-medium mb-1">
                                  Orchestrator timeline
                                  {item.orchestrator_tokens
                                    ? ` · ~${item.orchestrator_tokens} tokens`
                                    : ''}
                                </p>
                                <ul className="space-y-1">
                                  {(item.orchestrator_timeline || []).map((t, idx) => (
                                    <li key={idx}>
                                      <span className="font-medium">{t.phase}</span> —{' '}
                                      {t.detail}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {!item.context_pack ? (
                              <p className="text-muted-foreground">
                                No context pack yet. Queue the item (ready) or click
                                Re-assemble.
                              </p>
                            ) : (
                              <>
                                {(item.context_pack.human_refs || []).length > 0 && (
                                  <div>
                                    <p className="font-medium mb-1">Human refs</p>
                                    <ul className="list-disc pl-4 space-y-0.5">
                                      {(item.context_pack.human_refs || []).map(
                                        (ref, idx) => (
                                          <li key={idx}>
                                            {ref.label || ref.type}: {ref.value}
                                            {ref.fetch_status && (
                                              <span className="text-muted-foreground">
                                                {' '}
                                                ({ref.fetch_status})
                                              </span>
                                            )}
                                          </li>
                                        )
                                      )}
                                    </ul>
                                  </div>
                                )}
                                <pre className="max-h-64 overflow-auto whitespace-pre-wrap font-sans text-xs leading-relaxed">
                                  {item.context_pack.brief_markdown || '(empty brief)'}
                                </pre>
                              </>
                            )}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
