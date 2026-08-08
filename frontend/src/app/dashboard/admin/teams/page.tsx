'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Bot, Inbox, Loader2, Plug, Plus, Users, LayoutGrid, Trash2 } from 'lucide-react'

interface TeamSummary {
  id: string
  name: string
  slug: string
  description?: string | null
  is_default?: boolean
  member_count: number
  application_count: number
}

interface SaviInstance {
  id: string
  name: string
  slug: string
  status: string
  machine_user?: {
    id: string
    username: string
    email: string
    is_active: boolean
  } | null
  execution_model?: string
}

interface TeamDetail extends TeamSummary {
  members: Array<{
    user_id: string
    username: string
    full_name?: string | null
    role: string
  }>
  applications: Array<{
    id: string
    name: string
    access: string
    origin?: string
  }>
  savi_instances?: SaviInstance[]
}

interface AppOption {
  id: string
  name: string
}

export default function AdminTeamsPage() {
  const router = useRouter()
  const { hasPermission, hasRole } = useAuth()
  const [teams, setTeams] = useState<TeamSummary[]>([])
  const [selected, setSelected] = useState<TeamDetail | null>(null)
  const [apps, setApps] = useState<AppOption[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [attachAppId, setAttachAppId] = useState('')

  const canManage =
    hasPermission('can_manage_teams') || hasPermission('can_manage_tenant_config')

  const loadTeams = useCallback(async () => {
    const res = await apiClient.get('/api/v1/teams')
    setTeams(res.data.teams || [])
  }, [])

  const loadDetail = useCallback(async (teamId: string) => {
    const res = await apiClient.get(`/api/v1/teams/${teamId}`)
    setSelected(res.data)
  }, [])

  useEffect(() => {
    if (!canManage || !hasRole('admin')) {
      router.push('/dashboard')
      return
    }
    ;(async () => {
      try {
        setLoading(true)
        await apiClient.post('/api/v1/teams/ensure-default')
        await loadTeams()
        const appsRes = await apiClient.get('/api/v1/intelligence/applications')
        setApps(
          (appsRes.data.applications || []).map((a: AppOption) => ({
            id: a.id,
            name: a.name,
          }))
        )
      } catch {
        setError('Failed to load teams')
      } finally {
        setLoading(false)
      }
    })()
  }, [canManage, hasRole, router, loadTeams])

  const createTeam = async () => {
    if (!newName.trim()) return
    setSaving(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v1/teams', { name: newName.trim() })
      setNewName('')
      await loadTeams()
      setSelected(res.data)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to create team')
    } finally {
      setSaving(false)
    }
  }

  const attachApp = async () => {
    if (!selected || !attachAppId) return
    setSaving(true)
    setError(null)
    try {
      const res = await apiClient.post(`/api/v1/teams/${selected.id}/applications`, {
        application_id: attachAppId,
        access: 'own',
      })
      setSelected(res.data)
      setAttachAppId('')
      await loadTeams()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to attach application')
    } finally {
      setSaving(false)
    }
  }

  const detachApp = async (applicationId: string) => {
    if (!selected) return
    setSaving(true)
    try {
      await apiClient.delete(`/api/v1/teams/${selected.id}/applications/${applicationId}`)
      await loadDetail(selected.id)
      await loadTeams()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to detach application')
    } finally {
      setSaving(false)
    }
  }

  const activeSavi = selected?.savi_instances?.find(
    (s) => s.status === 'active' || s.status === 'pending'
  )
  const anySavi = selected?.savi_instances?.[0]

  const rosterSavi = async () => {
    if (!selected) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/teams/${selected.id}/savi`, {})
      await loadDetail(selected.id)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to roster Savi')
    } finally {
      setSaving(false)
    }
  }

  const disableSavi = async (saviId: string) => {
    if (!selected) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/teams/${selected.id}/savi/${saviId}/disable`)
      await loadDetail(selected.id)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to disable Savi')
    } finally {
      setSaving(false)
    }
  }

  const enableSavi = async (saviId: string) => {
    if (!selected) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/teams/${selected.id}/savi/${saviId}/enable`)
      await loadDetail(selected.id)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to enable Savi')
    } finally {
      setSaving(false)
    }
  }

  const deprovisionSavi = async (saviId: string) => {
    if (!selected) return
    if (!confirm('Deprovision this Savi? Machine identity, company identity link, and coding-agent seat will be disabled.')) return
    setSaving(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/teams/${selected.id}/savi/${saviId}/deprovision`)
      await loadDetail(selected.id)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to deprovision Savi')
    } finally {
      setSaving(false)
    }
  }

  if (!canManage) return null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Teams</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            ACL and Savi roster boundary (ADR 0007). Applications attach to teams; enable{' '}
            <code className="text-xs">TEAM_ACL_ENFORCED=true</code> to require membership for
            mutations.
          </p>
        </div>
        <Link href="/dashboard/admin/savi-activity">
          <Button size="sm" variant="outline">
            <Bot className="mr-1.5 h-3.5 w-3.5" />
            Savi activity
          </Button>
        </Link>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Teams</CardTitle>
            <CardDescription>Create teams and open details</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-2">
              <Input
                placeholder="New team name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                disabled={saving}
              />
              <Button onClick={createTeam} disabled={saving || !newName.trim()}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Create
              </Button>
            </div>
            {loading ? (
              <Skeleton className="h-24 w-full" />
            ) : (
              <ul className="divide-y rounded-md border">
                {teams.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      className="flex w-full items-center justify-between px-3 py-3 text-left hover:bg-muted/50"
                      onClick={() => loadDetail(t.id)}
                    >
                      <div>
                        <p className="text-sm font-medium">
                          {t.name}
                          {t.is_default && (
                            <Badge variant="secondary" className="ml-2 text-xs">
                              default
                            </Badge>
                          )}
                        </p>
                        <p className="text-xs text-muted-foreground">{t.slug}</p>
                      </div>
                      <div className="flex gap-2 text-xs text-muted-foreground">
                        <span className="inline-flex items-center gap-1">
                          <Users className="h-3 w-3" />
                          {t.member_count}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <LayoutGrid className="h-3 w-3" />
                          {t.application_count}
                        </span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {selected ? selected.name : 'Team detail'}
            </CardTitle>
            <CardDescription>
              {selected
                ? 'Members, applications, and Savi roster for this team'
                : 'Select a team to manage applications and Savi'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!selected ? (
              <p className="text-sm text-muted-foreground">No team selected.</p>
            ) : (
              <>
                <div>
                  <Label className="text-xs text-muted-foreground">Savi Teammate</Label>
                  <div className="mt-1 rounded-md border px-3 py-3">
                    {(selected.savi_instances || []).length === 0 ? (
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm text-muted-foreground">
                          No Savi rostered. One active Savi per team in V1.
                        </p>
                        <Button size="sm" onClick={rosterSavi} disabled={saving}>
                          <Bot className="mr-1.5 h-3.5 w-3.5" />
                          Roster Savi
                        </Button>
                      </div>
                    ) : (
                      <ul className="space-y-3">
                        {(selected.savi_instances || []).map((s) => (
                          <li key={s.id} className="space-y-2">
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <p className="text-sm font-medium">{s.name}</p>
                                <p className="text-xs text-muted-foreground">
                                  {s.slug}
                                  {s.machine_user && (
                                    <>
                                      {' '}
                                      · machine{' '}
                                      <code className="text-xs">@{s.machine_user.username}</code>
                                    </>
                                  )}
                                </p>
                              </div>
                              <Badge
                                variant={s.status === 'active' ? 'default' : 'secondary'}
                                className="capitalize"
                              >
                                {s.status}
                              </Badge>
                            </div>
                            <div className="flex flex-wrap gap-2">
                              <Button size="sm" variant="secondary" asChild>
                                <Link href={`/dashboard/admin/teams/${selected.id}/inbox`}>
                                  <Inbox className="mr-1.5 h-3.5 w-3.5" />
                                  Inbox
                                </Link>
                              </Button>
                              <Button size="sm" variant="outline" asChild>
                                <Link href={`/dashboard/admin/teams/${selected.id}/connectors`}>
                                  <Plug className="mr-1.5 h-3.5 w-3.5" />
                                  Connectors
                                </Link>
                              </Button>
                              {s.status === 'active' || s.status === 'pending' ? (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => disableSavi(s.id)}
                                  disabled={saving}
                                >
                                  Disable
                                </Button>
                              ) : (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => enableSavi(s.id)}
                                  disabled={saving}
                                >
                                  Enable
                                </Button>
                              )}
                              <Button
                                size="sm"
                                variant="ghost"
                                className="text-destructive"
                                onClick={() => deprovisionSavi(s.id)}
                                disabled={saving}
                              >
                                Deprovision
                              </Button>
                            </div>
                          </li>
                        ))}
                        {!activeSavi && anySavi && (
                          <li>
                            <Button size="sm" onClick={rosterSavi} disabled={saving}>
                              <Bot className="mr-1.5 h-3.5 w-3.5" />
                              Roster new Savi
                            </Button>
                          </li>
                        )}
                      </ul>
                    )}
                  </div>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Members</Label>
                  <ul className="mt-1 divide-y rounded-md border">
                    {selected.members.map((m) => (
                      <li key={m.user_id} className="flex justify-between px-3 py-2 text-sm">
                        <span>
                          {m.full_name || m.username}
                          <span className="ml-2 text-xs text-muted-foreground">@{m.username}</span>
                        </span>
                        <Badge variant="outline" className="capitalize">
                          {m.role}
                        </Badge>
                      </li>
                    ))}
                    {selected.members.length === 0 && (
                      <li className="px-3 py-2 text-sm text-muted-foreground">No members yet</li>
                    )}
                  </ul>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Applications</Label>
                  <ul className="mt-1 divide-y rounded-md border">
                    {selected.applications.map((a) => (
                      <li
                        key={a.id}
                        className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
                      >
                        <Link
                          href={`/dashboard/intelligence/applications/${a.id}`}
                          className="font-medium hover:underline"
                        >
                          {a.name}
                        </Link>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="capitalize">
                            {a.access}
                          </Badge>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-destructive"
                            onClick={() => detachApp(a.id)}
                            disabled={saving}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </li>
                    ))}
                    {selected.applications.length === 0 && (
                      <li className="px-3 py-2 text-sm text-muted-foreground">
                        No applications linked
                      </li>
                    )}
                  </ul>
                  <div className="mt-2 flex gap-2">
                    <select
                      className="h-9 flex-1 rounded-md border bg-background px-2 text-sm"
                      value={attachAppId}
                      onChange={(e) => setAttachAppId(e.target.value)}
                    >
                      <option value="">Attach application…</option>
                      {apps.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                    <Button onClick={attachApp} disabled={saving || !attachAppId}>
                      Attach
                    </Button>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
