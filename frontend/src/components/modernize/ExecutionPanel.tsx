'use client'

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import {
  CheckCircle2,
  Circle,
  ExternalLink,
  FolderGit2,
  Loader2,
  Play,
  RefreshCw,
  XCircle,
} from 'lucide-react'

export interface ExecutionTarget {
  slug: string
  name?: string
  role?: string
  github_url?: string | null
  clone_status?: string
  branch?: string
}

export interface ExecutionManifest {
  plan_type?: string
  stages?: string[]
  stage_state?: Record<string, string>
  stage_errors?: Record<string, string>
  source?: {
    clone_status?: string
    clone_error?: string
    branch?: string
    github_url?: string
    local_path?: string
  }
  target?: {
    github_url?: string
    branch?: string
    same_repo?: boolean
  }
  push?: {
    branch?: string
    commit_sha?: string
    targets?: Array<{
      slug: string
      branch?: string
      pr?: { url?: string; number?: number }
      skipped?: boolean
      reason?: string
    }>
  }
  pr?: {
    url?: string
    number?: number
  }
  targets?: ExecutionTarget[]
}

export interface ExecutionStatus {
  plan_id: string
  plan_type: string
  assessment_run_id?: string | null
  initialized: boolean
  execution_root?: string | null
  manifest?: ExecutionManifest | null
  spawned_project_id?: string | null
}

const STAGE_LABELS: Record<string, string> = {
  fix: 'Fix',
  code: 'Code',
  test: 'Test',
  push: 'Push',
  pr: 'PR',
  requirements: 'Requirements',
  tasks: 'Tasks',
  architecture: 'Architecture',
}

function stageIcon(status: string | undefined) {
  if (status === 'completed') return <CheckCircle2 className="h-4 w-4 text-emerald-600" />
  if (status === 'failed') return <XCircle className="h-4 w-4 text-destructive" />
  if (status === 'running') return <Loader2 className="h-4 w-4 animate-spin text-primary" />
  return <Circle className="h-4 w-4 text-muted-foreground" />
}

interface ExecutionPanelProps {
  planId: string
  planType?: string
  spawnedProjectId?: string | null
  canManage?: boolean
}

