'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  BarChart3,
  GitBranch,
  BookOpen,
  FolderKanban,
  AlertTriangle,
  Clock,
  ShieldCheck,
  RefreshCw,
  TrendingUp,
} from 'lucide-react'

interface PortfolioHealth {
  tenant_id: string
  generated_at: string
  health_score: number
  repositories: {
    total: number
    by_status: Record<string, number>
    ready: number
    indexed_pct: number
    avg_index_age_days: number | null
    stale_count: number
    error_count: number
  }
  indexing: {
    total_runs: number
    completed_runs: number
    failed_runs: number
    success_pct: number
  }
  wiki: {
    repos_with_wiki_site: number
    total_wiki_pages: number
    live_pages: number
    draft_pages: number
    coverage_pct: number
    approval_pct: number
  }
  projects: {
    total: number
    build: number
    modernize: number
  }
  modernization: {
    total: number
    active: number
    complete: number
    by_state: Record<string, number>
  }
  risk: {
    stale_repositories: number
    failed_index_runs: number
    repositories_in_error: number
    at_risk_total: number
  }
}

const STATUS_LABELS: Record<string, string> = {
  ready: 'Indexed',
  pending: 'Pending',
  indexing: 'In progress',
  error: 'Needs attention',
}

function healthScoreLabel(score: number): string {
  if (score >= 80) return 'Strong'
  if (score >= 60) return 'Moderate'
  if (score >= 40) return 'Needs attention'
  return 'At risk'
}

function healthScoreColor(score: number): string {
  if (score >= 80) return 'text-emerald-600'
  if (score >= 60) return 'text-amber-600'
  return 'text-destructive'
}

