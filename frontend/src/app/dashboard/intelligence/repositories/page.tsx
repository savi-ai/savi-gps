'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { GitBranch, Plus, ArrowRight, Trash2 } from 'lucide-react'
import {
  IndexingProgressCard,
  isAnalysisActive,
  type IndexRunInfo,
} from '@/components/intelligence/IndexingProgressCard'
import { ConfirmDialog } from '@/components/ConfirmDialog'

interface Repository {
  id: string
  name: string
  url: string
  provider: string
  github_full_name?: string
  status: string
  default_branch: string
  last_indexed_at: string | null
  index_run?: IndexRunInfo
  application?: { id: string; name: string } | null
}

export default function RepositoriesPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { hasCapability, hasPermission } = useAuth()
  const [repos, setRepos] = useState<Repository[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Repository | null>(null)
  const [actionRepoId, setActionRepoId] = useState<string | null>(null)
  const importedCount = searchParams.get('imported')

  const fetchRepos = useCallback(async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const res = await apiClient.get('/api/v1/intelligence/repos')
      setRepos(res.data?.repositories || [])
      setError(null)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to load repositories')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  const anyAnalysisActive = repos.some((r) => isAnalysisActive(r.index_run, r.status))

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    fetchRepos()
  }, [hasCapability, router, fetchRepos])

  useEffect(() => {
    if (!anyAnalysisActive) return
    const t = setInterval(() => fetchRepos(true), 4000)
    return () => clearInterval(t)
  }, [anyAnalysisActive, fetchRepos])

  const performDelete = async (repo: Repository) => {
    setDeletingId(repo.id)
    try {
      await apiClient.delete(`/api/v1/intelligence/repos/${repo.id}`)
      setRepos((prev) => prev.filter((r) => r.id !== repo.id))
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to delete repository')
    } finally {
      setDeletingId(null)
      setConfirmDelete(null)
    }
  }

  const cancelRepoIndex = async (repoId: string) => {
    setActionRepoId(repoId)
    try {
      await apiClient.post(`/api/v1/intelligence/repos/${repoId}/index/cancel`)
      await fetchRepos(true)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to cancel analysis')
    } finally {
      setActionRepoId(null)
    }
  }

  const retryRepoIndex = async (repoId: string) => {
    setActionRepoId(repoId)
    try {
      await apiClient.post(`/api/v1/intelligence/repos/${repoId}/index`)
      await fetchRepos(true)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to start analysis')
    } finally {
      setActionRepoId(null)
    }
  }

  if (!hasPermission('can_use_intelligence')) {
    return null
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Repositories</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Connect source repositories for wiki generation, grounded chat, and code intelligence.
          </p>
        </div>
        <Button onClick={() => router.push('/dashboard/intelligence/repositories/new')}>
          <Plus className="h-4 w-4" />
          Connect Repository
        </Button>
      </div>

      {importedCount && (
        <p className="rounded-md border border-success/30 bg-success/5 px-3 py-2 text-sm text-success">
          Successfully connected {importedCount} repository(ies). Indexing may be in progress.
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Connected repositories</CardTitle>
          <CardDescription>
            Connect GitHub repositories to index code and generate draft wiki pages.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {[1, 2].map((i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : error ? (
            <p className="text-sm text-destructive">{error}</p>
          ) : repos.length === 0 ? (
            <div className="flex flex-col items-center py-12 text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-muted">
                <GitBranch className="h-7 w-7 text-muted-foreground" />
              </div>
              <h3 className="text-base font-semibold">No repositories connected</h3>
              <p className="mt-1 max-w-md text-sm text-muted-foreground">
                Connect a GitHub repository to start building your codebase wiki.
              </p>
              <Button
                className="mt-4"
                onClick={() => router.push('/dashboard/intelligence/repositories/new')}
              >
                <Plus className="h-4 w-4" />
                Connect Repository
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              {repos.some((r) => isAnalysisActive(r.index_run, r.status)) && (
                <p className="text-xs text-muted-foreground">
                  Analysis runs in the background — safe to navigate away or log out and return later.
                </p>
              )}
              <div className="divide-y">
                {repos.map((repo) => (
                  <div key={repo.id} className="py-3 first:pt-0 last:pb-0">
                    <div
                      role="link"
                      tabIndex={0}
                      onClick={() => router.push(`/dashboard/intelligence/repositories/${repo.id}`)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          router.push(`/dashboard/intelligence/repositories/${repo.id}`)
                        }
                      }}
                      className="flex w-full cursor-pointer items-center justify-between text-left transition-colors hover:bg-muted/50 rounded-md px-1 -mx-1"
                    >
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10">
                          <GitBranch className="h-4 w-4 text-primary" />
                        </div>
                        <div>
                          <p className="text-sm font-medium">{repo.github_full_name || repo.name}</p>
                          <p className="text-xs text-muted-foreground">{repo.url}</p>
                          {repo.application && (
                            <Badge variant="outline" className="mt-1 text-[10px]">
                              {repo.application.name}
                            </Badge>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={isAnalysisActive(repo.index_run, repo.status) ? 'default' : 'secondary'}
                          className={isAnalysisActive(repo.index_run, repo.status) ? 'capitalize animate-pulse' : 'capitalize'}
                        >
                          {isAnalysisActive(repo.index_run, repo.status)
                            ? repo.index_run?.status === 'pending'
                              ? 'queued'
                              : `analyzing ${repo.index_run?.progress ?? 0}%`
                            : repo.status}
                        </Badge>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-destructive"
                          disabled={deletingId === repo.id || isAnalysisActive(repo.index_run, repo.status)}
                          onClick={(e) => {
                            e.stopPropagation()
                            setConfirmDelete(repo)
                          }}
                          aria-label={`Delete ${repo.name}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                        <ArrowRight className="h-4 w-4 text-muted-foreground" />
                      </div>
                    </div>
                    {repo.index_run &&
                      (isAnalysisActive(repo.index_run, repo.status) ||
                        repo.index_run.status === 'failed') && (
                      <div className="mt-3 pl-11">
                        <IndexingProgressCard
                          run={repo.index_run}
                          repositoryName={repo.github_full_name || repo.name}
                          compact
                          onCancel={
                            isAnalysisActive(repo.index_run, repo.status)
                              ? () => cancelRepoIndex(repo.id)
                              : undefined
                          }
                          onRetry={
                            repo.index_run.status === 'failed'
                              ? () => retryRepoIndex(repo.id)
                              : undefined
                          }
                          actionBusy={actionRepoId === repo.id}
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete repository"
        description={
          confirmDelete
            ? `Disconnect and permanently delete "${confirmDelete.github_full_name || confirmDelete.name}"?\n\nThis removes all wiki and search index data.`
            : ''
        }
        confirmLabel="Delete"
        destructive
        loading={!!confirmDelete && deletingId === confirmDelete.id}
        onConfirm={() => confirmDelete && performDelete(confirmDelete)}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
      />
    </div>
  )
}
