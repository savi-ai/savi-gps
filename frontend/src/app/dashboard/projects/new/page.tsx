'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
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

export default function NewProjectPage() {
  const router = useRouter()
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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedRepoIds, setSelectedRepoIds] = useState<string[]>([])
  const [selectedApplicationId, setSelectedApplicationId] = useState('')

  const { data: repositories = [], isLoading: reposLoading } = useRepositories({
    enabled: hasCapability('intelligence'),
  })
  const { data: applications = [] } = useApplications({
    enabled: hasCapability('intelligence'),
  })

  const { data: contextPreview, isLoading: previewLoading } = useContextPreview(
    selectedRepoIds,
    selectedApplicationId || undefined,
    hasCapability('intelligence') && (selectedRepoIds.length > 0 || !!selectedApplicationId)
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

    try {
      setLoading(true)
      setError(null)
      await buildApi.createProject({
        name: formData.name.trim(),
        description: formData.description.trim() || null,
        business_value: formData.business_value.trim() || null,
        domain: formData.domain.trim() || null,
        priority: formData.priority || null,
        target_audience: formData.target_audience.trim() || null,
        default_execution_mode: formData.default_execution_mode,
        repository_ids: selectedRepoIds.length > 0 ? selectedRepoIds : undefined,
        application_id: selectedApplicationId || undefined,
      })
      router.push('/dashboard/projects')
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
          Set up a new AI-guided delivery workflow
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Project Details</CardTitle>
          <CardDescription>
            Provide context to help AI agents generate better outputs
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
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
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
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
                placeholder="e.g., Enterprise customers, End users"
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
                ].map((mode) => (
                  <label
                    key={mode.value}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors',
                      formData.default_execution_mode === mode.value
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:border-primary/50',
                      loading && 'cursor-not-allowed opacity-60'
                    )}
                  >
                    <input
                      type="radio"
                      name="execution_mode"
                      value={mode.value}
                      checked={formData.default_execution_mode === mode.value}
                      onChange={() => handleChange('default_execution_mode', mode.value)}
                      disabled={loading}
                      className="mt-0.5 accent-primary"
                    />
                    <div>
                      <p className="text-sm font-semibold">{mode.title}</p>
                      <p className="text-xs text-muted-foreground">{mode.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {hasCapability('intelligence') && (
              <div className="space-y-2">
                <Label htmlFor="application">Link application (optional)</Label>
                <p className="text-xs text-muted-foreground">
                  Select an application to link all of its repositories as agent context.
                </p>
                <select
                  id="application"
                  value={selectedApplicationId}
                  onChange={(e) => setSelectedApplicationId(e.target.value)}
                  disabled={loading}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                >
                  <option value="">None</option>
                  {applications.map((app) => (
                    <option key={app.id} value={app.id}>
                      {app.name} ({app.repository_count} repos)
                    </option>
                  ))}
                </select>
              </div>
            )}

            {hasCapability('intelligence') && (
              <div className="space-y-2">
                <Label>Link repositories (optional)</Label>
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

            {(selectedRepoIds.length > 0 || selectedApplicationId) && (
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
