'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, Inbox, Loader2, RefreshCw } from 'lucide-react'

interface ActivityRow {
  savi_id: string
  savi_name: string
  savi_status: string
  team_id: string
  team_name: string
  last_work_item_id?: string | null
  last_work_title?: string | null
  last_work_state?: string | null
  orchestrator_phase?: string | null
  orchestrator_error?: string | null
  orchestrator_tokens?: number
  pr_url?: string | null
  updated_at?: string | null
  inbox_path: string
}

export default function SaviActivityAdminPage() {
  const router = useRouter()
  const { hasPermission, hasRole } = useAuth()
  const [items, setItems] = useState<ActivityRow[]>([])
  const [loading, setLoading] = useState(true)
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canManage =
    hasPermission('can_manage_teams') ||
    hasPermission('can_manage_tenant_config') ||
    hasRole('admin')

  const load = useCallback(async () => {
    const res = await apiClient.get('/api/v1/teams/savi-activity', {
      params: { errors_only: errorsOnly },
    })
    setItems(res.data.items || [])
  }, [errorsOnly])

  useEffect(() => {
    if (!canManage) {
      router.push('/dashboard')
      return
    }
    ;(async () => {
      try {
        setLoading(true)
        setError(null)
        await load()
      } catch {
        setError('Failed to load Savi activity')
      } finally {
        setLoading(false)
      }
    })()
  }, [canManage, router, load])

  if (!canManage) return null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            href="/dashboard/admin/teams"
            className="mb-2 inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="mr-1 h-3.5 w-3.5" />
            Teams
          </Link>
          <h1 className="text-2xl font-bold tracking-tight">Savi activity</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Last work item and orchestrator status per Savi (Beta B4).
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={errorsOnly ? 'default' : 'outline'}
            onClick={() => setErrorsOnly((v) => !v)}
          >
            {errorsOnly ? 'Showing errors' : 'Errors only'}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              setLoading(true)
              try {
                await load()
              } finally {
                setLoading(false)
              }
            }}
          >
            {loading ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            )}
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <Skeleton className="h-40 w-full" />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No Savi activity yet.</p>
      ) : (
        <div className="grid gap-3">
          {items.map((row) => (
            <Card key={row.savi_id}>
              <CardHeader className="pb-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="text-base">
                    {row.team_name} · {row.savi_name}
                  </CardTitle>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="secondary">{row.savi_status}</Badge>
                    {row.orchestrator_phase && (
                      <Badge variant="outline">{row.orchestrator_phase}</Badge>
                    )}
                    {row.last_work_state && (
                      <Badge variant="outline">{row.last_work_state}</Badge>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {row.last_work_title ? (
                  <p>
                    <span className="text-muted-foreground">Last work:</span>{' '}
                    {row.last_work_title}
                  </p>
                ) : (
                  <p className="text-muted-foreground">No work items yet.</p>
                )}
                {typeof row.orchestrator_tokens === 'number' &&
                  row.orchestrator_tokens > 0 && (
                    <p className="text-muted-foreground">
                      Tokens (rough): {row.orchestrator_tokens}
                    </p>
                  )}
                {row.orchestrator_error && (
                  <p className="text-destructive">{row.orchestrator_error}</p>
                )}
                {row.pr_url && (
                  <a
                    href={row.pr_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary underline-offset-2 hover:underline"
                  >
                    Open PR
                  </a>
                )}
                <div>
                  <Link href={row.inbox_path}>
                    <Button size="sm" variant="outline">
                      <Inbox className="mr-1.5 h-3.5 w-3.5" />
                      Inbox
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
