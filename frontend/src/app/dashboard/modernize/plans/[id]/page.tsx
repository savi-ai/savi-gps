'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ArrowLeft, ExternalLink, Loader2, Rocket, Save, Trash2 } from 'lucide-react'
import ReadinessPanel, { type ReadinessData } from '@/components/modernize/ReadinessPanel'
import AgentEffortCard from '@/components/modernize/AgentEffortCard'
import ExecutionPanel from '@/components/modernize/ExecutionPanel'

import PillarBreadcrumb from '@/components/navigation/PillarBreadcrumb'

interface Plan {
  id: string
  title: string
  state: string
  repository_id?: string | null
  repository_name?: string
  plan_md?: string
  plan_type?: string
  assessment_run_id?: string | null
  assessment_json?: ReadinessData
  spawned_project_id?: string | null
  application?: { id: string; name: string; role?: string | null } | null
  source_application_id?: string | null
  plan_bundle_id?: string | null
  can_delete?: boolean
}

const STATE_FLOW = ['assessing', 'planned', 'executing', 'verifying', 'complete']

export default function ModernizePlanDetailPage() {
  const params = useParams()
  const router = useRouter()
  const planId = params?.id as string
  const { hasCapability, hasPermission } = useAuth()
  const [plan, setPlan] = useState<Plan | null>(null)
  const [planMd, setPlanMd] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [spawning, setSpawning] = useState(false)
  const [spawnOpen, setSpawnOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [targetUrl, setTargetUrl] = useState('')
  const [targetBranch, setTargetBranch] = useState('main')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      const res = await apiClient.get(`/api/v1/modernize/plans/${planId}`)
      setPlan(res.data)
      setPlanMd(res.data.plan_md || '')
      setError(null)
    } catch {
      setPlan(null)
      setError('Plan not found')
    } finally {
      setLoading(false)
    }
  }, [planId])

  useEffect(() => {
    if (!hasCapability('modernize') || !hasPermission('can_manage_modernize')) {
      router.push('/dashboard')
      return
    }
    if (planId) load()
  }, [planId, hasCapability, hasPermission, router, load])

  const savePlan = async (updates: { plan_md?: string; state?: string }) => {
    setSaving(true)
    setError(null)
    try {
      const res = await apiClient.patch(`/api/v1/modernize/plans/${planId}`, {
        plan_md: updates.plan_md ?? planMd,
        state: updates.state,
      })
      setPlan(res.data)
      setPlanMd(res.data.plan_md || '')
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to save plan')
    } finally {
      setSaving(false)
    }
  }

  const canStartModernization =
    plan?.state === 'planned' &&
    !plan.spawned_project_id &&
    (hasCapability('build') || hasCapability('modernize'))

  const isFixPlan = (plan?.plan_type || 'modernize') === 'fix'
  const canDelete =
    Boolean(plan?.can_delete) ||
    Boolean(
      plan &&
        !plan.spawned_project_id &&
        ['assessing', 'planned', 'cancelled'].includes(plan.state)
    )

  const deletePlan = async () => {
    setDeleting(true)
    setError(null)
    try {
      await apiClient.delete(`/api/v1/modernize/plans/${planId}`)
      setDeleteOpen(false)
      router.push('/dashboard/modernize/plans')
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to delete plan')
      setDeleteOpen(false)
    } finally {
      setDeleting(false)
    }
  }

  const spawnBuild = async () => {
    setSpawning(true)
    setError(null)
    try {
      const payload: { target_github_url?: string; target_branch: string } = {
        target_branch: targetBranch.trim() || 'main',
      }
      if (!isFixPlan && targetUrl.trim()) {
        payload.target_github_url = targetUrl.trim()
      }
      if (isFixPlan) {
        // fix: omit URL — backend defaults to source repo
      } else if (!targetUrl.trim()) {
        // modernize: architecture defines targets; optional seed URL
      }
      const res = await apiClient.post(`/api/v1/modernize/plans/${planId}/spawn-build`, {
        ...payload,
        target_github_url: isFixPlan ? undefined : targetUrl.trim() || undefined,
      })
      setSpawnOpen(false)
      // Stay on plan page so execution panel is available for both tracks
      await load()
      setSpawning(false)
      if (!isFixPlan && res.data?.project?.id) {
        // optional: user can still open project from badge
      }
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to start modernization')
      setSpawning(false)
    }
  }

  if (!hasCapability('modernize') || !hasPermission('can_manage_modernize')) {
    return null
  }

  if (loading) return <Skeleton className="h-48 w-full" />

  if (!plan) {
    return (
      <div className="py-12 text-center">
        <p className="text-muted-foreground">{error || 'Plan not found'}</p>
        <Button variant="link" onClick={() => router.push('/dashboard/modernize/plans')}>
          Back to plans
        </Button>
      </div>
    )
  }

  const stateIndex = STATE_FLOW.indexOf(plan.state)

  return (
    <div className="space-y-6">
      <PillarBreadcrumb
        items={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Modernize', href: '/dashboard/modernize/plans' },
          { label: 'Plans', href: '/dashboard/modernize/plans' },
          { label: plan.title },
        ]}
      />

      {(plan.application || plan.source_application_id) && (
        <Card className="border-l-4 border-violet-500 bg-muted/20">
          <CardContent className="flex flex-wrap items-center gap-2 py-3 text-sm">
            <span className="text-muted-foreground">Lineage:</span>
            <Link
              href={`/dashboard/intelligence/applications/${plan.application?.id || plan.source_application_id}`}
              className="font-medium text-primary hover:underline"
            >
              {plan.application?.name || 'Application'}
            </Link>
            {plan.repository_id && (
              <>
                <span className="text-muted-foreground">→</span>
                <Link
                  href={`/dashboard/intelligence/repositories/${plan.repository_id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {plan.repository_name || 'Repository'}
                </Link>
              </>
            )}
            {!plan.repository_id && (
              <Badge variant="outline" className="text-xs">
                app-scoped
              </Badge>
            )}
            {plan.spawned_project_id && (
              <>
                <span className="text-muted-foreground">→</span>
                <Link
                  href={`/dashboard/projects/${plan.spawned_project_id}`}
                  className="font-medium text-primary hover:underline"
                >
                  Modernization project
                </Link>
              </>
            )}
            {plan.plan_bundle_id && plan.application && (
              <>
                <span className="text-muted-foreground">·</span>
                <Link
                  href={`/dashboard/modernize/plans?application_id=${plan.application.id}&bundle_id=${plan.plan_bundle_id}`}
                  className="text-xs text-primary hover:underline"
                >
                  View plan bundle
                </Link>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <Button variant="ghost" size="sm" className="-ml-2" asChild>
        <Link href="/dashboard/modernize/plans">
          <ArrowLeft className="h-4 w-4" />
          Plans
        </Link>
      </Button>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{plan.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {plan.repository_id ? (
              <>
                Repository:{' '}
                <Link
                  href={`/dashboard/intelligence/repositories/${plan.repository_id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {plan.repository_name || plan.repository_id}
                </Link>
              </>
            ) : plan.application || plan.source_application_id ? (
              <>
                Application:{' '}
                <Link
                  href={`/dashboard/intelligence/applications/${plan.application?.id || plan.source_application_id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {plan.application?.name || plan.source_application_id}
                </Link>
                <span className="ml-2 text-xs">(app-scoped — no member repo target)</span>
              </>
            ) : (
              'No repository linked'
            )}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="outline" className="capitalize">
              {plan.state}
            </Badge>
            <Badge variant={isFixPlan ? 'default' : 'secondary'} className="capitalize">
              {plan.plan_type || 'modernize'}
            </Badge>
            {plan.spawned_project_id && (
              <Badge variant="secondary">Execution project linked</Badge>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {plan.state === 'assessing' && (
            <Button size="sm" onClick={() => savePlan({ state: 'planned' })} disabled={saving}>
              Mark as planned
            </Button>
          )}
          {canStartModernization && (
            <Button size="sm" onClick={() => setSpawnOpen(true)} disabled={spawning}>
              {spawning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
              {isFixPlan ? 'Start fix execution' : 'Start modernization'}
            </Button>
          )}
          {plan.spawned_project_id && (
            <Button size="sm" variant="outline" asChild>
              <Link href={`/dashboard/projects/${plan.spawned_project_id}`}>
                <ExternalLink className="h-4 w-4" />
                Open project
              </Link>
            </Button>
          )}
          {canDelete && (
            <Button
              size="sm"
              variant="outline"
              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 className="h-4 w-4" />
              Delete
            </Button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
        {STATE_FLOW.map((s, i) => (
          <span
            key={s}
            className={i <= stateIndex ? 'font-medium text-foreground capitalize' : 'capitalize'}
          >
            {s}
            {i < STATE_FLOW.length - 1 ? ' → ' : ''}
          </span>
        ))}
      </div>

      {(plan.assessment_json?.agent_effort || plan.assessment_json?.synthesis) && (
        <AgentEffortCard
          effort={plan.assessment_json.agent_effort}
          synthesis={plan.assessment_json.synthesis}
        />
      )}

      {(plan.spawned_project_id || plan.state === 'executing') && (
        <ExecutionPanel
          planId={plan.id}
          planType={plan.plan_type || 'modernize'}
          spawnedProjectId={plan.spawned_project_id}
          canManage
        />
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Plan document</CardTitle>
            <CardDescription>
              Goals, checklist, and migration notes — editable while assessing or planned
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              value={planMd}
              onChange={(e) => setPlanMd(e.target.value)}
              rows={16}
              className="font-mono text-sm"
              disabled={!['assessing', 'planned'].includes(plan.state)}
            />
            {['assessing', 'planned'].includes(plan.state) && (
              <Button size="sm" onClick={() => savePlan({})} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Save plan
              </Button>
            )}
          </CardContent>
        </Card>

        <div className="lg:col-span-2">
          {plan.repository_id ? (
            <ReadinessPanel repoId={plan.repository_id} repoStatus="ready" canManage={false} />
          ) : plan.source_application_id || plan.application?.id ? (
            <p className="text-sm text-muted-foreground">
              App-scoped plan — assessment is on the application. Open{' '}
              <Link
                href={`/dashboard/intelligence/applications/${plan.application?.id || plan.source_application_id}`}
                className="text-primary hover:underline"
              >
                {plan.application?.name || 'application'}
              </Link>{' '}
              for member readiness.
            </p>
          ) : null}
        </div>
      </div>

      <Dialog open={spawnOpen} onOpenChange={setSpawnOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{isFixPlan ? 'Start fix execution' : 'Start modernization'}</DialogTitle>
            <DialogDescription>
              {isFixPlan ? (
                <>
                  Initializes the execution workspace and clones the member repo into{' '}
                  <code className="text-xs">source/</code>. Run Fix → Code → Test → Push → PR from
                  the execution panel (same repo, Copilot gates).
                </>
              ) : (
                <>
                  Initializes the app execution workspace under{' '}
                  <code className="text-xs">applications/…/executions/</code>. Architecture defines
                  components → <code className="text-xs">targets/{'{component}'}/</code>. Optional:
                  seed one GitHub URL now, or register remotes after Architecture. Stages:
                  Requirements → Tasks → Architecture → Code → Test → Push.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {!isFixPlan && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="target-url">Seed target GitHub URL (optional)</Label>
                  <Input
                    id="target-url"
                    placeholder="https://github.com/org/new-api (optional)"
                    value={targetUrl}
                    onChange={(e) => setTargetUrl(e.target.value)}
                    autoFocus
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="target-branch">Base branch</Label>
                  <Input
                    id="target-branch"
                    placeholder="main"
                    value={targetBranch}
                    onChange={(e) => setTargetBranch(e.target.value)}
                  />
                </div>
              </>
            )}
            {isFixPlan && (
              <p className="text-sm text-muted-foreground">
                Push target: same repository ({plan.repository_name || plan.repository_id}).
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setSpawnOpen(false)} disabled={spawning}>
              Cancel
            </Button>
            <Button onClick={() => void spawnBuild()} disabled={spawning}>
              {spawning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
              {isFixPlan ? 'Initialize workspace' : 'Initialize workspace'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Delete plan?</DialogTitle>
            <DialogDescription>
              Permanently remove <strong>{plan.title}</strong>. Only plans that have not started
              execution can be deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteOpen(false)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => void deletePlan()} disabled={deleting}>
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete plan
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
