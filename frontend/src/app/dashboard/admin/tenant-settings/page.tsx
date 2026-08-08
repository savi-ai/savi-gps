'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth, TenantCapabilities } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { BookOpen, GitBranch, Layers, Loader2, Save } from 'lucide-react'

type Preset = 'wiki_only' | 'modernization' | 'full'

const PRESETS: {
  id: Preset
  title: string
  description: string
  caps: TenantCapabilities & { fleet?: boolean }
  icon: React.ComponentType<{ className?: string }>
}[] = [
  {
    id: 'wiki_only',
    title: 'Wiki only',
    description: 'Intelligence only — repositories, wiki, chat, search.',
    caps: { build: false, intelligence: true, fleet: false, modernize: false, portfolio: true },
    icon: BookOpen,
  },
  {
    id: 'modernization',
    title: 'Legacy modernization',
    description: 'Intelligence + Build — understand legacy code, then modernize with agents.',
    caps: { build: true, intelligence: true, fleet: false, modernize: true, portfolio: true },
    icon: GitBranch,
  },
  {
    id: 'full',
    title: 'Full platform',
    description: 'Build + Intelligence + Fleet (when fleet is enabled server-side).',
    caps: { build: true, intelligence: true, fleet: true, modernize: true, portfolio: true },
    icon: Layers,
  },
]

