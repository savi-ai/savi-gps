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
import { ArrowLeft, ExternalLink, Loader2, Rocket, Save } from 'lucide-react'
import ReadinessPanel, { type ReadinessData } from '@/components/modernize/ReadinessPanel'

import PillarBreadcrumb from '@/components/navigation/PillarBreadcrumb'

interface Plan {
  id: string
  title: string
  state: string
  repository_id: string
  repository_name?: string
  plan_md?: string
  assessment_json?: ReadinessData
  spawned_project_id?: string | null
  application?: { id: string; name: string; role?: string | null } | null
  source_application_id?: string | null
  plan_bundle_id?: string | null
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

  const spawnBuild = async () => {
    setSpawning(true)
    setError(null)
    try {
      const res = await apiClient.post(`/api/v1/modernize/plans/${planId}/spawn-build`)
      router.push(`/dashboard/projects/${res.data.project.id}?spawned=1&from_plan=${planId}`)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to spawn Build project')
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

      {plan.application && (
        <Card className="border-l-4 border-violet-500 bg-muted/20">
          <CardContent className="flex flex-wrap items-center gap-2 py-3 text-sm">
            <span className="text-muted-foreground">Lineage:</span>
            <Link
              href={`/dashboard/intelligence/applications/${plan.application.id}`}
              className="font-medium text-primary hover:underline"
            >
              {plan.application.name}
            </Link>
            <span className="text-muted-foreground">→</span>
            <Link
              href={`/dashboard/intelligence/repositories/${plan.repository_id}`}
              className="font-medium text-primary hover:underline"
            >
              {plan.repository_name || 'Repository'}
            </Link>
            {plan.spawned_project_id && (
              <>
                <span className="text-muted-foreground">→</span>
                <Link
                  href={`/dashboard/projects/${plan.spawned_project_id}`}
                  className="font-medium text-primary hover:underline"
                >
                  Build project
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
            Repository:{' '}
            <Link
              href={`/dashboard/intelligence/repositories/${plan.repository_id}`}
              className="font-medium text-primary hover:underline"
            >
              {plan.repository_name || plan.repository_id}
            </Link>
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="outline" className="capitalize">{plan.state}</Badge>
            {plan.spawned_project_id && (
              <Badge variant="secondary">Build project linked</Badge>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {plan.state === 'assessing' && (
            <Button
              size="sm"
              onClick={() => savePlan({ state: 'planned' })}
              disabled={saving}
            >
              Mark as planned
            </Button>
          )}
          {plan.state === 'planned' && !plan.spawned_project_id && (
            <Button size="sm" onClick={spawnBuild} disabled={spawning}>
              {spawning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
              Spawn Build project
            </Button>
          )}
          {plan.spawned_project_id && (
            <Button size="sm" variant="outline" asChild>
              <Link href={`/dashboard/projects/${plan.spawned_project_id}`}>
                <ExternalLink className="h-4 w-4" />
                Open Build project
              </Link>
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
          <span key={s} className={i <= stateIndex ? 'font-medium text-foreground capitalize' : 'capitalize'}>
            {s}{i < STATE_FLOW.length - 1 ? ' → ' : ''}
          </span>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Plan document</CardTitle>
            <CardDescription>Goals, checklist, and migration notes — editable while assessing or planned</CardDescription>
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
          <ReadinessPanel
            repoId={plan.repository_id}
            repoStatus="ready"
            canManage={false}
          />
        </div>
      </div>
    </div>
  )
}
