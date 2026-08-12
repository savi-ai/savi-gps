'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Label } from '@/components/ui/label'
import PillarBreadcrumb from '@/components/navigation/PillarBreadcrumb'
import { WikiChatPanel } from '@/components/intelligence/WikiChatPanel'
import { WikiMarkdownContent } from '@/components/intelligence/WikiMarkdownContent'
import ApplicationReadinessPanel from '@/components/modernize/ApplicationReadinessPanel'
import ReadinessPanel from '@/components/modernize/ReadinessPanel'
import {
  Plus,
  Trash2,
  Rocket,
  FolderKanban,
  ClipboardList,
  GitBranch,
  BookOpen,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { ServiceMapPanel } from '@/components/intelligence/ServiceMapPanel'
import {
  ApplicationWikiGenerateDialog,
  type MemberReadinessSummary,
} from '@/components/intelligence/ApplicationWikiGenerateDialog'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { cn } from '@/lib/utils'

const REPO_ROLES = ['backend', 'frontend', 'api', 'worker', 'infra', 'library', 'other']
const TABS = ['repositories', 'dependencies', 'chat', 'wiki', 'readiness', 'plans', 'projects'] as const
type TabId = (typeof TABS)[number]

interface AppRepository {
  id: string
  name: string
  github_full_name?: string
  status: string
  role?: string | null
}

interface ReadinessRow {
  repository_id: string
  repository_name: string
  role?: string | null
  indexed: boolean
  overall_score: number | null
  readiness_level: string | null
  status: string
}

interface HubPlan {
  id: string
  title: string
  state: string
  repository_id: string
  repository_name?: string
  spawned_project_id?: string | null
}

interface HubProject {
  id: string
  name: string
  pillar: string
  mode?: string | null
  current_step: string
  source_plan_id?: string | null
  source_application_id?: string | null
  target_application_id?: string | null
}

interface ApplicationHub {
  id: string
  name: string
  description?: string | null
  domain?: string | null
  origin?: string | null
  repository_count: number
  repositories: AppRepository[]
  hub: {
    indexed_pct: number
    aggregate_readiness_level: string | null
    aggregate_readiness_score: number | null
    readiness: ReadinessRow[]
    plans: HubPlan[]
    projects: HubProject[]
    active_plan_count: number
    active_project_count: number
  }
}

interface RepositoryOption {
  id: string
  name: string
  github_full_name?: string
  application?: { id: string; name: string } | null
}

const LEVEL_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  high: 'default',
  medium: 'secondary',
  low: 'destructive',
}

