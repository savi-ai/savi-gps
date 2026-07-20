'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { AlertTriangle, CheckCircle2, Loader2, Play, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ReadinessSignal {
  id: string
  label: string
  value: string
  score: number
  status: string
  detail: string
  repository_id?: string
  repository_name?: string
}

interface RepoReadiness {
  repository_id: string
  repository_name: string
  role?: string | null
  indexed: boolean
  assessed?: boolean
  overall_score: number | null
  readiness_level: string | null
  status: string
  signals: ReadinessSignal[]
}

interface ApplicationReadiness {
  assessed?: boolean
  assessed_at?: string
  message?: string
  application_id: string
  application_name: string
  overall_score?: number
  readiness_level?: string
  signals: ReadinessSignal[]
  repositories: RepoReadiness[]
}

const LEVEL_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  high: 'default',
  medium: 'secondary',
  low: 'destructive',
}

interface ApplicationReadinessPanelProps {
  applicationId: string
  canManage?: boolean
}

export default function ApplicationReadinessPanel({
  applicationId,
  canManage = true,
}: ApplicationReadinessPanelProps) {
  const [data, setData] = useState<ApplicationReadiness | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      const res = await apiClient.get(`/api/v1/modernize/applications/${applicationId}/readiness`)
      setData(res.data)
      setError(null)
    } catch {
      setData(null)
      setError('Failed to load application readiness')
    } finally {
      setLoading(false)
    }
  }, [applicationId])

  useEffect(() => {
    load()
  }, [load])

  const runAssessment = async () => {
    setRunning(true)
    setError(null)
    try {
      const res = await apiClient.post(
        `/api/v1/modernize/applications/${applicationId}/assessments/run`
      )
      setData(res.data)
    } catch {
      setError('Failed to run application assessment')
    } finally {
      setRunning(false)
    }
  }

  if (loading) return <Skeleton className="h-48 w-full" />
  if (error && !data) {
    return <p className="text-sm text-destructive">{error}</p>
  }
  if (!data) {
    return <p className="text-sm text-muted-foreground">Unavailable</p>
  }

  const assessed = Boolean(data.assessed)

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Application readiness</CardTitle>
          <CardDescription>
            Assesses all member repositories, then rolls up application score (worst-repo level)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {error && <p className="text-sm text-destructive">{error}</p>}
          {!assessed ? (
            <div className="space-y-3 rounded-md border border-dashed p-4">
              <p className="text-sm text-muted-foreground">
                {data.message || 'No application assessment yet. Run assessment to score all member repos.'}
              </p>
              {canManage && (
                <Button onClick={runAssessment} disabled={running}>
                  {running ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="h-4 w-4" />
                  )}
                  Run assessment
                </Button>
              )}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-3xl font-bold tabular-nums">{data.overall_score}</span>
              <Badge
                variant={LEVEL_VARIANT[data.readiness_level || ''] || 'outline'}
                className="capitalize"
              >
                {data.readiness_level}
              </Badge>
              {data.assessed_at && (
                <span className="text-xs text-muted-foreground">
                  Assessed {new Date(data.assessed_at).toLocaleString()}
                </span>
              )}
              <Button variant="outline" size="sm" onClick={runAssessment} disabled={running}>
                {running ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Re-run assessment
              </Button>
              <Button variant="ghost" size="sm" onClick={load}>
                <RefreshCw className="h-4 w-4" />
                Reload stored
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {assessed && data.signals.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cross-repo signals</CardTitle>
            <CardDescription>Worst signal per category across members</CardDescription>
          </CardHeader>
          <CardContent className="divide-y">
            {data.signals.map((sig) => {
              const Icon = sig.status === 'good' ? CheckCircle2 : AlertTriangle
              const iconClass =
                sig.status === 'good'
                  ? 'text-emerald-600'
                  : sig.status === 'bad'
                    ? 'text-destructive'
                    : 'text-amber-600'
              return (
                <div key={sig.id} className="flex items-start justify-between gap-3 py-3 first:pt-0">
                  <div className="flex items-start gap-2">
                    <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', iconClass)} />
                    <div>
                      <p className="text-sm font-medium">{sig.label}</p>
                      <p className="text-xs text-muted-foreground">{sig.detail}</p>
                      {sig.repository_name && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          From {sig.repository_name}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-medium">{sig.value}</p>
                    <p className="text-xs text-muted-foreground">{sig.score}/100</p>
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}

      {assessed && data.repositories.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Per-repository breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y rounded-md border">
              {data.repositories.map((repo) => (
                <li
                  key={repo.repository_id}
                  className="flex items-center justify-between gap-3 px-3 py-3"
                >
                  <div>
                    <Link
                      href={`/dashboard/intelligence/repositories/${repo.repository_id}`}
                      className="text-sm font-medium hover:underline"
                    >
                      {repo.repository_name}
                    </Link>
                    {repo.role && (
                      <span className="ml-2 text-xs capitalize text-muted-foreground">
                        {repo.role}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {!repo.indexed ? (
                      <Badge variant="outline" className="capitalize">
                        {repo.status}
                      </Badge>
                    ) : !repo.assessed ? (
                      <Badge variant="outline">Not assessed</Badge>
                    ) : (
                      <>
                        <span className="text-sm tabular-nums">{repo.overall_score}/100</span>
                        <Badge
                          variant={LEVEL_VARIANT[repo.readiness_level || 'medium'] || 'outline'}
                          className="capitalize"
                        >
                          {repo.readiness_level}
                        </Badge>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
