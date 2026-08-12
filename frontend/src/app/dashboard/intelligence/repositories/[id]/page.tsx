'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, BookOpen, MessageSquare, Play, RefreshCw, FileText, Trash2, Network } from 'lucide-react'
import ReadinessPanel from '@/components/modernize/ReadinessPanel'
import { BlastRadiusPanel } from '@/components/intelligence/BlastRadiusPanel'
import { DomainGraphPanel } from '@/components/intelligence/DomainGraphPanel'
import {
  IndexingProgressCard,
  isAnalysisActive,
} from '@/components/intelligence/IndexingProgressCard'
import PillarBreadcrumb from '@/components/navigation/PillarBreadcrumb'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import {
  RepositoryConnectionsPanel,
} from '@/components/build/RepositoryConnectionsPanel'
import { useApplications, useRepositoryConnections } from '@/hooks/queries/useIntelligence'

interface Repository {
  id: string
  name: string
  url: string
  github_full_name?: string
  status: string
  default_branch: string
  last_indexed_at: string | null
  last_index_error?: string | null
  application?: { id: string; name: string; role?: string | null } | null
}

interface WikiPage {
  slug: string
  title: string
  state: string
  drift_status?: string
  verified_claim_count?: number
  total_claim_count?: number
  citation_coverage?: number
}

function WikiPageBadges({ page }: { page: WikiPage }) {
  const coverage = Math.round((page.citation_coverage ?? 0) * 100)
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge
        variant={page.state === 'live' ? 'default' : 'secondary'}
        className={page.state === 'live' ? 'bg-emerald-600 hover:bg-emerald-600 capitalize' : 'capitalize'}
      >
        {page.state}
      </Badge>
      {page.drift_status === 'stale' && (
        <Badge variant="destructive">Stale</Badge>
      )}
      {page.drift_status === 'pending_review' && page.state === 'draft' && (
        <Badge variant="outline">Review</Badge>
      )}
      {(page.total_claim_count ?? 0) > 0 && (
        <Badge variant="outline">
          {page.verified_claim_count}/{page.total_claim_count} citations ({coverage}%)
        </Badge>
      )}
    </div>
  )
}

interface IndexStatus {
  repository_status: string
  chunk_count?: number
  wiki_page_count?: number
  graph_stats?: {
    available?: boolean
    symbol_count?: number
    calls_count?: number
    neo4j?: boolean
  }
  index_run?: {
    status: string
    progress: number
    error?: string
  }
}