export default function PortfolioHealthPage() {
  const router = useRouter()
  const { hasCapability, hasPermission } = useAuth()
  const [health, setHealth] = useState<PortfolioHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchHealth = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await apiClient.get('/api/v1/portfolio/health')
      setHealth(res.data)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to load estate health')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!hasCapability('portfolio')) {
      router.push('/dashboard')
      return
    }
    if (!hasPermission('can_view_portfolio')) {
      router.push('/dashboard')
      return
    }
    fetchHealth()
  }, [hasCapability, hasPermission, router, fetchHealth])

  if (!hasCapability('portfolio') || !hasPermission('can_view_portfolio')) {
    return null
  }

  const score = health?.health_score ?? 0

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <BarChart3 className="h-6 w-6 pillar-text-portfolio" />
          <h1 className="text-2xl font-bold tracking-tight">Health</h1>
        </div>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Executive snapshot of application inventory, documentation readiness, operational risk,
          and modernization activity across your estate.
        </p>
        {health?.generated_at && (
          <p className="mt-1 text-xs text-muted-foreground">
            As of {new Date(health.generated_at).toLocaleString()}
          </p>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card className="border-l-4 pillar-accent-portfolio shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Overall estate health</CardTitle>
          <CardDescription>
            Composite score from index coverage, documentation, and operational signals
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-16 w-32" />
          ) : (
            <div className="flex flex-wrap items-end gap-4">
              <div>
                <span className={`text-5xl font-bold tabular-nums ${healthScoreColor(score)}`}>
                  {score}
                </span>
                <span className="ml-1 text-2xl text-muted-foreground">/100</span>
              </div>
              <Badge variant="secondary" className="mb-2 capitalize">
                {healthScoreLabel(score)}
              </Badge>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          {
            label: 'Indexed estate',
            value: health ? `${health.repositories.indexed_pct}%` : undefined,
            sub: health
              ? `${health.repositories.ready} of ${health.repositories.total} applications`
              : undefined,
            icon: GitBranch,
            href: '/dashboard/intelligence/repositories',
          },
          {
            label: 'Documentation coverage',
            value: health ? `${health.wiki.coverage_pct}%` : undefined,
            sub: health
              ? `${health.wiki.repos_with_wiki_site} apps with live documentation`
              : undefined,
            icon: BookOpen,
            href: '/dashboard/intelligence/wiki-review',
          },
          {
            label: 'At-risk signals',
            value: health?.risk.at_risk_total,
            sub: health
              ? `${health.risk.stale_repositories} stale · ${health.risk.repositories_in_error} errors`
              : undefined,
            icon: AlertTriangle,
            href: '/dashboard/intelligence/repositories',
          },
          {
            label: 'Active modernization',
            value: health?.modernization.active,
            sub: health
              ? `${health.modernization.complete} completed plans`
              : undefined,
            icon: RefreshCw,
            href: '/dashboard/modernize/plans',
          },
        ].map((stat) => (
          <Link key={stat.label} href={stat.href} className="block transition-opacity hover:opacity-90">
          <Card className="h-full shadow-sm cursor-pointer">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{stat.label}</CardTitle>
              <stat.icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className="h-8 w-16" />
              ) : (
                <>
                  <div className="text-2xl font-bold tabular-nums">{stat.value ?? '—'}</div>
                  <p className="text-xs text-muted-foreground">{stat.sub}</p>
                </>
              )}
            </CardContent>
          </Card>
          </Link>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShieldCheck className="h-4 w-4" />
              Application inventory
            </CardTitle>
            <CardDescription>Connected repositories and index status</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-24 w-full" />
            ) : health && health.repositories.total > 0 ? (
              <>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(health.repositories.by_status).map(([status, count]) => (
                    <Badge
                      key={status}
                      variant={status === 'ready' ? 'default' : status === 'error' ? 'destructive' : 'secondary'}
                    >
                      {STATUS_LABELS[status] || status}: {count}
                    </Badge>
                  ))}
                </div>
                {health.repositories.avg_index_age_days != null && (
                  <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
                    <Clock className="h-4 w-4" />
                    Average freshness: {health.repositories.avg_index_age_days} days since last index
                  </div>
                )}
                <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
                  <TrendingUp className="h-4 w-4" />
                  Index success rate: {health.indexing.success_pct}%
                  {health.indexing.failed_runs > 0 && (
                    <span className="text-destructive">
                      ({health.indexing.failed_runs} failed run
                      {health.indexing.failed_runs !== 1 ? 's' : ''})
                    </span>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No applications connected yet.</p>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">Documentation readiness</CardTitle>
            <CardDescription>Wiki coverage and governance status</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-24 w-full" />
            ) : health ? (
              <dl className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <dt className="text-muted-foreground">Apps documented</dt>
                  <dd className="text-lg font-semibold tabular-nums">
                    {health.wiki.repos_with_wiki_site}
                    <span className="text-sm font-normal text-muted-foreground">
                      {' '}
                      / {health.repositories.total}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Coverage</dt>
                  <dd className="text-lg font-semibold tabular-nums">{health.wiki.coverage_pct}%</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Approved pages</dt>
                  <dd className="text-lg font-semibold tabular-nums">{health.wiki.live_pages}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Pending review</dt>
                  <dd className="text-lg font-semibold tabular-nums">{health.wiki.draft_pages}</dd>
                </div>
              </dl>
            ) : null}
            {!loading && health && health.wiki.draft_pages > 0 && (
              <p className="mt-4 text-sm text-muted-foreground">
                {health.wiki.approval_pct}% of wiki content is approved for production use.
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="text-base">Operational risk</CardTitle>
            <CardDescription>Items requiring leadership or engineering attention</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-24 w-full" />
            ) : health ? (
              <ul className="space-y-3 text-sm">
                <li className="flex items-start justify-between gap-3">
                  <span>Stale applications (not indexed in 30+ days)</span>
                  <Badge variant={health.risk.stale_repositories > 0 ? 'destructive' : 'outline'}>
                    {health.risk.stale_repositories}
                  </Badge>
                </li>
                <li className="flex items-start justify-between gap-3">
                  <span>Applications in error state</span>
                  <Badge variant={health.risk.repositories_in_error > 0 ? 'destructive' : 'outline'}>
                    {health.risk.repositories_in_error}
                  </Badge>
                </li>
                <li className="flex items-start justify-between gap-3">
                  <span>Failed index operations</span>
                  <Badge variant={health.risk.failed_index_runs > 0 ? 'secondary' : 'outline'}>
                    {health.risk.failed_index_runs}
                  </Badge>
                </li>
              </ul>
            ) : null}
            {!loading && health && health.risk.at_risk_total === 0 && health.repositories.total > 0 && (
              <p className="mt-4 text-sm text-emerald-700 dark:text-emerald-400">
                No outstanding operational risk signals detected.
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FolderKanban className="h-4 w-4" />
              Modernization &amp; delivery
            </CardTitle>
            <CardDescription>Active programs and pipeline activity</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-24 w-full" />
            ) : health ? (
              <>
                <dl className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <dt className="text-muted-foreground">Modernization plans</dt>
                    <dd className="text-lg font-semibold tabular-nums">
                      {health.modernization.active}
                      <span className="text-sm font-normal text-muted-foreground"> active</span>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Completed plans</dt>
                    <dd className="text-lg font-semibold tabular-nums">{health.modernization.complete}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Build projects</dt>
                    <dd className="text-lg font-semibold tabular-nums">{health.projects.build}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Modernize projects</dt>
                    <dd className="text-lg font-semibold tabular-nums">{health.projects.modernize}</dd>
                  </div>
                </dl>
                {Object.keys(health.modernization.by_state).length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {Object.entries(health.modernization.by_state).map(([state, count]) => (
                      <Badge key={state} variant="outline" className="capitalize">
                        {state.replace(/_/g, ' ')}: {count}
                      </Badge>
                    ))}
                  </div>
                )}
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
