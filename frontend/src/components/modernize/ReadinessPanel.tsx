'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Loader2, Rocket, RefreshCw, Play } from 'lucide-react'
import { cn } from '@/lib/utils'
import AgentEffortCard, {
  type AgentEffort,
  type AssessmentSynthesis,
} from '@/components/modernize/AgentEffortCard'
import ReadinessSignalsList, {
  type ReadinessSignal,
  READINESS_LEVEL_VARIANT,
  formatReadinessLevel,
} from '@/components/modernize/ReadinessSignalsList'

export type { ReadinessSignal }

export interface ReadinessData {
  assessed?: boolean
  assessed_at?: string
  message?: string
  repository_id: string
  repository_name: string
  repository_status: string
  overall_score?: number
  readiness_level?: string
  signals?: ReadinessSignal[]
  recommended_plan_type?: 'fix' | 'modernize' | 'both' | string
  recommendation_reason?: string
  policy_gaps?: Array<{
    signal_id: string
    policy_name: string
    rule_id: string
    message: string
  }>
  policies_applied?: Array<{
    policy_name: string
    version_number: string
    policy_id?: string
  }>
  existing_plans?: Array<{
    id: string
    title: string
    state: string
    plan_type?: string
    spawned_project_id?: string | null
  }>
  indexed: boolean
  synthesis?: AssessmentSynthesis
  agent_effort?: AgentEffort
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

export default function ReadinessPanel({ repoId, repoStatus, canManage = false }: ReadinessPanelProps) {
  const router = useRouter()
  const [readiness, setReadiness] = useState<ReadinessData | null>(null)
  const [playbooks, setPlaybooks] = useState<Playbook[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [creating, setCreating] = useState(false)
  const [creatingFix, setCreatingFix] = useState(false)
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

  const startPlan = async (planType: 'modernize' | 'fix' = 'modernize') => {
    const setBusy = planType === 'fix' ? setCreatingFix : setCreating
    setBusy(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v1/modernize/plans', {
        repository_id: repoId,
        playbook_id: selectedPlaybook || undefined,
        plan_type: planType,
      })
      router.push(`/dashboard/modernize/plans/${res.data.id}`)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to create plan')
    } finally {
      setBusy(false)
    }
  }

  const ready = repoStatus === 'ready' || readiness?.indexed
  const assessed = Boolean(readiness?.assessed && readiness.signals)

  return (
    <Card className="border-l-4 pillar-accent-modernize shadow-sm">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">Repository readiness</CardTitle>
            <CardDescription>
              Signals show how ready this repo is for a <strong>fix plan</strong> (same-repo PR) or
              a <strong>modernize plan</strong> (architecture-led targets).
            </CardDescription>
          </div>
          <Button variant="ghost" size="icon" onClick={load} disabled={loading} aria-label="Reload stored">
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
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
                <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/20 p-4">
                  <div className="flex items-baseline gap-2">
                    <span className="text-4xl font-bold tabular-nums">{readiness.overall_score}</span>
                    <span className="text-sm text-muted-foreground">/ 100</span>
                  </div>
                  <Badge
                    variant={READINESS_LEVEL_VARIANT[readiness.readiness_level || ''] || 'outline'}
                  >
                    {formatReadinessLevel(readiness.readiness_level)}
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

                {(readiness.synthesis || readiness.agent_effort) && (
                  <AgentEffortCard
                    synthesis={readiness.synthesis}
                    effort={readiness.agent_effort}
                  />
                )}

                <div>
                  <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Assessment signals
                  </p>
                  <ReadinessSignalsList signals={readiness.signals || []} />
                </div>

                {(readiness.policies_applied || []).length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    Policies applied:{' '}
                    {(readiness.policies_applied || [])
                      .map((p) => `${p.policy_name} v${p.version_number}`)
                      .join(', ')}
                  </p>
                )}

                {(readiness.policy_gaps || []).length > 0 && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
                    <p className="mb-1 text-xs font-medium uppercase text-destructive">
                      Policy gaps ({readiness.policy_gaps!.length})
                    </p>
                    <ul className="space-y-1">
                      {readiness.policy_gaps!.map((g, i) => (
                        <li key={`${g.rule_id}-${i}`} className="text-xs text-destructive">
                          {g.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {(readiness.existing_plans || []).length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
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
                          {'plan_type' in p && p.plan_type && (
                            <Badge variant="secondary" className="ml-1 capitalize text-xs">
                              {String(p.plan_type)}
                            </Badge>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {canManage && (
                  <div className="space-y-3 border-t pt-4">
                    {readiness.recommendation_reason && (
                      <p className="text-xs text-muted-foreground">
                        {readiness.recommended_plan_type === 'fix' && (
                          <Badge className="mr-2 bg-sky-600 hover:bg-sky-600">Prefer fix</Badge>
                        )}
                        {readiness.recommended_plan_type === 'modernize' && (
                          <Badge className="mr-2">Prefer modernize</Badge>
                        )}
                        {readiness.recommended_plan_type === 'both' && (
                          <Badge variant="outline" className="mr-2">
                            Either works
                          </Badge>
                        )}
                        {readiness.recommendation_reason}
                      </p>
                    )}
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
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
                      <div className="flex flex-col gap-1">
                        <Button
                          onClick={() => startPlan('fix')}
                          disabled={!ready || creatingFix}
                          variant={
                            readiness.recommended_plan_type === 'modernize' ? 'outline' : 'default'
                          }
                        >
                          {creatingFix ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Rocket className="h-4 w-4" />
                          )}
                          Create fix plan
                        </Button>
                        <span className="text-[10px] text-muted-foreground">
                          In-repo edits → PR on this repository
                        </span>
                      </div>
                      <div className="flex flex-col gap-1">
                        <Button
                          onClick={() => startPlan('modernize')}
                          disabled={!ready || creating}
                          variant={
                            readiness.recommended_plan_type === 'fix' ? 'outline' : 'default'
                          }
                        >
                          {creating ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Rocket className="h-4 w-4" />
                          )}
                          Create modernize plan
                        </Button>
                        <span className="text-[10px] text-muted-foreground">
                          New target repos from architecture
                        </span>
                      </div>
                    </div>
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
