'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { GitBranch, ArrowRight, RefreshCw, Layers, Rocket, Play, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Repository {
  id: string
  name: string
  github_full_name?: string
  status: string
}

interface Application {
  id: string
  name: string
  repository_count: number
  repositories_ready?: number
}

interface ReadinessSummary {
  assessed: boolean
  overall_score?: number
  readiness_level?: string
}

type ViewMode = 'repositories' | 'applications'

export default function ModernizeAssessmentsPage() {
  const router = useRouter()
  const { hasCapability, hasPermission } = useAuth()
  const [view, setView] = useState<ViewMode>('applications')
  const [repos, setRepos] = useState<Repository[]>([])
  const [applications, setApplications] = useState<Application[]>([])
  const [repoScores, setRepoScores] = useState<Record<string, ReadinessSummary>>({})
  const [appScores, setAppScores] = useState<Record<string, ReadinessSummary>>({})
  const [loading, setLoading] = useState(true)
  const [creatingFor, setCreatingFor] = useState<string | null>(null)
  const [runningFor, setRunningFor] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      const [reposRes, appsRes] = await Promise.all([
        apiClient.get('/api/v1/intelligence/repos'),
        apiClient.get('/api/v1/intelligence/applications'),
      ])
      const list: Repository[] = reposRes.data?.repositories || []
      const apps: Application[] = appsRes.data?.applications || []
      setRepos(list)
      setApplications(apps)

      const repoEntries = await Promise.all(
        list.map(async (repo) => {
          try {
            const r = await apiClient.get(`/api/v1/modernize/repos/${repo.id}/readiness`)
            return [
              repo.id,
              {
                assessed: Boolean(r.data.assessed),
                overall_score: r.data.overall_score,
                readiness_level: r.data.readiness_level,
              },
            ] as const
          } catch {
            return [repo.id, { assessed: false }] as const
          }
        })
      )
      setRepoScores(Object.fromEntries(repoEntries))

      const appEntries = await Promise.all(
        apps.map(async (app) => {
          try {
            const r = await apiClient.get(`/api/v1/modernize/applications/${app.id}/readiness`)
            return [
              app.id,
              {
                assessed: Boolean(r.data.assessed),
                overall_score: r.data.overall_score,
                readiness_level: r.data.readiness_level,
              },
            ] as const
          } catch {
            return [app.id, { assessed: false }] as const
          }
        })
      )
      setAppScores(Object.fromEntries(appEntries))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!hasCapability('modernize') || !hasPermission('can_manage_modernize')) {
      router.push('/dashboard')
      return
    }
    load()
  }, [hasCapability, hasPermission, router, load])

  const runRepoAssessment = async (repoId: string) => {
    setRunningFor(repoId)
    try {
      const r = await apiClient.post(`/api/v1/modernize/repos/${repoId}/assessments/run`)
      setRepoScores((prev) => ({
        ...prev,
        [repoId]: {
          assessed: true,
          overall_score: r.data.overall_score,
          readiness_level: r.data.readiness_level,
        },
      }))
    } finally {
      setRunningFor(null)
    }
  }

  const runAppAssessment = async (appId: string) => {
    setRunningFor(appId)
    try {
      const r = await apiClient.post(`/api/v1/modernize/applications/${appId}/assessments/run`)
      setAppScores((prev) => ({
        ...prev,
        [appId]: {
          assessed: true,
          overall_score: r.data.overall_score,
          readiness_level: r.data.readiness_level,
        },
      }))
      await load()
    } finally {
      setRunningFor(null)
    }
  }

  const createAppPlans = async (appId: string) => {
    setCreatingFor(appId)
    try {
      await apiClient.post(`/api/v1/modernize/applications/${appId}/plans`, { skip_existing: true })
      router.push(`/dashboard/intelligence/applications/${appId}?tab=plans`)
    } catch {
      setCreatingFor(null)
    }
  }

  if (!hasCapability('modernize') || !hasPermission('can_manage_modernize')) {
    return null
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Assessments</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Run readiness manually for an application (all member repos) or a single repository.
            Indexing alone does not assess.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      <div className="flex gap-2">
        <Button
          size="sm"
          variant={view === 'applications' ? 'default' : 'outline'}
          onClick={() => setView('applications')}
        >
          <Layers className="h-4 w-4" />
          By application
        </Button>
        <Button
          size="sm"
          variant={view === 'repositories' ? 'default' : 'outline'}
          onClick={() => setView('repositories')}
        >
          <GitBranch className="h-4 w-4" />
          By repository
        </Button>
      </div>

      {view === 'repositories' ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Connected repositories</CardTitle>
            <CardDescription>Stored readiness — click Run assessment to score</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : repos.length === 0 ? (
              <div className="py-8 text-center">
                <p className="text-sm text-muted-foreground">No repositories connected yet.</p>
                <Button
                  className="mt-4"
                  size="sm"
                  onClick={() => router.push('/dashboard/intelligence/repositories/new')}
                >
                  Connect repository
                </Button>
              </div>
            ) : (
              <ul className="divide-y">
                {repos.map((repo) => {
                  const score = repoScores[repo.id]
                  return (
                    <li
                      key={repo.id}
                      className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
                          <GitBranch className="h-4 w-4" />
                        </div>
                        <div className="min-w-0">
                          <Link
                            href={`/dashboard/intelligence/repositories/${repo.id}`}
                            className="truncate text-sm font-medium hover:underline"
                          >
                            {repo.github_full_name || repo.name}
                          </Link>
                          <p className="text-xs capitalize text-muted-foreground">{repo.status}</p>
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {score?.assessed ? (
                          <Badge variant="outline">
                            {score.overall_score} · {score.readiness_level}
                          </Badge>
                        ) : (
                          <Badge variant="secondary">Not assessed</Badge>
                        )}
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={repo.status !== 'ready' || runningFor === repo.id}
                          onClick={() => runRepoAssessment(repo.id)}
                        >
                          {runningFor === repo.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Play className="h-4 w-4" />
                          )}
                          {score?.assessed ? 'Re-run' : 'Run assessment'}
                        </Button>
                        <Button variant="ghost" size="sm" asChild>
                          <Link href={`/dashboard/intelligence/repositories/${repo.id}`}>
                            Open
                            <ArrowRight className="h-4 w-4" />
                          </Link>
                        </Button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Applications</CardTitle>
            <CardDescription>
              Run assessment across all member repos, then create modernization plans
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {[1, 2].map((i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : applications.length === 0 ? (
              <div className="py-8 text-center">
                <p className="text-sm text-muted-foreground">No applications defined yet.</p>
                <Button
                  className="mt-4"
                  size="sm"
                  onClick={() => router.push('/dashboard/intelligence/applications/new')}
                >
                  Create application
                </Button>
              </div>
            ) : (
              <ul className="divide-y">
                {applications.map((app) => {
                  const score = appScores[app.id]
                  return (
                    <li
                      key={app.id}
                      className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0">
                        <Link
                          href={`/dashboard/intelligence/applications/${app.id}?tab=readiness`}
                          className="text-sm font-medium hover:underline"
                        >
                          {app.name}
                        </Link>
                        <p className="text-xs text-muted-foreground">
                          {app.repository_count} repos
                          {app.repositories_ready != null && ` · ${app.repositories_ready} indexed`}
                        </p>
                      </div>
                      <div className="flex shrink-0 flex-wrap items-center gap-2">
                        {score?.assessed ? (
                          <Badge variant="outline">
                            {score.overall_score} · {score.readiness_level}
                          </Badge>
                        ) : (
                          <Badge variant="secondary">Not assessed</Badge>
                        )}
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={runningFor === app.id}
                          onClick={() => runAppAssessment(app.id)}
                        >
                          {runningFor === app.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Play className="h-4 w-4" />
                          )}
                          {score?.assessed ? 'Re-run' : 'Run assessment'}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={creatingFor === app.id || (app.repositories_ready || 0) < 1}
                          onClick={() => createAppPlans(app.id)}
                        >
                          <Rocket className="h-4 w-4" />
                          {creatingFor === app.id ? 'Creating…' : 'Create plans'}
                        </Button>
                        <Button size="sm" variant="ghost" asChild>
                          <Link href={`/dashboard/intelligence/applications/${app.id}?tab=readiness`}>
                            Open
                            <ArrowRight className="h-4 w-4" />
                          </Link>
                        </Button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
