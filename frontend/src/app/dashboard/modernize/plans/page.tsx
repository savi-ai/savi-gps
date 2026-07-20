'use client'

import { useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import { useModernizePlans } from '@/hooks/queries/useModernize'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Plus, ArrowRight, ClipboardList } from 'lucide-react'

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

  const queryParams = useMemo(() => {
    const params: Record<string, string> = {}
    const applicationId = searchParams.get('application_id')
    const bundleId = searchParams.get('bundle_id')
    if (applicationId) params.application_id = applicationId
    if (bundleId) params.bundle_id = bundleId
    if (stateFilter && stateFilter !== 'all' && stateFilter !== 'active') {
      params.state = stateFilter
    }
    return params
  }, [searchParams, stateFilter])

  const enabled = hasCapability('modernize') && hasPermission('can_manage_modernize')
  const { data: rawPlans = [], isLoading: loading } = useModernizePlans(queryParams, enabled)

  const plans = useMemo(() => {
    if (stateFilter !== 'active') return rawPlans
    return rawPlans.filter((p) => !['complete', 'cancelled'].includes(p.state))
  }, [rawPlans, stateFilter])

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
            Modernization plans linked to repositories and applications
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
            <p className="text-sm text-muted-foreground">No modernization plans match this filter.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {plans.map((plan) => (
            <Card key={plan.id} className="transition-colors hover:border-primary/40">
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <CardTitle className="text-base">{plan.title}</CardTitle>
                    <CardDescription>
                      {plan.repository_name || plan.repository_id}
                    </CardDescription>
                  </div>
                  <Badge variant="outline" className="capitalize">
                    {STATE_LABELS[plan.state] || plan.state}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  {plan.updated_at
                    ? `Updated ${new Date(plan.updated_at).toLocaleDateString()}`
                    : 'No update timestamp'}
                </p>
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/dashboard/modernize/plans/${plan.id}`}>
                    View plan
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