export default function TenantSettingsPage() {
  const router = useRouter()
  const { hasPermission, currentTenant, refreshTenantConfig } = useAuth()
  const [caps, setCaps] = useState<TenantCapabilities>({
    build: true,
    intelligence: false,
    fleet: false,
    modernize: false,
    portfolio: false,
  })
  const [assessmentSettings, setAssessmentSettings] = useState({
    auto_assess_on_repo_index: false,
    auto_assess_on_application_analysis: false,
  })
  const [llmSettings, setLlmSettings] = useState({
    code_generation_provider: '' as string,
    wiki_generation_mode: '' as string,
    wiki_generation_provider: '' as string,
    llm_provider: '' as string,
    llm_model: '' as string,
    wiki_github_export_enabled: false,
    wiki_github_export_path: 'docs/savi-wiki',
  })
  const [specLayerSettings, setSpecLayerSettings] = useState({
    enabled: false,
    specs_folder: '.github',
    coding_agent: 'github_copilot',
  })
  const [llmStatus, setLlmStatus] = useState<{
    wiki_generation_mode_default?: string
    llm_provider_default?: string
    code_generation_default?: string
    bedrock_model_id?: string
    bedrock_region?: string
    credentials?: Record<string, boolean>
  } | null>(null)
  const [onboardingPath, setOnboardingPath] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!hasPermission('can_manage_tenant_config')) {
      router.push('/dashboard')
      return
    }
    loadConfig()
  }, [hasPermission, router])

  const loadConfig = async () => {
    try {
      setLoading(true)
      const res = await apiClient.get('/api/v1/tenant-config/me')
      setCaps({
        build: true,
        intelligence: false,
        fleet: false,
        modernize: false,
        portfolio: false,
        ...res.data.capabilities,
      })
      setAssessmentSettings({
        auto_assess_on_repo_index: false,
        auto_assess_on_application_analysis: false,
        ...res.data.assessment_settings,
      })
      setLlmSettings({
        code_generation_provider: res.data.llm_settings?.code_generation_provider || '',
        wiki_generation_mode: res.data.llm_settings?.wiki_generation_mode || '',
        wiki_generation_provider: res.data.llm_settings?.wiki_generation_provider || '',
        llm_provider: res.data.llm_settings?.llm_provider || '',
        llm_model: res.data.llm_settings?.llm_model || '',
        wiki_github_export_enabled: Boolean(
          res.data.llm_settings?.wiki_github_export_enabled
        ),
        wiki_github_export_path:
          res.data.llm_settings?.wiki_github_export_path || 'docs/savi-wiki',
      })
      setSpecLayerSettings({
        enabled: Boolean(res.data.spec_layer_settings?.enabled),
        specs_folder: res.data.spec_layer_settings?.specs_folder || '.github',
        coding_agent:
          res.data.spec_layer_settings?.coding_agent || 'github_copilot',
      })
      setLlmStatus(res.data.llm_status || null)
      setOnboardingPath(res.data.onboarding_path)
    } catch {
      setError('Failed to load tenant configuration')
    } finally {
      setLoading(false)
    }
  }

  const applyPreset = async (preset: Preset) => {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      await apiClient.post('/api/v1/tenant-config/onboarding', { path: preset })
      await refreshTenantConfig()
      await loadConfig()
      setMessage(`Applied "${PRESETS.find((p) => p.id === preset)?.title}" preset. Refresh the page if navigation does not update.`)
    } catch (err: unknown) {
      setError(extractError(err))
    } finally {
      setSaving(false)
    }
  }

  const saveAssessmentSettings = async () => {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      await apiClient.patch('/api/v1/tenant-config/assessment-settings', assessmentSettings)
      setMessage('Assessment settings saved.')
    } catch (err: unknown) {
      setError(extractError(err))
    } finally {
      setSaving(false)
    }
  }

  const saveLlmSettings = async () => {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      await apiClient.patch('/api/v1/tenant-config/llm-settings', {
        code_generation_provider: llmSettings.code_generation_provider || null,
        wiki_generation_mode: llmSettings.wiki_generation_mode || null,
        wiki_generation_provider: llmSettings.wiki_generation_provider || null,
        llm_provider: llmSettings.llm_provider || null,
        llm_model: llmSettings.llm_model || null,
        wiki_github_export_enabled: llmSettings.wiki_github_export_enabled,
      })
      await loadConfig()
      setMessage('LLM settings saved (API keys stay in server .env).')
    } catch (err: unknown) {
      setError(extractError(err))
    } finally {
      setSaving(false)
    }
  }

  const wikiCopilotNeedsCli =
    llmSettings.wiki_generation_provider === 'github_copilot' &&
    llmSettings.wiki_generation_mode === 'api'

  const saveSpecLayerSettings = async () => {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      await apiClient.patch('/api/v1/tenant-config/spec-layer-settings', {
        enabled: specLayerSettings.enabled,
        specs_folder: specLayerSettings.specs_folder.trim() || '.github',
        coding_agent: specLayerSettings.coding_agent,
      })
      await refreshTenantConfig()
      await loadConfig()
      setMessage(
        'Specs & Drift settings saved. Re-index repositories to refresh discovered specs.'
      )
    } catch (err: unknown) {
      setError(extractError(err))
    } finally {
      setSaving(false)
    }
  }

  const onCodingAgentChange = (agent: string) => {
    const suggested: Record<string, string> = {
      kiro: '.kiro',
      github_copilot: '.github',
      cursor: '.cursor',
      claude_code: '.claude',
    }
    setSpecLayerSettings((s) => ({
      ...s,
      coding_agent: agent,
      // Only auto-fill folder when it still matches a known default
      specs_folder:
        Object.values(suggested).includes(s.specs_folder) || !s.specs_folder
          ? suggested[agent] || s.specs_folder
          : s.specs_folder,
    }))
  }

  const saveCustom = async () => {
    setSaving(true)
    setError(null)
    setMessage(null)
    try {
      await apiClient.patch('/api/v1/tenant-config/capabilities', caps)
      await refreshTenantConfig()
      setMessage('Capabilities saved.')
    } catch (err: unknown) {
      setError(extractError(err))
    } finally {
      setSaving(false)
    }
  }

  if (!hasPermission('can_manage_tenant_config')) return null

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Tenant settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Configure platform capabilities for{' '}
          <span className="font-medium text-foreground">{currentTenant?.name || 'this tenant'}</span>.
          Changes apply to all users in the tenant.
        </p>
      </div>

      {onboardingPath && (
        <p className="text-sm text-muted-foreground">
          Current preset: <Badge variant="secondary">{onboardingPath.replace('_', ' ')}</Badge>
        </p>
      )}

      {message && (
        <p className="rounded-md border border-success/30 bg-success/5 px-3 py-2 text-sm text-success">
          {message}
        </p>
      )}
      {error && (
        <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Platform presets</CardTitle>
          <CardDescription>
            To use <strong>both Intelligence and legacy modernization</strong>, choose{' '}
            <strong>Legacy modernization</strong> or <strong>Full platform</strong>.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {PRESETS.map((preset) => {
            const Icon = preset.icon
            const active = onboardingPath === preset.id
            return (
              <div
                key={preset.id}
                className={cn(
                  'flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between',
                  active && 'border-primary bg-primary/5'
                )}
              >
                <div className="flex gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                    <Icon className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <p className="font-medium">{preset.title}</p>
                    <p className="text-sm text-muted-foreground">{preset.description}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {preset.caps.intelligence && <Badge variant="outline">Intelligence</Badge>}
                      {preset.caps.build && <Badge variant="outline">Build</Badge>}
                      {preset.caps.modernize && <Badge variant="outline">Modernize</Badge>}
                      {preset.caps.portfolio && <Badge variant="outline">Portfolio</Badge>}
                      {preset.caps.fleet && <Badge variant="outline">Fleet</Badge>}
                    </div>
                  </div>
                </div>
                <Button
                  variant={active ? 'secondary' : 'default'}
                  size="sm"
                  disabled={saving || loading}
                  onClick={() => applyPreset(preset.id)}
                >
                  {active ? 'Active' : 'Apply'}
                </Button>
              </div>
            )
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Code generation</CardTitle>
          <CardDescription>
            Build Developer/Testing agents and Savi Teammate when no active coding-agent seat.
            Per-Savi seats still override this when status is active.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">Provider</label>
            <select
              className="h-9 w-full rounded-md border bg-background px-3 text-sm"
              value={llmSettings.code_generation_provider}
              onChange={(e) =>
                setLlmSettings((s) => ({ ...s, code_generation_provider: e.target.value }))
              }
              disabled={loading}
            >
              <option value="">
                Inherit server ({llmStatus?.code_generation_default || 'heuristic'})
              </option>
              <option value="claude">Claude Code (claude CLI)</option>
              <option value="github_copilot">GitHub Copilot (copilot CLI)</option>
            </select>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <Badge
              variant={llmStatus?.credentials?.claude_cli_on_path ? 'secondary' : 'outline'}
            >
              claude CLI {llmStatus?.credentials?.claude_cli_on_path ? 'on PATH' : 'missing'}
            </Badge>
            <Badge
              variant={llmStatus?.credentials?.copilot_cli_on_path ? 'secondary' : 'outline'}
            >
              copilot CLI {llmStatus?.credentials?.copilot_cli_on_path ? 'on PATH' : 'missing'}
            </Badge>
            <Badge
              variant={llmStatus?.credentials?.copilot_github_token ? 'secondary' : 'outline'}
            >
              Copilot/GitHub token{' '}
              {llmStatus?.credentials?.copilot_github_token ? 'set' : 'unset'}
            </Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Wiki generation</CardTitle>
          <CardDescription>
            How repository wikis are produced. GitHub Copilot uses the CLI path only
            (wiki_agent.sh with AGENT_CLI=copilot). Secrets stay in the server environment.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Generation mode</label>
              <select
                className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={llmSettings.wiki_generation_mode}
                onChange={(e) =>
                  setLlmSettings((s) => {
                    const mode = e.target.value
                    const next = { ...s, wiki_generation_mode: mode }
                    if (mode === 'api' && s.wiki_generation_provider === 'github_copilot') {
                      next.wiki_generation_provider = 'claude'
                    }
                    return next
                  })
                }
                disabled={loading}
              >
                <option value="">
                  Inherit server ({llmStatus?.wiki_generation_mode_default || 'auto'})
                </option>
                <option value="auto">Auto (CLI then API)</option>
                <option value="api">API only</option>
                <option value="cli">CLI only (wiki_agent.sh)</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Provider</label>
              <select
                className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={llmSettings.wiki_generation_provider}
                onChange={(e) =>
                  setLlmSettings((s) => ({
                    ...s,
                    wiki_generation_provider: e.target.value,
                    ...(e.target.value === 'github_copilot' && s.wiki_generation_mode === 'api'
                      ? { wiki_generation_mode: 'cli' }
                      : {}),
                  }))
                }
                disabled={loading}
              >
                <option value="">
                  Inherit server ({llmStatus?.llm_provider_default || 'claude'})
                </option>
                <option value="claude">Anthropic Claude</option>
                <option value="github_copilot">GitHub Copilot (CLI)</option>
                <option value="openai">OpenAI</option>
                <option value="bedrock">AWS Bedrock</option>
                <option value="ollama">Ollama (local)</option>
              </select>
            </div>
          </div>
          {wikiCopilotNeedsCli && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              Copilot wiki generation requires CLI (or auto). Switch mode away from API before
              saving.
            </p>
          )}
          {llmSettings.wiki_generation_provider === 'github_copilot' && (
            <p className="text-xs text-muted-foreground">
              Copilot wiki uses the CLI only — authenticate the copilot CLI on the server; no
              Anthropic key required for this path.
            </p>
          )}
          <label className="flex cursor-pointer items-start gap-3 rounded-md border p-3">
            <input
              type="checkbox"
              className="mt-1"
              checked={llmSettings.wiki_github_export_enabled}
              onChange={(e) =>
                setLlmSettings((s) => ({
                  ...s,
                  wiki_github_export_enabled: e.target.checked,
                }))
              }
              disabled={loading}
            />
            <span>
              <span className="block text-sm font-medium">Push wiki to GitHub as a PR</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                After wiki generation, open a PR under{' '}
                <code className="text-xs">{llmSettings.wiki_github_export_path}/</code>.
                Merging that PR does not re-run wiki analysis (wiki-folder-only changes are
                always skipped). Requires the repo&apos;s linked GitHub credential with
                contents + pull-request write access.
              </span>
            </span>
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Other LLM calls</CardTitle>
          <CardDescription>
            Wiki chat/search, Idea / Feature / Architecture agents, and other API LLM clients.
            Secrets (Anthropic, OpenAI, AWS) stay in the server environment — never stored in the
            database.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">LLM provider</label>
              <select
                className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={llmSettings.llm_provider}
                onChange={(e) => setLlmSettings((s) => ({ ...s, llm_provider: e.target.value }))}
                disabled={loading}
              >
                <option value="">
                  Inherit server ({llmStatus?.llm_provider_default || 'claude'})
                </option>
                <option value="claude">Anthropic Claude</option>
                <option value="openai">OpenAI</option>
                <option value="bedrock">AWS Bedrock</option>
                <option value="ollama">Ollama (local)</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">
                Model ID (required for Bedrock; optional override otherwise)
              </label>
              <input
                className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                placeholder={
                  llmStatus?.bedrock_model_id ||
                  'e.g. us.anthropic.claude-sonnet-4-5 or anthropic.claude-…'
                }
                value={llmSettings.llm_model}
                onChange={(e) => setLlmSettings((s) => ({ ...s, llm_model: e.target.value }))}
                disabled={loading}
              />
            </div>
          </div>
          {llmStatus && (
            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
              <Badge variant="outline">Region {llmStatus.bedrock_region || '—'}</Badge>
              <Badge variant={llmStatus.credentials?.anthropic ? 'secondary' : 'outline'}>
                Anthropic {llmStatus.credentials?.anthropic ? 'configured' : 'missing'}
              </Badge>
              <Badge variant={llmStatus.credentials?.openai ? 'secondary' : 'outline'}>
                OpenAI {llmStatus.credentials?.openai ? 'configured' : 'missing'}
              </Badge>
              <Badge
                variant={llmStatus.credentials?.bedrock_model_configured ? 'secondary' : 'outline'}
              >
                Bedrock model{' '}
                {llmStatus.credentials?.bedrock_model_configured ? 'set' : 'unset'}
              </Badge>
            </div>
          )}
          <Button
            onClick={saveLlmSettings}
            disabled={saving || loading || wikiCopilotNeedsCli}
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save LLM settings
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Specs &amp; Drift</CardTitle>
          <CardDescription>
            Discover coding-agent specs during repository indexing and surface them on Specs
            &amp; Drift. Off by default — enable and choose the folder your team uses.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="flex cursor-pointer items-start gap-3 rounded-md border p-3">
            <input
              type="checkbox"
              className="mt-1"
              checked={specLayerSettings.enabled}
              onChange={(e) =>
                setSpecLayerSettings((s) => ({ ...s, enabled: e.target.checked }))
              }
              disabled={loading}
            />
            <span>
              <span className="block text-sm font-medium">Enable specs scanning</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                When on, each index pass scans the folder below for markdown / YAML specs.
                When off, Specs &amp; Drift stays empty after the next re-index.
              </span>
            </span>
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Coding agent</label>
              <select
                className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={specLayerSettings.coding_agent}
                onChange={(e) => onCodingAgentChange(e.target.value)}
                disabled={loading || !specLayerSettings.enabled}
              >
                <option value="github_copilot">GitHub Copilot</option>
                <option value="kiro">Kiro</option>
                <option value="cursor">Cursor</option>
                <option value="claude_code">Claude Code</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">
                Specs folder (repo-relative)
              </label>
              <input
                className="h-9 w-full rounded-md border bg-background px-3 text-sm font-mono"
                placeholder=".github"
                value={specLayerSettings.specs_folder}
                onChange={(e) =>
                  setSpecLayerSettings((s) => ({ ...s, specs_folder: e.target.value }))
                }
                disabled={loading || !specLayerSettings.enabled}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Default <code className="text-xs">.github</code>. Changing the coding agent
                suggests a matching folder (e.g. Kiro → <code className="text-xs">.kiro</code>).
              </p>
            </div>
          </div>
          <Button
            onClick={saveSpecLayerSettings}
            disabled={saving || loading}
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save Specs &amp; Drift settings
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Assessment triggers</CardTitle>
          <CardDescription>
            By default, modernization assessment is <strong>manual</strong> (Run assessment).
            Optionally auto-run after analysis completes.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {(
            [
              [
                'auto_assess_on_repo_index',
                'Auto-assess after repo analysis',
                'When a repository index finishes, run readiness for that repo.',
              ],
              [
                'auto_assess_on_application_analysis',
                'Auto-assess after application analysis',
                'When an application service map is freshly computed, assess all member repos.',
              ],
            ] as const
          ).map(([key, label, desc]) => (
            <label
              key={key}
              className="flex cursor-pointer items-start gap-3 rounded-md border p-3 hover:bg-muted/50"
            >
              <input
                type="checkbox"
                className="mt-1 h-4 w-4"
                checked={assessmentSettings[key]}
                onChange={(e) =>
                  setAssessmentSettings((s) => ({ ...s, [key]: e.target.checked }))
                }
                disabled={loading}
              />
              <div>
                <p className="font-medium">{label}</p>
                <p className="text-sm text-muted-foreground">{desc}</p>
              </div>
            </label>
          ))}
          <Button onClick={saveAssessmentSettings} disabled={saving || loading}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save assessment settings
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Custom capabilities</CardTitle>
          <CardDescription>Fine-tune modules independently (admin only).</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {(
            [
              ['build', 'Build', 'Idea → features → stories → architecture → code → tests'],
              ['intelligence', 'Intelligence', 'Repositories, wiki, chat, search, specs'],
              ['modernize', 'Modernize', 'Assessments, plans, playbooks — legacy modernization'],
              ['portfolio', 'Portfolio', 'CTO/CIO health, risk, cost, and trends (read-only)'],
              ['fleet', 'Fleet', 'Fleet remediation and approval queue (Phase 5)'],
            ] as const
          ).map(([key, label, desc]) => (
            <label
              key={key}
              className="flex cursor-pointer items-start gap-3 rounded-md border p-3 hover:bg-muted/50"
            >
              <input
                type="checkbox"
                className="mt-1 h-4 w-4"
                checked={caps[key]}
                onChange={(e) => setCaps((c) => ({ ...c, [key]: e.target.checked }))}
                disabled={loading}
              />
              <div>
                <p className="font-medium">{label}</p>
                <p className="text-sm text-muted-foreground">{desc}</p>
              </div>
            </label>
          ))}
          <Button onClick={saveCustom} disabled={saving || loading}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save custom capabilities
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

function extractError(err: unknown): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
    if (detail) return detail
  }
  return 'Request failed'
}
