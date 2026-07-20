'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { AlertTriangle, CheckCircle2, Loader2, Rocket, RefreshCw, Play } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface ReadinessSignal {
  id: string
  label: string
  value: string
  score: number
  status: 'good' | 'warn' | 'bad' | string
  detail: string
}

export interface ReadinessData {
  assessed?: boolean
  assessed_at?: string
  message?: string
  repository_id: string
  repository_name: string
  repository_status: string
  overall_score?: number
  readiness_level?: 'low' | 'medium' | 'high' | string
  signals?: ReadinessSignal[]
  existing_plans?: Array<{
    id: string
    title: string
    state: string
    spawned_project_id?: string | null
  }>
  indexed: boolean
}

interface Playbook {
  id: string
  name: string
  description?: string
}

interface ReadinessPanelProps {
  repoId: string
  repoStatus: string
  canManage?: boolean
}

const LEVEL_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  high: 'default',
  medium: 'secondary',
  low: 'destructive',
}

function SignalRow({ signal }: { signal: ReadinessSignal }) {
  const Icon =
    signal.status === 'good'
      ? CheckCircle2
      : signal.status === 'bad'
        ? AlertTriangle
        : AlertTriangle
  const iconClass =
    signal.status === 'good'
      ? 'text-emerald-600'
      : signal.status === 'bad'
        ? 'text-destructive'
        : 'text-amber-600'

  return (
    <div className="flex items-start justify-between gap-3 py-2">
      <div className="flex items-start gap-2">
        <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', iconClass)} />
        <div>
          <p className="text-sm font-medium">{signal.label}</p>
          <p className="text-xs text-muted-foreground">{signal.detail}</p>
        </div>
      </div>
      <div className="text-right shrink-0">
        <p className="text-sm font-medium">{signal.value}</p>
        <p className="text-xs text-muted-foreground">{signal.score}/100</p>
      </div>
    </div>
  )
}

export default function ReadinessPanel({ repoId, repoStatus, canManage = false }: ReadinessPanelProps) {
  const router = useRouter()
  const [readiness, setReadiness] = useState<ReadinessData | null>(null)
  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [creating, setCreating] = useState(false)
  const [selectedPlaybook, setSelectedPlaybook] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const [readinessRes, playbooksRes] = await Promise.all([
        apiClient.get(`/api/v1/modernize/repos/${repoId}/readiness`),
        apiClient.get('/api/v1/modernize/playbooks').catch(() => ({ data: { playbooks: [] } })),
      ])
      setReadiness(readinessRes.data)
      setPlaybooks(playbooksRes.data?.playbooks || [])
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to load readiness')
    } finally {
      setLoading(false)
    }
  }, [repoId])

  useEffect(() => {
    load()
  }, [load])

  const runAssessment = async () => {
    setRunning(true)
    setError(null)
    try {
      const res = await apiClient.post(`/api/v1/modernize/repos/${repoId}/assessments/run`)
      setReadiness(res.data)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to run assessment')
    } finally {
      setRunning(false)
    }
  }

  const startPlan = async () => {
    setCreating(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v1/modernize/plans', {
        repository_id: repoId,
        playbook_id: selectedPlaybook || undefined,
      })
      router.push(`/dashboard/modernize/plans/${res.data.id}`)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to create plan')
    } finally {
      setCreating(false)
    }
  }

  const ready = repoStatus === 'ready' || readiness?.indexed
  const assessed = Boolean(readiness?.assessed && readiness.signals)

  return (
    <Card className="border-l-4 pillar-accent-modernize shadow-sm">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">Modernization readiness</CardTitle>
            <CardDescription>
              Manual assessment from wiki analysis, index metadata, and code structure
            </CardDescription>
          </div>
          <Button variant="ghost" size="icon" onClick={load} disabled={loading} aria-label="Reload stored">
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <Skeleton className="h-32 w-full" />
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : readiness ? (
          <>
            {!assessed ? (
              <div className="space-y-3 rounded-md border border-dashed p-4">
                <p className="text-sm text-muted-foreground">
                  {readiness.message ||
                    'No assessment yet. Run assessment after the repository is indexed.'}
                </p>
                {canManage && (
                  <Button onClick={runAssessment} disabled={!ready || running}>
                    {running ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                    Run assessment
                  </Button>
                )}
                {!ready && (
                  <p className="text-xs text-muted-foreground">
                    Index this repository first — assessment needs a completed wiki analysis.
                  </p>
                )}
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-3xl font-bold">{readiness.overall_score}</span>
                  <Badge
                    variant={LEVEL_VARIANT[readiness.readiness_level || ''] || 'outline'}
                    className="capitalize"
                  >
                    {readiness.readiness_level} readiness
                  </Badge>
                  {readiness.assessed_at && (
                    <span className="text-xs text-muted-foreground">
                      Assessed {new Date(readiness.assessed_at).toLocaleString()}
                    </span>
                  )}
                  {canManage && (
                    <Button variant="outline" size="sm" onClick={runAssessment} disabled={running}>
                      {running ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                      Re-run assessment
                    </Button>
                  )}
                </div>

                <div className="divide-y rounded-md border px-3">
                  {(readiness.signals || []).map((s) => (
                    <SignalRow key={s.id} signal={s} />
                  ))}
                </div>

                {(readiness.existing_plans || []).length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                      Active plans
                    </p>
                    <ul className="space-y-1">
                      {(readiness.existing_plans || []).map((p) => (
                        <li key={p.id}>
                          <button
                            type="button"
                            className="text-sm font-medium text-primary hover:underline"
                            onClick={() => router.push(`/dashboard/modernize/plans/${p.id}`)}
                          >
                            {p.title}
                          </button>
                          <Badge variant="outline" className="ml-2 capitalize text-xs">
                            {p.state}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {canManage && (
                  <div className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-end">
                    {playbooks.length > 0 && (
                      <div className="flex-1">
                        <label className="mb-1 block text-xs text-muted-foreground">
                          Playbook (optional)
                        </label>
                        <select
                          value={selectedPlaybook}
                          onChange={(e) => setSelectedPlaybook(e.target.value)}
                          className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                        >
                          <option value="">No playbook</option>
                          {playbooks.map((pb) => (
                            <option key={pb.id} value={pb.id}>
                              {pb.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                    <Button onClick={startPlan} disabled={!ready || creating}>
                      {creating ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Rocket className="h-4 w-4" />
                      )}
                      Start modernize plan
                    </Button>
                  </div>
                )}
              </>
            )}
          </>
        ) : null}
      </CardContent>
    </Card>
  )
}