export default function RepositoryDetailPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const showAssignPrompt = searchParams.get('assign_app') === '1'
  const activeTab = searchParams.get('tab') === 'analysis' ? 'analysis' : 'overview'
  const { hasCapability, hasPermission } = useAuth()
  const repoId = params?.id as string
  const intelligenceEnabled = hasCapability('intelligence')
  const { data: applicationsList = [] } = useApplications({ enabled: intelligenceEnabled })
  const {
    data: connections = null,
    isLoading: connectionsLoading,
  } = useRepositoryConnections(intelligenceEnabled ? repoId : undefined)
  const [repo, setRepo] = useState<Repository | null>(null)
  const [pages, setPages] = useState<WikiPage[]>([])
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [indexing, setIndexing] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [wikiMeta, setWikiMeta] = useState<{
    analysis_dir?: string
    generation_source?: string
    shell_succeeded?: boolean
  } | null>(null)
  const [driftStatus, setDriftStatus] = useState<{
    drift_status?: string
    wiki_pending_review?: number
    wiki_stale?: number
    spec_count?: number
    has_specs?: boolean
    has_kiro_specs?: boolean
  } | null>(null)
  const [assignAppId, setAssignAppId] = useState('')
  const [assignRole, setAssignRole] = useState('backend')
  const [assigning, setAssigning] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const load = useCallback(async () => {
    try {
      const [repoRes, pagesRes, statusRes, wikiRes, driftRes] = await Promise.all([
        apiClient.get(`/api/v1/intelligence/repos/${repoId}`),
        apiClient.get(`/api/v1/intelligence/repos/${repoId}/pages`),
        apiClient.get(`/api/v1/intelligence/repos/${repoId}/index-status`),
        apiClient.get(`/api/v1/intelligence/repos/${repoId}/wiki-site`).catch(() => ({ data: null })),
        apiClient.get(`/api/v1/intelligence/repos/${repoId}/specs/drift`).catch(() => ({ data: null })),
      ])
      setRepo(repoRes.data)
      setPages(pagesRes.data?.pages || [])
      setIndexStatus(statusRes.data)
      setWikiMeta(wikiRes.data)
      setDriftStatus(driftRes.data)
    } catch {
      setRepo(null)
    } finally {
      setLoading(false)
    }
  }, [repoId])

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    if (repoId) load()
  }, [repoId, hasCapability, router, load])

  useEffect(() => {
    const active = isAnalysisActive(indexStatus?.index_run, indexStatus?.repository_status)
    if (!active) return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [indexStatus?.index_run?.status, indexStatus?.repository_status, load])

  const assignToApplication = async () => {
    if (!assignAppId) return
    setAssigning(true)
    try {
      await apiClient.post(`/api/v1/intelligence/applications/${assignAppId}/repositories`, {
        repository_id: repoId,
        role: assignRole,
      })
      await load()
    } finally {
      setAssigning(false)
    }
  }

  const removeFromApplication = async () => {
    if (!repo?.application?.id) return
    setAssigning(true)
    try {
      await apiClient.delete(
        `/api/v1/intelligence/applications/${repo.application.id}/repositories/${repoId}`
      )
      await load()
    } finally {
      setAssigning(false)
    }
  }

  const startIndex = async () => {
    setIndexing(true)
    try {
      await apiClient.post(`/api/v1/intelligence/repos/${repoId}/index`)
      await load()
    } finally {
      setIndexing(false)
    }
  }

  const cancelIndex = async () => {
    setIndexing(true)
    try {
      await apiClient.post(`/api/v1/intelligence/repos/${repoId}/index/cancel`)
      await load()
    } finally {
      setIndexing(false)
    }
  }

  const deleteRepo = async () => {
    setDeleting(true)
    try {
      await apiClient.delete(`/api/v1/intelligence/repos/${repoId}`)
      router.push('/dashboard/intelligence/repositories')
    } finally {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  if (!hasPermission('can_use_intelligence')) return null

  if (loading) return <Skeleton className="h-48 w-full" />

  if (!repo) {
    return (
      <div className="py-12 text-center">
        <p className="text-muted-foreground">Repository not found</p>
        <Button variant="link" onClick={() => router.push('/dashboard/intelligence/repositories')}>
          Back
        </Button>
      </div>
    )
  }

  const run = indexStatus?.index_run
  const analysisActive = isAnalysisActive(run, repo.status)
  const graphAvailable = Boolean(indexStatus?.graph_stats?.available)

  const setTab = (tab: 'overview' | 'analysis') => {
    const params = new URLSearchParams(searchParams.toString())
    if (tab === 'overview') {
      params.delete('tab')
    } else {
      params.set('tab', tab)
    }
    const qs = params.toString()
    router.push(
      `/dashboard/intelligence/repositories/${repoId}${qs ? `?${qs}` : ''}`,
      { scroll: false }
    )
  }

  return (
    <div className="space-y-6">
      <PillarBreadcrumb
        items={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Repositories', href: '/dashboard/intelligence/repositories' },
          ...(repo.application
            ? [{ label: repo.application.name, href: `/dashboard/intelligence/applications/${repo.application.id}` }]
            : []),
          { label: repo.github_full_name || repo.name },
        ]}
      />

      {showAssignPrompt && !repo.application && (
        <Card className="border-l-4 border-amber-500 bg-amber-50/50 dark:bg-amber-950/20">
          <CardContent className="py-3 text-sm">
            <p className="font-medium">Add this repository to an application?</p>
            <p className="mt-1 text-muted-foreground">
              Grouping repos unlocks application-level readiness, plans, and Build context.
            </p>
          </CardContent>
        </Card>
      )}

      <Button
        variant="ghost"
        size="sm"
        className="-ml-2"
        onClick={() => router.push('/dashboard/intelligence/repositories')}
      >
        <ArrowLeft className="h-4 w-4" />
        Repositories
      </Button>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{repo.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {repo.github_full_name || repo.url}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="secondary" className="capitalize">
              {repo.status}
            </Badge>
            <Badge variant="outline">{repo.default_branch}</Badge>
            {indexStatus?.chunk_count != null && (
              <Badge variant="outline">{indexStatus.chunk_count} chunks</Badge>
            )}
            {indexStatus?.graph_stats?.available && (
              <Badge variant="outline">
                {indexStatus.graph_stats.symbol_count ?? 0} symbols ·{' '}
                {indexStatus.graph_stats.calls_count ?? 0} calls
              </Badge>
            )}
            {(driftStatus?.wiki_stale ?? 0) > 0 && (
              <Badge variant="destructive">{driftStatus?.wiki_stale} stale wiki</Badge>
            )}
            {(driftStatus?.wiki_pending_review ?? 0) > 0 && (
              <Badge variant="outline">{driftStatus?.wiki_pending_review} pending review</Badge>
            )}
            {(driftStatus?.has_specs || driftStatus?.has_kiro_specs) && (
              <Badge variant="outline">{driftStatus?.spec_count ?? 0} specs</Badge>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => router.push(`/dashboard/intelligence/specs?repo=${repoId}`)}
            >
              Specs &amp; drift
            </Button>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => router.push(`/dashboard/intelligence/search?repo=${repoId}`)}
            >
              Search this repo
            </Button>
          </div>
          {repo.last_index_error && (
            <p className="mt-2 text-sm text-destructive">{repo.last_index_error}</p>
          )}
          {wikiMeta?.analysis_dir && (
            <p className="mt-2 text-xs text-muted-foreground">
              Artifacts: <code className="text-[11px]">{wikiMeta.analysis_dir}</code>
              {wikiMeta.generation_source && (
                <> · via <span className="font-medium">{wikiMeta.generation_source}</span></>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {pages.length > 0 && (
            <>
              <Button
                variant="outline"
                onClick={() => router.push(`/dashboard/intelligence/repositories/${repoId}/wiki-site`)}
              >
                <FileText className="h-4 w-4" />
                Full Wiki (HTML)
              </Button>
              <Button
                variant="outline"
                onClick={() => router.push(`/dashboard/intelligence/chat?repo_id=${repoId}`)}
              >
                <MessageSquare className="h-4 w-4" />
                Wiki Chat
              </Button>
            </>
          )}
          <Button onClick={startIndex} disabled={indexing || analysisActive || deleting}>
            {indexing || analysisActive ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            {analysisActive && run
              ? run.status === 'pending'
                ? 'Queued…'
                : `Analyzing ${run.progress}%`
              : 'Re-index'}
          </Button>
          <Button
            variant="destructive"
            onClick={() => setConfirmDelete(true)}
            disabled={deleting || analysisActive}
          >
            <Trash2 className="h-4 w-4" />
            {deleting ? 'Deleting…' : 'Delete'}
          </Button>
        </div>
      </div>

      <div className="flex gap-1 border-b">
        <Button
          variant={activeTab === 'overview' ? 'secondary' : 'ghost'}
          size="sm"
          className="rounded-b-none"
          onClick={() => setTab('overview')}
        >
          Overview
        </Button>
        <Button
          variant={activeTab === 'analysis' ? 'secondary' : 'ghost'}
          size="sm"
          className="rounded-b-none"
          onClick={() => setTab('analysis')}
        >
          <Network className="h-4 w-4" />
          Analysis
        </Button>
      </div>

      {activeTab === 'analysis' ? (
        <div className="space-y-6">
          <BlastRadiusPanel
            repoId={repoId}
            graphAvailable={graphAvailable}
            repoStatus={repo.status}
          />
          <DomainGraphPanel repoId={repoId} repoStatus={repo.status} />
        </div>
      ) : (
        <>
      {run && (analysisActive || run.status === 'failed') && (
        <IndexingProgressCard
          run={run}
          repositoryName={repo.github_full_name || repo.name}
          onCancel={analysisActive ? cancelIndex : undefined}
          onRetry={run.status === 'failed' ? startIndex : undefined}
          actionBusy={indexing}
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Application</CardTitle>
          <CardDescription>
            Group this repository with others that ship as one product
          </CardDescription>
        </CardHeader>
        <CardContent>
          {repo.application ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <Link
                  href={`/dashboard/intelligence/applications/${repo.application.id}`}
                  className="text-sm font-medium hover:underline"
                >
                  {repo.application.name}
                </Link>
                {repo.application.role && (
                  <Badge variant="outline" className="ml-2 capitalize text-xs">
                    {repo.application.role}
                  </Badge>
                )}
              </div>
              <Button variant="outline" size="sm" onClick={removeFromApplication} disabled={assigning}>
                Remove from application
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-2">
                <label className="text-sm font-medium">Assign to application</label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={assignAppId}
                  onChange={(e) => setAssignAppId(e.target.value)}
                >
                  <option value="">Select application</option>
                  {applicationsList.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Role</label>
                <select
                  className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm capitalize"
                  value={assignRole}
                  onChange={(e) => setAssignRole(e.target.value)}
                >
                  {['backend', 'frontend', 'api', 'worker', 'infra', 'library', 'other'].map(
                    (role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    )
                  )}
                </select>
              </div>
              <Button onClick={assignToApplication} disabled={!assignAppId || assigning}>
                Assign
              </Button>
              <Button variant="link" size="sm" asChild>
                <Link href="/dashboard/intelligence/applications/new">Create new</Link>
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {hasCapability('modernize') && hasPermission('can_manage_modernize') && (
        <ReadinessPanel
          repoId={repoId}
          repoStatus={repo.status}
          canManage
        />
      )}

      <RepositoryConnectionsPanel
        connections={connections}
        loading={connectionsLoading}
        showModernize={hasCapability('modernize')}
        showBuild={hasCapability('build')}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BookOpen className="h-4 w-4" />
            Wiki pages
          </CardTitle>
          <CardDescription>
            Generated by Wiki Agent after indexing. Draft until reviewed — or open Full Wiki for the
            left-pane HTML site.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {pages.length === 0 ? (
            <p className="text-sm text-muted-foreground">No wiki pages yet — run indexing first.</p>
          ) : (
            <ul className="divide-y">
              {pages.map((p) => (
                <li key={p.slug} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <Link
                    href={`/dashboard/intelligence/repositories/${repoId}/wiki/${p.slug}`}
                    className="text-sm font-medium hover:underline"
                  >
                    {p.title}
                  </Link>
                  <WikiPageBadges page={p} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
        </>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete repository"
        description={`Disconnect and permanently delete "${repo.github_full_name || repo.name}"?\n\nThis removes all wiki pages, search index data, and analysis attributes. This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        loading={deleting}
        onConfirm={deleteRepo}
        onOpenChange={setConfirmDelete}
      />
    </div>
  )
}