export default function ExecutionPanel({
  planId,
  planType = 'modernize',
  spawnedProjectId,
  canManage = false,
}: ExecutionPanelProps) {
  const [execution, setExecution] = useState<ExecutionStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [runningStage, setRunningStage] = useState<string | null>(null)
  const [retryingClone, setRetryingClone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [regSlug, setRegSlug] = useState('')
  const [regUrl, setRegUrl] = useState('')
  const [regBranch, setRegBranch] = useState('main')
  const [registering, setRegistering] = useState(false)

  const load = useCallback(async (opts?: { quiet?: boolean }) => {
    try {
      if (!opts?.quiet) setLoading(true)
      const res = await apiClient.get<ExecutionStatus>(`/api/v1/modernize/plans/${planId}/execution`)
      setExecution(res.data)
      setError(null)
      return res.data
    } catch {
      setExecution(null)
      setError('Could not load execution workspace')
      return null
    } finally {
      if (!opts?.quiet) setLoading(false)
    }
  }, [planId])

  useEffect(() => {
    if (planId) void load()
  }, [planId, load, spawnedProjectId])

  // Poll while any stage is running so the UI stays usable (POST returns immediately)
  useEffect(() => {
    const stageState = execution?.manifest?.stage_state || {}
    const running = Object.values(stageState).some((s) => s === 'running')
    if (!running && !runningStage) return

    const id = setInterval(() => {
      void load({ quiet: true }).then((data) => {
        const states = data?.manifest?.stage_state || {}
        const still = Object.values(states).some((s) => s === 'running')
        if (!still) setRunningStage(null)
      })
    }, 2000)
    return () => clearInterval(id)
  }, [execution?.manifest?.stage_state, runningStage, load])

  const runStage = async (stage: string, opts?: { rerun?: boolean }) => {
    if (opts?.rerun) {
      const idx = stages.indexOf(stage)
      const downstream = stages.slice(idx + 1)
      const label = STAGE_LABELS[stage] || stage
      const message =
        downstream.length > 0
          ? `Re-running ${label} will reset ${downstream.map((s) => STAGE_LABELS[s] || s).join(', ')} to pending. Continue?`
          : `Re-run ${label}?`
      if (!window.confirm(message)) return
    }

    setRunningStage(stage)
    setError(null)
    try {
      await apiClient.post(`/api/v1/modernize/plans/${planId}/execution/stages/${stage}/run`)
      await load({ quiet: true })
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || `Failed to start stage: ${stage}`)
      setRunningStage(null)
      await load({ quiet: true })
    }
  }

  const retryClone = async () => {
    setRetryingClone(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/modernize/plans/${planId}/execution/retry-clone`)
      await load()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to retry clone')
    } finally {
      setRetryingClone(false)
    }
  }

  const registerTarget = async () => {
    if (!regSlug.trim() || !regUrl.trim()) {
      setError('Component slug and GitHub URL are required')
      return
    }
    setRegistering(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/modernize/plans/${planId}/execution/targets`, {
        slug: regSlug.trim(),
        github_url: regUrl.trim(),
        branch: regBranch.trim() || 'main',
        clone: true,
      })
      setRegUrl('')
      await load()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to register target')
    } finally {
      setRegistering(false)
    }
  }

  if (loading) return <Skeleton className="h-40 w-full" />

  const manifest = execution?.manifest
  const stages =
    manifest?.stages ??
    (planType === 'fix'
      ? ['fix', 'code', 'test', 'push', 'pr']
      : ['requirements', 'tasks', 'architecture', 'code', 'test', 'push'])
  const stageState = manifest?.stage_state ?? {}
  const targets = manifest?.targets ?? []

  const nextRunnable = stages.find((s, i) => {
    const status = stageState[s] || 'pending'
    if (status === 'completed') return false
    if (status === 'running') return false
    const priorOk = stages.slice(0, i).every((p) => stageState[p] === 'completed')
    return priorOk
  })

  const anyStageRunning = Object.values(stageState).some((s) => s === 'running')
  const stageErrors = manifest?.stage_errors ?? {}
  const pushTargets = manifest?.push?.targets

  return (
    <Card className="border-l-4 border-sky-500 shadow-sm">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <FolderGit2 className="h-4 w-4" />
              Execution workspace
            </CardTitle>
            <CardDescription>
              {planType === 'fix'
                ? 'Agent edits source/ in the member repo checkout — Copilot approve each stage.'
                : 'Architecture defines components under targets/{component}/ — Copilot approve each stage.'}
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void load()}
            aria-label="Refresh execution"
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive">
            {error}
          </p>
        )}

        {!execution?.initialized ? (
          <p className="text-sm text-muted-foreground">
            Workspace not initialized yet. Start {planType === 'fix' ? 'fix execution' : 'modernization'}{' '}
            to create the execution folder and manifest.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
              <Badge variant="outline" className="capitalize">
                {execution.plan_type === 'fix' ? 'Fix plan' : 'Modernize plan'}
              </Badge>
              {execution.assessment_run_id && (
                <span>Assessment run: {execution.assessment_run_id.slice(0, 19)}</span>
              )}
              {manifest?.source?.clone_status && (
                <Badge
                  variant={manifest.source.clone_status === 'ready' ? 'secondary' : 'outline'}
                  className="capitalize"
                >
                  clone: {manifest.source.clone_status}
                </Badge>
              )}
              {manifest?.source?.branch && (
                <Badge variant="outline">branch: {manifest.source.branch}</Badge>
              )}
            </div>

            {(manifest?.source?.local_path ||
              manifest?.source?.github_url ||
              execution.execution_root) && (
              <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs space-y-1">
                <p className="font-medium text-muted-foreground uppercase tracking-wide">
                  Manifest paths
                </p>
                {execution.execution_root && (
                  <p>
                    <span className="text-muted-foreground">Workspace: </span>
                    <code className="break-all">{execution.execution_root}</code>
                  </p>
                )}
                {manifest?.source?.local_path && (
                  <p>
                    <span className="text-muted-foreground">Source: </span>
                    <code className="break-all">{manifest.source.local_path}</code>
                  </p>
                )}
                {manifest?.source?.github_url && (
                  <p>
                    <span className="text-muted-foreground">Repo: </span>
                    <a
                      href={manifest.source.github_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      {manifest.source.github_url}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </p>
                )}
                {planType === 'fix' && manifest?.target?.same_repo && (
                  <p className="text-muted-foreground">Push target: same repository (fix PR)</p>
                )}
              </div>
            )}

            {manifest?.source?.clone_status === 'failed' && canManage && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
                <p className="text-amber-800 dark:text-amber-200">
                  Source clone failed{manifest.source.clone_error ? `: ${manifest.source.clone_error}` : '.'}
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-2"
                  onClick={() => void retryClone()}
                  disabled={retryingClone}
                >
                  {retryingClone ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Retry clone
                </Button>
              </div>
            )}

            {anyStageRunning && (
              <p className="rounded-md border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-sm text-sky-900 dark:text-sky-100">
                Stage running in the background — you can keep using the app. This panel refreshes
                automatically.
              </p>
            )}

            <ol className="space-y-2">
              {stages.map((stage) => {
                const status = stageState[stage] || 'pending'
                const isNext = stage === nextRunnable
                const errMsg = stageErrors[stage]
                return (
                  <li
                    key={stage}
                    className={cn(
                      'flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2',
                      status === 'completed' && 'border-emerald-500/30 bg-emerald-500/5',
                      status === 'failed' && 'border-destructive/30 bg-destructive/5',
                      status === 'running' && 'border-sky-500/30 bg-sky-500/5'
                    )}
                  >
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        {stageIcon(status)}
                        <span className="text-sm font-medium">{STAGE_LABELS[stage] || stage}</span>
                        <Badge variant="outline" className="text-xs capitalize">
                          {status}
                        </Badge>
                      </div>
                      {errMsg && status === 'failed' && (
                        <p className="text-xs text-destructive break-words">{errMsg}</p>
                      )}
                    </div>
                    {canManage && isNext && status !== 'completed' && status !== 'running' && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => void runStage(stage)}
                        disabled={anyStageRunning || runningStage !== null}
                      >
                        {runningStage === stage ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                        Run stage
                      </Button>
                    )}
                    {canManage && status === 'completed' && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void runStage(stage, { rerun: true })}
                        disabled={anyStageRunning || runningStage !== null}
                      >
                        {runningStage === stage ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <RefreshCw className="h-4 w-4" />
                        )}
                        Re-run stage
                      </Button>
                    )}
                  </li>
                )
              })}
            </ol>

            {planType === 'modernize' && (
              <div className="space-y-3 rounded-md border p-3">
                <p className="text-xs font-medium uppercase text-muted-foreground">
                  Architecture targets ({targets.length})
                </p>
                {targets.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Run Architecture to declare components, then register GitHub URLs before Push.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {targets.map((t) => (
                      <li key={t.slug} className="flex flex-wrap items-center gap-2 text-sm">
                        <code className="text-xs">{t.slug}</code>
                        {t.role && (
                          <Badge variant="outline" className="text-xs capitalize">
                            {t.role}
                          </Badge>
                        )}
                        <Badge variant="outline" className="text-xs capitalize">
                          {t.clone_status || 'pending'}
                        </Badge>
                        {t.github_url ? (
                          <span className="truncate text-xs text-muted-foreground">{t.github_url}</span>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 text-xs"
                            onClick={() => setRegSlug(t.slug)}
                          >
                            Set URL
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}

                {canManage && (
                  <div className="grid gap-2 border-t pt-3 sm:grid-cols-3">
                    <div className="space-y-1">
                      <Label className="text-xs">Component slug</Label>
                      <Input
                        placeholder="api-service"
                        value={regSlug}
                        onChange={(e) => setRegSlug(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1 sm:col-span-2">
                      <Label className="text-xs">GitHub URL</Label>
                      <Input
                        placeholder="https://github.com/org/new-api"
                        value={regUrl}
                        onChange={(e) => setRegUrl(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Branch</Label>
                      <Input value={regBranch} onChange={(e) => setRegBranch(e.target.value)} />
                    </div>
                    <div className="flex items-end sm:col-span-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void registerTarget()}
                        disabled={registering}
                      >
                        {registering ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                        Register / clone target
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {manifest?.push?.branch && (
              <p className="text-sm text-muted-foreground">
                Branch: <code className="text-xs">{manifest.push.branch}</code>
                {manifest.push.commit_sha && (
                  <>
                    {' '}
                    · commit <code className="text-xs">{manifest.push.commit_sha.slice(0, 8)}</code>
                  </>
                )}
              </p>
            )}

            {pushTargets && pushTargets.length > 0 && (
              <ul className="space-y-1 text-sm">
                {pushTargets.map((p) => (
                  <li key={p.slug} className="flex flex-wrap items-center gap-2">
                    <code className="text-xs">{p.slug}</code>
                    {p.skipped ? (
                      <span className="text-xs text-muted-foreground">{p.reason}</span>
                    ) : (
                      <>
                        {p.branch && <span className="text-xs text-muted-foreground">{p.branch}</span>}
                        {p.pr?.url && (
                          <Button size="sm" variant="outline" asChild>
                            <a href={p.pr.url} target="_blank" rel="noopener noreferrer">
                              <ExternalLink className="h-4 w-4" />
                              PR #{p.pr.number}
                            </a>
                          </Button>
                        )}
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {manifest?.pr?.url && (
              <Button size="sm" variant="outline" asChild>
                <a href={manifest.pr.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-4 w-4" />
                  Pull request #{manifest.pr.number}
                </a>
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