export default function ApplicationDetailPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { hasCapability, hasPermission } = useAuth()
  const appId = params?.id as string
  const initialTab = (searchParams.get('tab') as TabId) || 'repositories'
  const [tab, setTab] = useState<TabId>(TABS.includes(initialTab) ? initialTab : 'repositories')
  const [app, setApp] = useState<ApplicationHub | null>(null)
  const [allRepos, setAllRepos] = useState<RepositoryOption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [addRepoId, setAddRepoId] = useState('')
  const [addRole, setAddRole] = useState('backend')
  const [saving, setSaving] = useState(false)
  const [readinessRepoId, setReadinessRepoId] = useState<string | null>(null)
  const [wikiMarkdown, setWikiMarkdown] = useState<string | null>(null)
  const [wikiLoading, setWikiLoading] = useState(false)
  const [wikiSource, setWikiSource] = useState<string | null>(null)
  const [wikiStatus, setWikiStatus] = useState<string | null>(null)
  const [wikiGenerating, setWikiGenerating] = useState(false)
  const [wikiCancelling, setWikiCancelling] = useState(false)
  const [wikiGenerateOpen, setWikiGenerateOpen] = useState(false)
  const [wikiBanner, setWikiBanner] = useState<string | null>(null)
  const [memberReadiness, setMemberReadiness] = useState<MemberReadinessSummary | null>(null)
  const [creatingPlans, setCreatingPlans] = useState(false)
  const [planMessage, setPlanMessage] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<
    { type: 'remove-repo'; repositoryId: string } | { type: 'delete-app' } | null
  >(null)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      const [appRes, reposRes] = await Promise.all([
        apiClient.get(`/api/v1/intelligence/applications/${appId}`, { params: { hub: true } }),
        apiClient.get('/api/v1/intelligence/repos'),
      ])
      setApp(appRes.data)
      setAllRepos(reposRes.data?.repositories || [])
      setReadinessRepoId((prev) => prev || appRes.data?.repositories?.[0]?.id || null)
      setError(null)
    } catch {
      setApp(null)
      setError('Application not found')
    } finally {
      setLoading(false)
    }
  }, [appId])

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    load()
  }, [hasCapability, router, load])

  const refreshWikiStatus = useCallback(async () => {
    const [wikiRes, statusRes] = await Promise.all([
      apiClient.get(`/api/v1/intelligence/applications/${appId}/wiki`).catch(() => null),
      apiClient.get(`/api/v1/intelligence/applications/${appId}/wiki/status`).catch(() => null),
    ])
    if (wikiRes?.data) {
      setWikiMarkdown(wikiRes.data.markdown || '')
      setWikiSource(wikiRes.data.source || null)
    }
    const st = statusRes?.data?.status || wikiRes?.data?.status?.status || null
    setWikiStatus(st)
    setMemberReadiness(statusRes?.data?.member_readiness || null)
    return st
  }, [appId])

  useEffect(() => {
    if (tab !== 'wiki' || !appId) return
    let cancelled = false
    const loadWiki = async () => {
      setWikiLoading(true)
      try {
        await refreshWikiStatus()
      } catch {
        if (!cancelled) {
          setWikiMarkdown(null)
          setWikiSource(null)
        }
      } finally {
        if (!cancelled) setWikiLoading(false)
      }
    }
    loadWiki()
    return () => {
      cancelled = true
    }
  }, [tab, appId, refreshWikiStatus])

  useEffect(() => {
    if (tab !== 'wiki' || wikiStatus !== 'running') return
    const t = setInterval(() => {
      void refreshWikiStatus()
    }, 4000)
    return () => clearInterval(t)
  }, [tab, wikiStatus, refreshWikiStatus])

  const pollAppWikiUntilDone = async () => {
    setWikiStatus('running')
    for (let i = 0; i < 90; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      const st = await refreshWikiStatus()
      if (st === 'completed' || st === 'failed') break
    }
  }

  const onWikiGenerateCompleted = async (result: {
    deferred?: boolean
    message?: string
  }) => {
    setWikiBanner(result.message || null)
    if (result.deferred) {
      setWikiStatus(null)
      await load()
      const statusRes = await apiClient
        .get(`/api/v1/intelligence/applications/${appId}/wiki/status`)
        .catch(() => null)
      setMemberReadiness(statusRes?.data?.member_readiness || null)
      return
    }
    setWikiGenerating(true)
    try {
      await pollAppWikiUntilDone()
    } catch {
      setWikiStatus('failed')
    } finally {
      setWikiGenerating(false)
    }
  }

  const cancelAppWiki = async () => {
    if (!appId) return
    setWikiCancelling(true)
    try {
      await apiClient.post(`/api/v1/intelligence/applications/${appId}/wiki/cancel`)
      await refreshWikiStatus()
      setWikiBanner('Application wiki cancelled. You can Generate again (uses API, not Copilot CLI).')
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setWikiBanner(detail || 'Failed to cancel application wiki')
    } finally {
      setWikiCancelling(false)
    }
  }

  if (!hasPermission('can_use_intelligence')) return null

  const unassignedRepos = allRepos.filter((r) => !r.application || r.application.id === appId)
  const availableToAdd = unassignedRepos.filter(
    (r) => !app?.repositories.some((member) => member.id === r.id)
  )

  const addRepository = async () => {
    if (!addRepoId) return
    setSaving(true)
    try {
      await apiClient.post(`/api/v1/intelligence/applications/${appId}/repositories`, {
        repository_id: addRepoId,
        role: addRole,
      })
      setAddRepoId('')
      await load()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to add repository')
    } finally {
      setSaving(false)
    }
  }

  const removeRepository = async (repositoryId: string) => {
    setSaving(true)
    try {
      await apiClient.delete(
        `/api/v1/intelligence/applications/${appId}/repositories/${repositoryId}`
      )
      await load()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to remove repository')
    } finally {
      setSaving(false)
      setConfirmAction(null)
    }
  }

  const deleteApplication = async () => {
    if (!app) return
    await apiClient.delete(`/api/v1/intelligence/applications/${appId}`)
    router.push('/dashboard/intelligence/applications')
  }

  const createApplicationPlans = async () => {
    if (!hasCapability('modernize') || !hasPermission('can_manage_modernize')) return
    setCreatingPlans(true)
    setPlanMessage(null)
    try {
      const res = await apiClient.post(`/api/v1/modernize/applications/${appId}/plans`, {
        title: `Modernize ${app?.name}`,
        skip_existing: true,
      })
      setPlanMessage(
        `Created ${res.data.plans?.length || 0} plan(s)` +
          (res.data.skipped?.length ? ` · skipped ${res.data.skipped.length}` : '')
      )
      await load()
      setTab('plans')
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setPlanMessage(detail || 'Failed to create plans')
    } finally {
      setCreatingPlans(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (!app) {
    return <p className="text-sm text-destructive">{error || 'Not found'}</p>
  }

  const hub = app.hub
  const readyRepo = app.repositories.find((r) => r.status === 'ready')

  return (
    <div className="space-y-6">
      <PillarBreadcrumb
        items={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Applications', href: '/dashboard/intelligence/applications' },
          { label: app.name },
        ]}
      />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{app.name}</h1>
          {app.domain && (
            <p className="mt-1 text-sm capitalize text-muted-foreground">{app.domain}</p>
          )}
          {app.description && (
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{app.description}</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {app.origin && (
              <Badge variant="outline" className="capitalize">
                {app.origin}
              </Badge>
            )}
            <Badge variant="outline">
              <GitBranch className="mr-1 h-3 w-3" />
              {app.repository_count} repos · {hub.indexed_pct}% indexed
            </Badge>
            {hub.aggregate_readiness_level && (
              <Badge variant={LEVEL_VARIANT[hub.aggregate_readiness_level] || 'outline'} className="capitalize">
                Readiness: {hub.aggregate_readiness_level}
              </Badge>
            )}
            {hub.active_plan_count > 0 && (
              <Badge variant="secondary">{hub.active_plan_count} active plan{hub.active_plan_count !== 1 ? 's' : ''}</Badge>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {readyRepo && hasCapability('modernize') && (
            <Button size="sm" asChild>
              <Link href={`/dashboard/modernize/assessments?repo=${readyRepo.id}`}>
                <Rocket className="h-4 w-4" />
                Assess modernization
              </Link>
            </Button>
          )}
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setConfirmAction({ type: 'delete-app' })}
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex flex-wrap gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              'px-4 py-2 text-sm font-medium capitalize transition-colors',
              tab === t
                ? 'border-b-2 border-primary text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            )}
          >
            {t}
            {t === 'plans' && hub.plans.length > 0 && ` (${hub.plans.length})`}
            {t === 'projects' && hub.projects.length > 0 && ` (${hub.projects.length})`}
          </button>
        ))}
      </div>

      {tab === 'repositories' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Repositories</CardTitle>
            <CardDescription>Codebases that make up this application</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {app.repositories.length === 0 ? (
              <p className="text-sm text-muted-foreground">No repositories assigned yet.</p>
            ) : (
              <ul className="divide-y rounded-md border">
                {app.repositories.map((repo) => (
                  <li
                    key={repo.id}
                    className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <Link
                        href={`/dashboard/intelligence/repositories/${repo.id}`}
                        className="text-sm font-medium hover:underline"
                      >
                        {repo.github_full_name || repo.name}
                      </Link>
                      <p className="text-xs capitalize text-muted-foreground">{repo.status}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {repo.role && (
                        <Badge variant="outline" className="capitalize">
                          {repo.role}
                        </Badge>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setConfirmAction({ type: 'remove-repo', repositoryId: repo.id })}
                        disabled={saving}
                      >
                        Remove
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {availableToAdd.length > 0 && (
              <div className="flex flex-col gap-3 rounded-md border bg-muted/30 p-4 sm:flex-row sm:items-end">
                <div className="flex-1 space-y-2">
                  <Label htmlFor="add-repo">Add repository</Label>
                  <select
                    id="add-repo"
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={addRepoId}
                    onChange={(e) => setAddRepoId(e.target.value)}
                  >
                    <option value="">Select repository</option>
                    {availableToAdd.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.github_full_name || r.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="add-role">Role</Label>
                  <select
                    id="add-role"
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm capitalize sm:w-[140px]"
                    value={addRole}
                    onChange={(e) => setAddRole(e.target.value)}
                  >
                    {REPO_ROLES.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </div>
                <Button onClick={addRepository} disabled={!addRepoId || saving}>
                  <Plus className="h-4 w-4" />
                  Add
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {tab === 'dependencies' && (
        <ServiceMapPanel applicationId={appId} repositoryCount={app.repository_count} />
      )}

      {tab === 'chat' && (
        <WikiChatPanel
          scope={{ type: 'application', id: appId, label: app.name }}
        />
      )}

      {tab === 'wiki' && (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <BookOpen className="h-4 w-4" />
                Application wiki
              </CardTitle>
              <CardDescription>
                Multi-repo wiki across all member repositories (plus per-repo wikis).
                {wikiSource === 'synthesized' && ' Showing synthesizer fallback until generation completes.'}
                {wikiSource === 'generated' && ' Generated from cloned member repos.'}
              </CardDescription>
              {wikiStatus && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Status: {wikiStatus}
                </p>
              )}
              {memberReadiness && memberReadiness.total_count > 0 && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Member wikis: {memberReadiness.ready_count}/{memberReadiness.total_count} ready
                  {!memberReadiness.all_ready
                    ? ' — Generate will ask whether to proceed now or retry incomplete repos first.'
                    : null}
                </p>
              )}
              {wikiBanner && (
                <p className="mt-2 rounded-md border border-primary/20 bg-primary/5 px-2 py-1.5 text-xs text-foreground">
                  {wikiBanner}
                </p>
              )}
            </div>
            <div className="flex shrink-0 gap-2">
              {wikiStatus === 'running' && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={wikiCancelling}
                  onClick={() => void cancelAppWiki()}
                >
                  {wikiCancelling ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Cancel
                </Button>
              )}
              <Button
                variant="default"
                size="sm"
                disabled={wikiGenerating || wikiStatus === 'running' || wikiCancelling}
                onClick={() => {
                  setWikiBanner(null)
                  setWikiGenerateOpen(true)
                }}
              >
                {wikiGenerating || wikiStatus === 'running' ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                {wikiSource === 'generated' ? 'Regenerate' : 'Generate'}
              </Button>
              <Button variant="outline" size="sm" asChild>
                <Link href={`/dashboard/intelligence/applications/${appId}/wiki-site`}>
                  View HTML
                </Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {memberReadiness && memberReadiness.members.length > 0 && (
              <ul className="mb-4 space-y-1.5 rounded-md border p-3">
                {memberReadiness.members.map((m) => (
                  <li
                    key={m.repository_id}
                    className="flex items-center justify-between gap-2 text-sm"
                  >
                    <Link
                      href={`/dashboard/intelligence/repositories/${m.repository_id}`}
                      className="truncate text-primary hover:underline"
                    >
                      {m.name}
                    </Link>
                    <Badge
                      variant={m.wiki_ready ? 'default' : m.repo_status === 'error' ? 'destructive' : 'outline'}
                      className="shrink-0 capitalize"
                    >
                      {m.wiki_ready
                        ? 'Wiki ready'
                        : m.index_run_status === 'running' || m.index_run_status === 'pending'
                          ? `Analyzing ${m.index_progress ?? 0}%`
                          : m.repo_status}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            {wikiLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : wikiMarkdown ? (
              <WikiMarkdownContent content={wikiMarkdown} />
            ) : (
              <p className="text-sm text-muted-foreground">
                No wiki content yet. Index member repositories, then generate the application wiki.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <ApplicationWikiGenerateDialog
        open={wikiGenerateOpen}
        applicationId={appId}
        onOpenChange={setWikiGenerateOpen}
        onCompleted={(result) => void onWikiGenerateCompleted(result)}
      />

      {tab === 'readiness' && (
        <div className="space-y-4">
          <ApplicationReadinessPanel
            applicationId={appId}
            canManage={hasCapability('modernize') && hasPermission('can_manage_modernize')}
          />

          {readinessRepoId && (
            <ReadinessPanel
              repoId={readinessRepoId}
              repoStatus={hub.readiness.find((r) => r.repository_id === readinessRepoId)?.status || 'pending'}
              canManage={hasCapability('modernize') && hasPermission('can_manage_modernize')}
            />
          )}

          {hub.readiness.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Drill into repository</CardTitle>
                <CardDescription>Open per-repo readiness detail</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {hub.readiness.map((row) => (
                  <Button
                    key={row.repository_id}
                    variant={readinessRepoId === row.repository_id ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setReadinessRepoId(row.repository_id)}
                  >
                    {row.repository_name}
                  </Button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {tab === 'plans' && (
        <Card>
          <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <ClipboardList className="h-4 w-4" />
                Modernization plans
              </CardTitle>
              <CardDescription>Plans for repositories in this application</CardDescription>
            </div>
            {hasCapability('modernize') && hasPermission('can_manage_modernize') && (
              <Button size="sm" onClick={createApplicationPlans} disabled={creatingPlans}>
                <Rocket className="h-4 w-4" />
                {creatingPlans ? 'Creating…' : 'Create plans for all repos'}
              </Button>
            )}
          </CardHeader>
          <CardContent className="space-y-3">
            {planMessage && (
              <p className="text-sm text-muted-foreground">{planMessage}</p>
            )}
            {hub.plans.length === 0 ? (
              <div className="text-sm text-muted-foreground">
                No plans yet.{' '}
                {readyRepo && (
                  <Link
                    href={`/dashboard/modernize/assessments?repo=${readyRepo.id}`}
                    className="text-primary hover:underline"
                  >
                    Start an assessment
                  </Link>
                )}
              </div>
            ) : (
              <ul className="divide-y rounded-md border">
                {hub.plans.map((plan) => (
                  <li key={plan.id} className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <Link
                        href={`/dashboard/modernize/plans/${plan.id}`}
                        className="text-sm font-medium hover:underline"
                      >
                        {plan.title}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {plan.repository_name} · <span className="capitalize">{plan.state}</span>
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {plan.spawned_project_id && (
                        <Button variant="outline" size="sm" asChild>
                          <Link href={`/dashboard/projects/${plan.spawned_project_id}`}>
                            <FolderKanban className="h-4 w-4" />
                            Build project
                          </Link>
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      {tab === 'projects' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FolderKanban className="h-4 w-4" />
              Build projects
            </CardTitle>
            <CardDescription>Delivery workstreams linked to this application</CardDescription>
          </CardHeader>
          <CardContent>
            {hub.projects.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No projects yet. Spawn Build from a modernization plan or{' '}
                <Link
                  href={`/dashboard/projects/new?application_id=${appId}&mode=enhance`}
                  className="text-primary hover:underline"
                >
                  create a project
                </Link>{' '}
                with this application as context.
              </p>
            ) : (
              <ul className="divide-y rounded-md border">
                {hub.projects.map((project) => (
                  <li key={project.id} className="flex items-center justify-between gap-3 px-3 py-3">
                    <div>
                      <Link
                        href={`/dashboard/projects/${project.id}`}
                        className="text-sm font-medium hover:underline"
                      >
                        {project.name}
                      </Link>
                      <p className="text-xs capitalize text-muted-foreground">
                        {project.pillar}
                        {project.mode ? ` · ${project.mode}` : ''} · {project.current_step}
                      </p>
                    </div>
                    {project.source_plan_id && (
                      <Button variant="ghost" size="sm" asChild>
                        <Link href={`/dashboard/modernize/plans/${project.source_plan_id}`}>
                          View plan
                        </Link>
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        open={confirmAction?.type === 'remove-repo'}
        title="Remove repository"
        description="Remove this repository from the application? It will remain connected to your tenant."
        confirmLabel="Remove"
        destructive
        loading={saving}
        onConfirm={() => {
          if (confirmAction?.type === 'remove-repo') {
            removeRepository(confirmAction.repositoryId)
          }
        }}
        onOpenChange={(open) => !open && setConfirmAction(null)}
      />
      <ConfirmDialog
        open={confirmAction?.type === 'delete-app'}
        title="Delete application"
        description={
          app
            ? `Delete application "${app.name}"? Repositories will be ungrouped but not deleted.`
            : ''
        }
        confirmLabel="Delete"
        destructive
        loading={saving}
        onConfirm={deleteApplication}
        onOpenChange={(open) => !open && setConfirmAction(null)}
      />
    </div>
  )
}
