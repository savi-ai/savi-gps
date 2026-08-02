'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { buildApi } from '@/lib/api/build'
import { useRepositories, useApplications } from '@/hooks/queries/useIntelligence'
import { useContextPreview } from '@/hooks/queries/useProjects'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { Plus, Loader2 } from 'lucide-react'
import { ProjectContextPreview } from '@/components/build/ProjectContextPreview'

type ProjectMode = 'greenfield' | 'enhance' | 'extend'

const MODE_OPTIONS: {
  value: ProjectMode
  title: string
  description: string
}[] = [
  {
    value: 'greenfield',
    title: 'From scratch',
    description:
      'Creates a new Application for you (origin: generated). No existing repos required — agents build it.',
  },
  {
    value: 'enhance',
    title: 'Enhance existing Application',
    description:
      'Pick an Application you already have. Agents use its current repos as context.',
  },
  {
    value: 'extend',
    title: 'Extend existing Application',
    description:
      'Pick an Application and optionally add more repos (or later create new ones under it).',
  },
]

export default function NewProjectPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { hasPermission, hasCapability } = useAuth()
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    business_value: '',
    domain: '',
    priority: 'medium',
    target_audience: '',
    default_execution_mode: 'copilot' as 'autopilot' | 'copilot',
  })
  const [mode, setMode] = useState<ProjectMode>('greenfield')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedRepoIds, setSelectedRepoIds] = useState<string[]>([])
  const [selectedApplicationId, setSelectedApplicationId] = useState('')

  useEffect(() => {
    const appId = searchParams.get('application_id') || ''
    const modeParam = searchParams.get('mode') as ProjectMode | null
    if (appId) {
      setSelectedApplicationId(appId)
      setMode(modeParam && ['enhance', 'extend', 'greenfield'].includes(modeParam) ? modeParam : 'enhance')
    } else if (modeParam && ['enhance', 'extend', 'greenfield'].includes(modeParam)) {
      setMode(modeParam)
    }
  }, [searchParams])

  const { data: repositories = [], isLoading: reposLoading } = useRepositories({
    enabled: hasCapability('intelligence'),
  })
  const { data: applications = [] } = useApplications({
    enabled: hasCapability('intelligence'),
  })

  const needsApp = mode === 'enhance' || mode === 'extend'
  const { data: contextPreview, isLoading: previewLoading } = useContextPreview(
    selectedRepoIds,
    needsApp ? selectedApplicationId || undefined : undefined,
    hasCapability('intelligence') && (selectedRepoIds.length > 0 || (needsApp && !!selectedApplicationId))
  )

  const toggleRepo = (repoId: string) => {
    setSelectedRepoIds((prev) =>
      prev.includes(repoId) ? prev.filter((id) => id !== repoId) : [...prev, repoId]
    )
  }

  if (!hasPermission('can_create_project')) {
    router.push('/dashboard/projects')
    return null
  }

  const handleChange = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
    setError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!formData.name.trim()) {
      setError('Project name is required')
      return
    }
    if (formData.name.trim().length < 3) {
      setError('Project name must be at least 3 characters')
      return
    }
    if (needsApp && !selectedApplicationId) {
      setError('Select a target Application for enhance / extend')
      return
    }

    try {
      setLoading(true)
      setError(null)
      const created = await buildApi.createProject({
        name: formData.name.trim(),
        description: formData.description.trim() || null,
        business_value: formData.business_value.trim() || null,
        domain: formData.domain.trim() || null,
        priority: formData.priority || null,
        target_audience: formData.target_audience.trim() || null,
        default_execution_mode: formData.default_execution_mode,
        mode,
        repository_ids: selectedRepoIds.length > 0 ? selectedRepoIds : undefined,
        application_id: needsApp ? selectedApplicationId : undefined,
        target_application_id: needsApp ? selectedApplicationId : undefined,
      })
      const appId =
        created?.target_application_id ||
        created?.source_application_id ||
        selectedApplicationId
      if (appId) {
        router.push(`/dashboard/intelligence/applications/${appId}`)
      } else {
        router.push('/dashboard/projects')
      }
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || (err instanceof Error ? err.message : 'Failed to create project'))
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Create New Project</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Delivery workstream that creates or targets an Application
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Project Details</CardTitle>
          <CardDescription>
            Choose how this project relates to estate Applications, then provide context for agents
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-3">
              <Label>How does this project relate to an Application?</Label>
              <p className="text-xs text-muted-foreground">
                Every project targets an Application. &quot;From scratch&quot; creates one;
                the other modes use an Application you already have.
              </p>
              <div className="grid gap-3">
                {MODE_OPTIONS.map((opt) => (
                  <label
                    key={opt.value}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors',
                      mode === opt.value
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-primary/50',
                      loading && 'cursor-not-allowed opacity-60'
                    )}
                  >
                    <input
                      type="radio"
                      name="project_mode"
                      value={opt.value}
                      checked={mode === opt.value}
                      onChange={() => {
                        setMode(opt.value)
                        if (opt.value === 'greenfield') {
                          setSelectedApplicationId('')
                        }
                        setError(null)
                      }}
                      disabled={loading}
                      className="mt-0.5 accent-primary"
                    />
                    <div>
                      <p className="text-sm font-semibold">{opt.title}</p>
                      <p className="text-xs text-muted-foreground">{opt.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="project-name">
                Project Name <span className="text-destructive">*</span>
              </Label>
              <Input
                id="project-name"
                value={formData.name}
                onChange={(e) => handleChange('name', e.target.value)}
                placeholder="e.g., Customer Portal, Inventory System"
                disabled={loading}
                autoFocus
                maxLength={100}
              />
              {mode === 'greenfield' && (
                <p className="text-xs text-muted-foreground">
                  Saving will create a new Application named after this project (you can rename it later).
                  That is not &quot;no linkage&quot; — the project always targets that Application.
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="project-description">Description</Label>
              <Textarea
                id="project-description"
                value={formData.description}
                onChange={(e) => handleChange('description', e.target.value)}
                placeholder="What does this project aim to achieve?"
                disabled={loading}
                rows={3}
                maxLength={500}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="business-value">Business Value</Label>
              <Textarea
                id="business-value"
                value={formData.business_value}
                onChange={(e) => handleChange('business_value', e.target.value)}
                placeholder="Expected business outcomes and benefits"
                disabled={loading}
                rows={2}
                maxLength={500}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="domain">Domain</Label>
                <Input
                  id="domain"
                  value={formData.domain}
                  onChange={(e) => handleChange('domain', e.target.value)}
                  placeholder="e.g., E-commerce, Healthcare"
                  disabled={loading}
                  maxLength={50}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="priority">Priority</Label>
                <select
                  id="priority"
                  value={formData.priority}
                  onChange={(e) => handleChange('priority', e.target.value)}
                  disabled={loading}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="target-audience">Target Audience</Label>
              <Input
                id="target-audience"
                value={formData.target_audience}
                onChange={(e) => handleChange('target_audience', e.target.value)}
                placeholder="Who will use this?"
                disabled={loading}
                maxLength={100}
              />
            </div>

            <div className="space-y-3">
              <Label>Default Execution Mode</Label>
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  {
                    value: 'copilot' as const,
                    title: 'Copilot',
                    description: 'Human-in-the-loop stage-by-stage review',
                  },
                  {
                    value: 'autopilot' as const,
                    title: 'Autopilot',
                    description: 'Fully automated end-to-end delivery',
                  },
                ].map((execMode) => (
                  <label
                    key={execMode.value}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors',
                      formData.default_execution_mode === execMode.value
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-primary/50',
                      loading && 'cursor-not-allowed opacity-60'
                    )}
                  >
                    <input
                      type="radio"
                      name="execution_mode"
                      value={execMode.value}
                      checked={formData.default_execution_mode === execMode.value}
                      onChange={() => handleChange('default_execution_mode', execMode.value)}
                      disabled={loading}
                      className="mt-0.5 accent-primary"
                    />
                    <div>
                      <p className="text-sm font-semibold">{execMode.title}</p>
                      <p className="text-xs text-muted-foreground">{execMode.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {hasCapability('intelligence') && needsApp && (
              <div className="space-y-2">
                <Label htmlFor="application">
                  Target application <span className="text-destructive">*</span>
                </Label>
                <p className="text-xs text-muted-foreground">
                  Member repositories are linked as agent context.
                </p>
                <select
                  id="application"
                  value={selectedApplicationId}
                  onChange={(e) => setSelectedApplicationId(e.target.value)}
                  disabled={loading}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                >
                  <option value="">Select application…</option>
                  {applications.map((app) => (
                    <option key={app.id} value={app.id}>
                      {app.name} ({app.repository_count} repos)
                      {app.origin ? ` · ${app.origin}` : ''}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {hasCapability('intelligence') && mode !== 'greenfield' && (
              <div className="space-y-2">
                <Label>Additional repositories (optional)</Label>
                <p className="text-xs text-muted-foreground">
                  Agents will use wiki and code context from linked repos.
                </p>
                {reposLoading ? (
                  <p className="text-sm text-muted-foreground">Loading repositories…</p>
                ) : repositories.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No indexed repositories available.</p>
                ) : (
                  <div className="max-h-48 space-y-2 overflow-y-auto rounded-md border p-3">
                    {repositories.map((repo) => (
                      <label
                        key={repo.id}
                        className="flex cursor-pointer items-start gap-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          checked={selectedRepoIds.includes(repo.id)}
                          onChange={() => toggleRepo(repo.id)}
                          disabled={loading || repo.status !== 'ready'}
                          className="mt-1"
                        />
                        <span className="flex-1">
                          <span className="font-medium">{repo.github_full_name || repo.name}</span>
                          <Badge variant="outline" className="ml-2 capitalize text-xs">
                            {repo.status}
                          </Badge>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}

            {(selectedRepoIds.length > 0 || (needsApp && selectedApplicationId)) && (
              <ProjectContextPreview preview={contextPreview ?? null} loading={previewLoading} />
            )}

            {error && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => router.push('/dashboard/projects')}
                disabled={loading}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={loading || !formData.name.trim()}>
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  <>
                    <Plus className="h-4 w-4" />
                    Create Project
                  </>
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
