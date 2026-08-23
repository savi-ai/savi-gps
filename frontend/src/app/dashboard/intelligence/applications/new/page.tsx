'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ArrowLeft } from 'lucide-react'
import ApplicationRepoAttachPanel, {
  attachRepositoriesToApplication,
  emptyRepoRow,
  type RepoAttachPayload,
  type RepoOption,
} from '@/components/intelligence/ApplicationRepoAttachPanel'

export default function NewApplicationPage() {
  const router = useRouter()
  const { hasCapability, hasPermission } = useAuth()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [domain, setDomain] = useState('')
  const [repositories, setRepositories] = useState<RepoOption[]>([])
  const [repoAttach, setRepoAttach] = useState<RepoAttachPayload>({
    selectedRepoIds: [],
    newRepoRows: [emptyRepoRow()],
    role: 'unknown',
    autoIndex: true,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    apiClient
      .get('/api/v1/intelligence/repos')
      .then((res) => setRepositories(res.data?.repositories || []))
      .catch(() => setRepositories([]))
  }, [hasCapability, router])

  const unassignedRepos = useMemo(
    () => repositories.filter((r) => !r.application),
    [repositories]
  )

  if (!hasPermission('can_use_intelligence')) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Name is required')
      return
    }

    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v1/intelligence/applications', {
        name: name.trim(),
        description: description.trim() || null,
        domain: domain.trim() || null,
        repository_ids:
          repoAttach.selectedRepoIds.length > 0 ? repoAttach.selectedRepoIds : undefined,
      })
      const appId = res.data.id as string

      const hasNewUrls = repoAttach.newRepoRows.some((r) => r.url.trim())
      if (hasNewUrls) {
        await attachRepositoriesToApplication(appId, {
          ...repoAttach,
          selectedRepoIds: [],
        })
      }

      router.push(`/dashboard/intelligence/applications/${appId}`)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to create application')
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Button variant="ghost" size="sm" onClick={() => router.back()}>
        <ArrowLeft className="h-4 w-4" />
        Back
      </Button>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">New application</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Define a product and attach multiple repositories now — existing or new GitHub URLs.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Application details</CardTitle>
            <CardDescription>How this product appears in Intelligence and Portfolio</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {error && (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. ITC Academy"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="domain">Domain (optional)</Label>
              <Input
                id="domain"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="e.g. Education, E-commerce"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Description (optional)</Label>
              <Input
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Short summary for executives and teams"
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Repositories</CardTitle>
            <CardDescription>
              Optional — select multiple existing repos and/or connect new GitHub URLs.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ApplicationRepoAttachPanel
              variant="embedded"
              availableRepos={unassignedRepos}
              value={repoAttach}
              onChange={setRepoAttach}
              disabled={loading}
            />
          </CardContent>
        </Card>

        <Button type="submit" disabled={loading}>
          {loading ? 'Creating…' : 'Create application'}
        </Button>
      </form>
    </div>
  )
}
