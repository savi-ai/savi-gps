'use client'

import { useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import { useModernizePlans } from '@/hooks/queries/useModernize'
import { useQueryClient } from '@tanstack/react-query'
import apiClient from '@/lib/axios'
import { queryKeys } from '@/lib/queryClient'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Plus, ArrowRight, ClipboardList, Wrench, Layers, Trash2, Loader2 } from 'lucide-react'

const STATE_LABELS: Record<string, string> = {
  assessing: 'Assessing',
  planned: 'Planned',
  executing: 'Executing',
  verifying: 'Verifying',
  complete: 'Complete',
  cancelled: 'Cancelled',
}

export default function ModernizePlansPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { hasCapability, hasPermission } = useAuth()
  const [stateFilter, setStateFilter] = useState<string>('active')
  const [typeFilter, setTypeFilter] = useState<string>('all')

  const queryParams = useMemo(() => {
    const params: Record<string, string> = {}
    const applicationId = searchParams.get('application_id')
    const bundleId = searchParams.get('bundle_id')
    if (applicationId) params.application_id = applicationId
    if (bundleId) params.bundle_id = bundleId
    if (stateFilter && stateFilter !== 'all' && stateFilter !== 'active') {
      params.state = stateFilter
    }
    if (typeFilter === 'fix' || typeFilter === 'modernize') {
      params.plan_type = typeFilter
    }
    return params
  }, [searchParams, stateFilter, typeFilter])

  const enabled = hasCapability('modernize') && hasPermission('can_manage_modernize')
  const { data: rawPlans = [], isLoading: loading } = useModernizePlans(queryParams, enabled)
  const queryClient = useQueryClient()
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const plans = useMemo(() => {
    if (stateFilter !== 'active') return rawPlans
    return rawPlans.filter((p) => !['complete', 'cancelled'].includes(p.state))
  }, [rawPlans, stateFilter])

  const deletePlan = async (planId: string, title: string) => {
    if (!window.confirm(`Delete plan "${title}"? This cannot be undone.`)) return
    setDeletingId(planId)
    try {
      await apiClient.delete(`/api/v1/modernize/plans/${planId}`)
      await queryClient.invalidateQueries({ queryKey: queryKeys.modernize.plans(queryParams) })
    } finally {
      setDeletingId(null)
    }
  }

  if (!enabled) {
    router.push('/dashboard')
    return null
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Active plans</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            <strong>Fix</strong> plans remediate a member repo in place.{' '}
            <strong>Modernize</strong> plans build new target repos from architecture.
          </p>
        </div>
        <Button asChild>
          <Link href="/dashboard/modernize/assessments">
            <Plus className="h-4 w-4" />
            New assessment
          </Link>
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(['all', 'fix', 'modernize'] as const).map((t) => (
          <Button
            key={t}
            variant={typeFilter === t ? 'default' : 'outline'}
            size="sm"
            onClick={() => setTypeFilter(t)}
          >
            {t === 'all' ? 'All types' : t === 'fix' ? 'Fix plans' : 'Modernize plans'}
          </Button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {['active', 'all', 'assessing', 'planned', 'executing', 'complete'].map((state) => (
          <Button
            key={state}
            variant={stateFilter === state ? 'default' : 'outline'}
            size="sm"
            onClick={() => setStateFilter(state)}
          >
            {state === 'active' ? 'Active' : STATE_LABELS[state] || state}
          </Button>
        ))}
      </div>

      {loading ? (
        <Skeleton className="h-48 w-full" />
      ) : plans.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <ClipboardList className="h-10 w-10 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No {typeFilter === 'fix' ? 'fix' : typeFilter === 'modernize' ? 'modernize' : ''}{' '}
              plans match this filter.
            </p>
            <p className="max-w-md text-xs text-muted-foreground">
              Run a repository assessment to create a fix plan, or an application assessment for a
              modernize plan.
            </p>
            <Button variant="outline" size="sm" asChild>
              <Link href="/dashboard/modernize/assessments">Go to assessments</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {plans.map((plan) => {
            const isFix = (plan.plan_type || 'modernize') === 'fix'
            return (
              <Card key={plan.id} className="transition-colors hover:border-primary/40">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <CardTitle className="flex items-center gap-2 text-base">
                        {isFix ? (
                          <Wrench className="h-4 w-4 text-sky-600" />
                        ) : (
                          <Layers className="h-4 w-4 text-violet-600" />
                        )}
                        {plan.title}
                      </CardTitle>
                      <CardDescription>
                        {plan.repository_name ||
                          (isFix ? plan.repository_id : 'Application-scoped modernize')}
                      </CardDescription>
                    </div>
                    <div className="flex flex-wrap justify-end gap-1">
                      <Badge
                        variant={isFix ? 'secondary' : 'default'}
                        className="capitalize"
                      >
                        {isFix ? 'Fix' : 'Modernize'}
                      </Badge>
                      <Badge variant="outline" className="capitalize">
                        {STATE_LABELS[plan.state] || plan.state}
                      </Badge>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="flex items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    {plan.updated_at
                      ? `Updated ${new Date(plan.updated_at).toLocaleDateString()}`
                      : 'No update timestamp'}
                    {isFix
                      ? ' · Stages: Fix → Code → Test → Push → PR'
                      : ' · Stages: Requirements → … → Push'}
                  </p>
                  <div className="flex shrink-0 items-center gap-1">
                    {plan.can_delete && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        disabled={deletingId === plan.id}
                        onClick={() => void deletePlan(plan.id, plan.title)}
                        aria-label={`Delete ${plan.title}`}
                      >
                        {deletingId === plan.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" asChild>
                      <Link href={`/dashboard/modernize/plans/${plan.id}`}>
                        View plan
                        <ArrowRight className="h-4 w-4" />
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
