'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Loader2, Play, RefreshCw, Rocket, ChevronDown, ChevronUp } from 'lucide-react'
import AgentEffortCard, {
  type AgentEffort,
  type AssessmentSynthesis,
} from '@/components/modernize/AgentEffortCard'
import ReadinessSignalsList, {
  type ReadinessSignal,
  READINESS_LEVEL_VARIANT,
  formatReadinessLevel,
} from '@/components/modernize/ReadinessSignalsList'

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

interface SignalGroup {
  repository_id: string
  repository_name: string
  role?: string | null
  signals: ReadinessSignal[]
  scorable_count?: number
  gap_count?: number
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
  signal_groups?: SignalGroup[]
  repositories: RepoReadiness[]
  policy_gaps?: Array<{ message: string; policy_name: string; signal_id: string }>
  policies_applied?: Array<{ policy_name: string; version_number: string }>
  synthesis?: AssessmentSynthesis
  agent_effort?: AgentEffort
}

interface ApplicationReadinessPanelProps {
  applicationId: string
  canManage?: boolean
}

function RepoSignalGroup({ group }: { group: SignalGroup }) {
  const [open, setOpen] = useState(true)
  const gapCount = group.gap_count ?? 0

  return (
    <div className="rounded-md border">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-muted/30"
        onClick={() => setOpen((v) => !v)}
      >
        <div>
          <p className="text-sm font-medium">{group.repository_name}</p>
          {group.role && (
            <p className="text-xs capitalize text-muted-foreground">{group.role}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {gapCount > 0 && (
            <Badge variant="secondary" className="text-[10px]">
              {gapCount} gap{gapCount === 1 ? '' : 's'}
            </Badge>
          )}
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>
      {open && (
        <div className="border-t px-1 pb-2">
          <ReadinessSignalsList signals={group.signals} hideNotApplicable />
        </div>
      )}
    </div>
  )
}

export default function ApplicationReadinessPanel({
  applicationId,
  canManage = true,
}: ApplicationReadinessPanelProps) {
  const router = useRouter()
  const [data, setData] = useState<ApplicationReadiness | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [creating, setCreating] = useState(false)
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

  const createModernizePlan = async () => {
    setCreating(true)
    setError(null)
    try {
      const res = await apiClient.post(`/api/v1/modernize/applications/${applicationId}/plans`, {
        per_repository: false,
      })
      const planId = res.data?.plan?.id || res.data?.plans?.[0]?.id
      if (planId) {
        router.push(`/dashboard/modernize/plans/${planId}`)
      } else {
        setError('Plan created but id missing')
      }
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to create modernization plan')
    } finally {
      setCreating(false)
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
  const signalGroups = data.signal_groups || []
  const topGaps = (data.signals || []).filter((s) => s.status === 'bad' || s.status === 'warn')

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Application readiness</CardTitle>
          <CardDescription>
            Assesses all member repositories and rolls up score and gaps across the application.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && <p className="text-sm text-destructive">{error}</p>}
          {!assessed ? (
            <div className="space-y-3 rounded-md border border-dashed p-4">
              <p className="text-sm text-muted-foreground">
                {data.message ||
                  'No application assessment yet. Run assessment to score all member repos.'}
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
            <>
              <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/20 p-4">
                <div className="flex items-baseline gap-2">
                  <span className="text-4xl font-bold tabular-nums">{data.overall_score}</span>
                  <span className="text-sm text-muted-foreground">/ 100</span>
                </div>
                <Badge variant={READINESS_LEVEL_VARIANT[data.readiness_level || ''] || 'outline'}>
                  {formatReadinessLevel(data.readiness_level)}
                </Badge>
                {data.assessed_at && (
                  <span className="text-xs text-muted-foreground">
                    Assessed {new Date(data.assessed_at).toLocaleString()}
                  </span>
                )}
                <div className="ml-auto flex flex-wrap gap-2">
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
                    Reload
                  </Button>
                </div>
              </div>

              {canManage && (
                <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <Button size="sm" onClick={() => void createModernizePlan()} disabled={creating}>
                      {creating ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Rocket className="h-4 w-4" />
                      )}
                      Create modernize plan
                    </Button>
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      Architecture defines new target repos — not in-place member fixes
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    For same-repo PRs, open a member repository and use{' '}
                    <strong>Create fix plan</strong>.
                  </p>
                </div>
              )}

              {(data.synthesis || data.agent_effort) && (
                <AgentEffortCard synthesis={data.synthesis} effort={data.agent_effort} />
              )}
            </>
          )}
        </CardContent>
      </Card>

      {assessed && data.repositories.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Member repositories</CardTitle>
            <CardDescription>Per-repo readiness scores — open a repo for fix plans</CardDescription>
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
                          variant={
                            READINESS_LEVEL_VARIANT[repo.readiness_level || 'partial'] || 'outline'
                          }
                        >
                          {formatReadinessLevel(repo.readiness_level)}
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

      {assessed && signalGroups.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Signals by repository</CardTitle>
            <CardDescription>
              Only checks that apply to each repo&apos;s stack — irrelevant runtime signals are hidden
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {signalGroups.map((group) => (
              <RepoSignalGroup key={group.repository_id} group={group} />
            ))}
          </CardContent>
        </Card>
      )}

      {assessed && topGaps.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top gaps across application</CardTitle>
            <CardDescription>Worst applicable signals from member repositories</CardDescription>
          </CardHeader>
          <CardContent>
            <ReadinessSignalsList signals={topGaps.slice(0, 8)} showRepo hideNotApplicable />
          </CardContent>
        </Card>
      )}

      {assessed && (data.policy_gaps || []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base text-destructive">Policy gaps</CardTitle>
            <CardDescription>Failures against tenant modernization policies</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1">
              {data.policy_gaps!.map((g, i) => (
                <li key={i} className="text-xs text-destructive">
                  {g.message}
                  {g.policy_name ? ` (${g.policy_name})` : ''}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
