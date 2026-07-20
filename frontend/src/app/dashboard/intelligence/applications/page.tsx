'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { LayoutGrid, Plus, GitBranch, ArrowRight } from 'lucide-react'

interface ApplicationSummary {
  id: string
  name: string
  description?: string | null
  domain?: string | null
  repository_count: number
  repositories_ready: number
}

export default function ApplicationsPage() {
  const router = useRouter()
  const { hasCapability, hasPermission } = useAuth()
  const [applications, setApplications] = useState<ApplicationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await apiClient.get('/api/v1/intelligence/applications')
      setApplications(res.data?.applications || [])
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to load applications')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    load()
  }, [hasCapability, router, load])

  if (!hasPermission('can_use_intelligence')) return null

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <LayoutGrid className="h-6 w-6 pillar-text-intelligence" />
            <h1 className="text-2xl font-bold tracking-tight">Applications</h1>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Group repositories into real-world products — a backend, frontend, and shared libs
            that ship together as one application in your estate.
          </p>
        </div>
        <Button onClick={() => router.push('/dashboard/intelligence/applications/new')}>
          <Plus className="h-4 w-4" />
          New application
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-36 w-full" />
          ))}
        </div>
      ) : applications.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <LayoutGrid className="mx-auto mb-3 h-10 w-10 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No applications yet. Create one to group related repositories.
            </p>
            <Button className="mt-4" size="sm" asChild>
              <Link href="/dashboard/intelligence/applications/new">Create application</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {applications.map((app) => (
            <Card key={app.id} className="shadow-sm transition-shadow hover:shadow-md">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{app.name}</CardTitle>
                {app.domain && (
                  <CardDescription className="capitalize">{app.domain}</CardDescription>
                )}
              </CardHeader>
              <CardContent className="space-y-3">
                {app.description && (
                  <p className="line-clamp-2 text-sm text-muted-foreground">{app.description}</p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">
                    <GitBranch className="mr-1 h-3 w-3" />
                    {app.repository_count} repo{app.repository_count !== 1 ? 's' : ''}
                  </Badge>
                  {app.repository_count > 0 && (
                    <Badge variant="outline">
                      {app.repositories_ready}/{app.repository_count} indexed
                    </Badge>
                  )}
                </div>
                <Button variant="ghost" size="sm" className="h-auto p-0" asChild>
                  <Link href={`/dashboard/intelligence/applications/${app.id}`}>
                    View details
                    <ArrowRight className="ml-1 h-3.5 w-3.5" />
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
