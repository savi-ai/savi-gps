'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, Loader2, Save, Unlink } from 'lucide-react'

const TYPES = ['github', 'jira', 'slack', 'confluence'] as const

interface Binding {
  id: string
  connector_type: string
  status: string
  config: Record<string, unknown>
  has_secret: boolean
}

interface CredOption {
  id: string
  github_login?: string
  label?: string
}

interface MachineUser {
  id: string
  username: string
  email: string
  is_active: boolean
}

interface ExternalIdentity {
  provider: string
  subject: string
  display_name?: string
  linked_at?: string | null
}

interface CodingAgentSeat {
  id: string
  agent_type: string
  status: string
  external_seat_ref?: string | null
  execution_mode: string
  has_secret: boolean
}

interface SaviInstance {
  id: string
  name: string
  status: string
  machine_user?: MachineUser | null
  external_identity?: ExternalIdentity | null
  coding_agent_seat?: CodingAgentSeat | null
}

function errDetail(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    return (
      (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
      fallback
    )
  }
  return fallback
}

export default function TeamSaviConnectorsPage() {
  const params = useParams()
  const teamId = String(params.teamId || '')
  const router = useRouter()
  const { hasPermission, hasRole } = useAuth()

  const [teamName, setTeamName] = useState('')
  const [savi, setSavi] = useState<SaviInstance | null>(null)
  const [bindings, setBindings] = useState<Binding[]>([])
  const [creds, setCreds] = useState<CredOption[]>([])
  const [apps, setApps] = useState<Array<{ id: string; name: string }>>([])
  const [providers, setProviders] = useState<string[]>([
    'entra',
    'okta',
    'google',
    'github',
    'custom',
  ])
  const [agentTypes, setAgentTypes] = useState<string[]>([
    'github_copilot',
    'cursor',
    'kiro',
    'claude_code',
    'custom',
  ])
  const [executionModes, setExecutionModes] = useState<string[]>([
    'cli',
    'claude_cli',
    'copilot_cli',
    'kiro_cli',
    'api',
    'remote_runner',
    'llm',
    'heuristic',
  ])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [forms, setForms] = useState<Record<string, Record<string, string>>>({})
  const [identityForm, setIdentityForm] = useState({
    provider: 'entra',
    subject: '',
    display_name: '',
  })
  const [seatForm, setSeatForm] = useState({
    agent_type: 'claude_code',
    execution_mode: 'cli',
    status: 'pending_license',
    external_seat_ref: '',
    secret: '',
  })

  const canManage =
    hasPermission('can_manage_teams') ||
    hasPermission('can_manage_tenant_config') ||
    hasRole('admin')

  const load = useCallback(async () => {
    const teamRes = await apiClient.get(`/api/v1/teams/${teamId}`)
    setTeamName(teamRes.data.name || 'Team')
    setApps(teamRes.data.applications || [])
    const active =
      (teamRes.data.savi_instances || []).find(
        (s: SaviInstance) => s.status === 'active'
      ) || (teamRes.data.savi_instances || [])[0]
    if (!active) {
      setSavi(null)
      setBindings([])
      return
    }

    const [connRes, idRes] = await Promise.all([
      apiClient.get(`/api/v1/teams/${teamId}/savi/${active.id}/connectors`),
      apiClient.get(`/api/v1/teams/${teamId}/savi/${active.id}/identity`),
    ])

    const list: Binding[] = connRes.data.connectors || []
    setBindings(list)
    const nextForms: Record<string, Record<string, string>> = {}
    for (const t of TYPES) {
      const b = list.find((x) => x.connector_type === t)
      const cfg = (b?.config || {}) as Record<string, string>
      nextForms[t] = {
        status: b?.status || 'active',
        github_credential_id: cfg.github_credential_id || '',
        base_url: cfg.base_url || '',
        email: cfg.email || '',
        channel_id: cfg.channel_id || '',
        default_application_id: cfg.default_application_id || '',
        webhook_token: cfg.webhook_token || '',
        secret: '',
      }
    }
    setForms(nextForms)

    const detail = idRes.data.savi as SaviInstance
    setSavi(detail)
    const ext = idRes.data.external_identity as ExternalIdentity | null
    setIdentityForm({
      provider: ext?.provider || 'entra',
      subject: ext?.subject || '',
      display_name: ext?.display_name || '',
    })
    const seat = idRes.data.coding_agent_seat as CodingAgentSeat | null
    setSeatForm({
      agent_type: seat?.agent_type || 'claude_code',
      execution_mode: seat?.execution_mode || 'cli',
      status: seat?.status || 'pending_license',
      external_seat_ref: seat?.external_seat_ref || '',
      secret: '',
    })
    const opts = idRes.data.options || {}
    if (opts.providers?.length) setProviders(opts.providers)
    if (opts.agent_types?.length) setAgentTypes(opts.agent_types)
    if (opts.execution_modes?.length) setExecutionModes(opts.execution_modes)

    try {
      const credRes = await apiClient.get('/api/v1/intelligence/github/credentials')
      setCreds(
        (credRes.data.credentials || credRes.data || []).map(
          (c: { id: string; github_login?: string; label?: string }) => ({
            id: c.id,
            github_login: c.github_login,
            label: c.label,
          })
        )
      )
    } catch {
      setCreds([])
    }
  }, [teamId])

  useEffect(() => {
    if (!canManage) {
      router.push('/dashboard')
      return
    }
    ;(async () => {
      try {
        setLoading(true)
        await load()
      } catch {
        setError('Failed to load Savi setup')
      } finally {
        setLoading(false)
      }
    })()
  }, [canManage, router, load])

  const save = async (ctype: string) => {
    if (!savi) return
    setSaving(ctype)
    setError(null)
    const f = forms[ctype] || {}
    const config: Record<string, string> = {}
    if (ctype === 'github' && f.github_credential_id) {
      config.github_credential_id = f.github_credential_id
    }
    if (ctype === 'jira' || ctype === 'confluence') {
      if (f.base_url) config.base_url = f.base_url
      if (f.email) config.email = f.email
    }
    if (ctype === 'slack' && f.channel_id) config.channel_id = f.channel_id
    if ((ctype === 'jira' || ctype === 'slack') && f.default_application_id) {
      config.default_application_id = f.default_application_id
    }
    if (f.webhook_token) config.webhook_token = f.webhook_token

    try {
      await apiClient.put(
        `/api/v1/teams/${teamId}/savi/${savi.id}/connectors/${ctype}`,
        {
          connector_type: ctype,
          status: f.status || 'active',
          config,
          secret: f.secret || undefined,
        }
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, `Failed to save ${ctype}`))
    } finally {
      setSaving(null)
    }
  }

  const saveIdentity = async () => {
    if (!savi) return
    setSaving('identity')
    setError(null)
    try {
      await apiClient.put(
        `/api/v1/teams/${teamId}/savi/${savi.id}/identity/external`,
        {
          provider: identityForm.provider,
          subject: identityForm.subject,
          display_name: identityForm.display_name || undefined,
        }
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to attach identity'))
    } finally {
      setSaving(null)
    }
  }

  const detachIdentity = async () => {
    if (!savi) return
    if (!confirm('Detach company identity from this Savi?')) return
    setSaving('identity-detach')
    setError(null)
    try {
      await apiClient.delete(
        `/api/v1/teams/${teamId}/savi/${savi.id}/identity/external`
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to detach identity'))
    } finally {
      setSaving(null)
    }
  }

  const saveSeat = async () => {
    if (!savi) return
    setSaving('seat')
    setError(null)
    try {
      await apiClient.put(`/api/v1/teams/${teamId}/savi/${savi.id}/coding-agent`, {
        agent_type: seatForm.agent_type,
        execution_mode: seatForm.execution_mode,
        status: seatForm.status,
        external_seat_ref: seatForm.external_seat_ref || undefined,
        secret: seatForm.secret || undefined,
      })
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to save coding agent seat'))
    } finally {
      setSaving(null)
    }
  }

  const disableSeat = async () => {
    if (!savi) return
    setSaving('seat-disable')
    setError(null)
    try {
      await apiClient.post(
        `/api/v1/teams/${teamId}/savi/${savi.id}/coding-agent/disable`
      )
      await load()
    } catch (err: unknown) {
      setError(errDetail(err, 'Failed to disable seat'))
    } finally {
      setSaving(null)
    }
  }

  const setField = (ctype: string, key: string, value: string) => {
    setForms((prev) => ({
      ...prev,
      [ctype]: { ...(prev[ctype] || {}), [key]: value },
    }))
  }

  if (!canManage) return null

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/dashboard/admin/teams"
          className="mb-2 inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
          Teams
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">
          {teamName ? `${teamName} · Savi setup` : 'Savi setup'}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Attach company identity and coding-agent seat (T7), then bind GitHub / Jira /
          Slack / Confluence (T5).
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <Skeleton className="h-40 w-full" />
      ) : !savi ? (
        <p className="text-sm text-muted-foreground">Roster a Savi first.</p>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Identity</CardTitle>
                  <Badge variant={savi.external_identity ? 'default' : 'secondary'}>
                    {savi.external_identity ? 'linked' : 'machine only'}
                  </Badge>
                </div>
                <CardDescription>
                  GPS machine user for audit; attach your company service account / SP
                  (ADR 0009).
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {savi.machine_user && (
                  <div className="rounded-md border bg-muted/40 px-3 py-2 text-xs">
                    <div className="font-medium">Machine identity</div>
                    <div className="mt-1 font-mono text-muted-foreground">
                      {savi.machine_user.email}
                    </div>
                  </div>
                )}
                <div>
                  <Label className="text-xs">Provider</Label>
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={identityForm.provider}
                    onChange={(e) =>
                      setIdentityForm((p) => ({ ...p, provider: e.target.value }))
                    }
                  >
                    {providers.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-xs">Subject (UPN / email / object id)</Label>
                  <Input
                    className="mt-1 font-mono text-xs"
                    placeholder="savi-platform@contoso.com"
                    value={identityForm.subject}
                    onChange={(e) =>
                      setIdentityForm((p) => ({ ...p, subject: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <Label className="text-xs">Display name</Label>
                  <Input
                    className="mt-1"
                    value={identityForm.display_name}
                    onChange={(e) =>
                      setIdentityForm((p) => ({ ...p, display_name: e.target.value }))
                    }
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    onClick={saveIdentity}
                    disabled={saving === 'identity' || !identityForm.subject.trim()}
                  >
                    {saving === 'identity' ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Save className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    Attach identity
                  </Button>
                  {savi.external_identity && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={detachIdentity}
                      disabled={saving === 'identity-detach'}
                    >
                      {saving === 'identity-detach' ? (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Unlink className="mr-1.5 h-3.5 w-3.5" />
                      )}
                      Detach
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Coding agent seat</CardTitle>
                  <Badge
                    variant={
                      savi.coding_agent_seat?.status === 'active' ? 'default' : 'secondary'
                    }
                  >
                    {savi.coding_agent_seat?.status || 'not bound'}
                  </Badge>
                </div>
                <CardDescription>
                  Bind the vendor seat licensed to the company identity (IT assigns the
                  seat; GPS stores the binding).
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div>
                  <Label className="text-xs">Agent type</Label>
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={seatForm.agent_type}
                    onChange={(e) =>
                      setSeatForm((p) => ({ ...p, agent_type: e.target.value }))
                    }
                  >
                    {agentTypes.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-xs">Execution mode</Label>
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={seatForm.execution_mode}
                    onChange={(e) =>
                      setSeatForm((p) => ({ ...p, execution_mode: e.target.value }))
                    }
                  >
                    {executionModes.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <Label className="text-xs">Status</Label>
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
                    value={seatForm.status}
                    onChange={(e) =>
                      setSeatForm((p) => ({ ...p, status: e.target.value }))
                    }
                  >
                    <option value="pending_license">pending_license</option>
                    <option value="active">active</option>
                    <option value="disabled">disabled</option>
                  </select>
                </div>
                <div>
                  <Label className="text-xs">Seat ref (licensed email / seat id)</Label>
                  <Input
                    className="mt-1 font-mono text-xs"
                    value={seatForm.external_seat_ref}
                    onChange={(e) =>
                      setSeatForm((p) => ({
                        ...p,
                        external_seat_ref: e.target.value,
                      }))
                    }
                  />
                </div>
                <div>
                  <Label className="text-xs">
                    Agent secret{' '}
                    {savi.coding_agent_seat?.has_secret ? '(saved)' : '(optional)'}
                  </Label>
                  <Input
                    className="mt-1"
                    type="password"
                    placeholder={
                      savi.coding_agent_seat?.has_secret ? '••••••••' : 'Paste if needed'
                    }
                    value={seatForm.secret}
                    onChange={(e) =>
                      setSeatForm((p) => ({ ...p, secret: e.target.value }))
                    }
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    onClick={saveSeat}
                    disabled={saving === 'seat'}
                  >
                    {saving === 'seat' ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Save className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    Save seat
                  </Button>
                  {savi.coding_agent_seat &&
                    savi.coding_agent_seat.status !== 'disabled' && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={disableSeat}
                        disabled={saving === 'seat-disable'}
                      >
                        {saving === 'seat-disable' ? (
                          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        ) : null}
                        Disable seat
                      </Button>
                    )}
                </div>
              </CardContent>
            </Card>
          </div>

          <div>
            <h2 className="mb-3 text-lg font-semibold tracking-tight">Connectors</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              {TYPES.map((ctype) => {
                const existing = bindings.find((b) => b.connector_type === ctype)
                const f = forms[ctype] || {}
                return (
                  <Card key={ctype}>
                    <CardHeader className="pb-2">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-base capitalize">{ctype}</CardTitle>
                        <Badge
                          variant={existing?.status === 'active' ? 'default' : 'secondary'}
                        >
                          {existing ? existing.status : 'not bound'}
                        </Badge>
                      </div>
                      <CardDescription>
                        {ctype === 'github' &&
                          'Uses Intelligence GitHub credential for PRs'}
                        {ctype === 'jira' &&
                          'Assignment webhook + comments / transitions'}
                        {ctype === 'slack' &&
                          'Status posts + @mention enqueue webhook'}
                        {ctype === 'confluence' &&
                          'Read page by URL into context pack'}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {ctype === 'github' && (
                        <div>
                          <Label className="text-xs">GitHub credential</Label>
                          <select
                            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
                            value={f.github_credential_id || ''}
                            onChange={(e) =>
                              setField(ctype, 'github_credential_id', e.target.value)
                            }
                          >
                            <option value="">Select credential…</option>
                            {creds.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.label || c.github_login || c.id}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                      {(ctype === 'jira' || ctype === 'confluence') && (
                        <>
                          <div>
                            <Label className="text-xs">Base URL</Label>
                            <Input
                              className="mt-1"
                              placeholder="https://your.atlassian.net"
                              value={f.base_url || ''}
                              onChange={(e) =>
                                setField(ctype, 'base_url', e.target.value)
                              }
                            />
                          </div>
                          <div>
                            <Label className="text-xs">Email</Label>
                            <Input
                              className="mt-1"
                              value={f.email || ''}
                              onChange={(e) => setField(ctype, 'email', e.target.value)}
                            />
                          </div>
                          <div>
                            <Label className="text-xs">
                              API token {existing?.has_secret ? '(saved)' : ''}
                            </Label>
                            <Input
                              className="mt-1"
                              type="password"
                              placeholder={
                                existing?.has_secret ? '••••••••' : 'Paste token'
                              }
                              value={f.secret || ''}
                              onChange={(e) => setField(ctype, 'secret', e.target.value)}
                            />
                          </div>
                        </>
                      )}
                      {ctype === 'slack' && (
                        <>
                          <div>
                            <Label className="text-xs">Channel ID</Label>
                            <Input
                              className="mt-1"
                              placeholder="C0123456789"
                              value={f.channel_id || ''}
                              onChange={(e) =>
                                setField(ctype, 'channel_id', e.target.value)
                              }
                            />
                          </div>
                          <div>
                            <Label className="text-xs">
                              Bot token {existing?.has_secret ? '(saved)' : ''}
                            </Label>
                            <Input
                              className="mt-1"
                              type="password"
                              placeholder={
                                existing?.has_secret ? '••••••••' : 'xoxb-…'
                              }
                              value={f.secret || ''}
                              onChange={(e) => setField(ctype, 'secret', e.target.value)}
                            />
                          </div>
                        </>
                      )}
                      {(ctype === 'jira' || ctype === 'slack') && (
                        <>
                          <div>
                            <Label className="text-xs">
                              Default application (for webhooks)
                            </Label>
                            <select
                              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
                              value={f.default_application_id || ''}
                              onChange={(e) =>
                                setField(
                                  ctype,
                                  'default_application_id',
                                  e.target.value
                                )
                              }
                            >
                              <option value="">None</option>
                              {apps.map((a) => (
                                <option key={a.id} value={a.id}>
                                  {a.name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <Label className="text-xs">Webhook token</Label>
                            <Input
                              className="mt-1 font-mono text-xs"
                              value={f.webhook_token || ''}
                              onChange={(e) =>
                                setField(ctype, 'webhook_token', e.target.value)
                              }
                              placeholder="Auto-generated on save if empty"
                            />
                            <p className="mt-1 break-all text-[11px] text-muted-foreground">
                              POST /api/v1/webhooks/savi/{savi.id}/{ctype}
                              <br />
                              Header: X-Savi-Webhook-Token
                            </p>
                          </div>
                        </>
                      )}
                      <Button
                        size="sm"
                        onClick={() => save(ctype)}
                        disabled={saving === ctype}
                      >
                        {saving === ctype ? (
                          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Save className="mr-1.5 h-3.5 w-3.5" />
                        )}
                        Save {ctype}
                      </Button>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
