'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ArrowLeft } from 'lucide-react'

interface RepositoryOption {
  id: string
  name: string
  github_full_name?: string
  status: string
}

export default function NewApplicationPage() {
  const router = useRouter()
  const { hasCapability, hasPermission } = useAuth()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [domain, setDomain] = useState('')
  const [repositories, setRepositories] = useState<RepositoryOption[]>([])
  const [selectedRepoIds, setSelectedRepoIds] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    apiClient.get('/api/v1/intelligence/repos').then((res) => {
      setRepositories(res.data?.repositories || [])
    })
  }, [hasCapability, router])

  if (!hasPermission('can_use_intelligence')) return null

  const toggleRepo = (id: string) => {
    setSelectedRepoIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

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
        repository_ids: selectedRepoIds.length > 0 ? selectedRepoIds : undefined,
      })
      router.push(`/dashboard/intelligence/applications/${res.data.id}`)
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
          Define a product in your estate and optionally attach repositories now.
        </p>
      </div>

      <form onSubmit={handleSubmit}>
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

            {repositories.length > 0 && (
              <div className="space-y-2">
                <Label>Repositories (optional)</Label>
                <p className="text-xs text-muted-foreground">
                  Only unassigned repos can be added. Assign others from the repo detail page.
                </p>
                <ul className="max-h-48 space-y-2 overflow-y-auto rounded-md border p-3">
                  {repositories.map((repo) => (
                    <li key={repo.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={selectedRepoIds.includes(repo.id)}
                        onChange={() => toggleRepo(repo.id)}
                        className="h-4 w-4"
                      />
                      <span>{repo.github_full_name || repo.name}</span>
                      <span className="text-xs text-muted-foreground capitalize">{repo.status}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <Button type="submit" disabled={loading}>
              {loading ? 'Creating…' : 'Create application'}
            </Button>
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
