'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { WikiChatPanel } from '@/components/intelligence/WikiChatPanel'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'

interface Repository {
  id: string
  name: string
  status: string
}

interface Application {
  id: string
  name: string
}

type ChatMode = 'repo' | 'application' | 'tenant'

export default function IntelligenceChatPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { hasCapability } = useAuth()
  const [repos, setRepos] = useState<Repository[]>([])
  const [applications, setApplications] = useState<Application[]>([])
  const [mode, setMode] = useState<ChatMode>(
    searchParams.get('application_id') ? 'application' : 'repo'
  )
  const [selectedRepoId, setSelectedRepoId] = useState<string>('')
  const [selectedAppId, setSelectedAppId] = useState<string>(searchParams.get('application_id') || '')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!hasCapability('intelligence')) router.push('/dashboard')
  }, [hasCapability, router])

  useEffect(() => {
    const load = async () => {
      try {
        const [reposRes, appsRes] = await Promise.all([
          apiClient.get('/api/v1/intelligence/repos'),
          apiClient.get('/api/v1/intelligence/applications'),
        ])
        const list: Repository[] = reposRes.data.repositories || []
        const apps: Application[] = appsRes.data.applications || []
        setRepos(list)
        setApplications(apps)

        const fromQuery = searchParams.get('repo_id')
        const fromApp = searchParams.get('application_id')
        const ready = list.filter((r) => r.status === 'ready')

        if (fromApp && apps.some((a) => a.id === fromApp)) {
          setMode('application')
          setSelectedAppId(fromApp)
        } else if (fromQuery && list.some((r) => r.id === fromQuery)) {
          setMode('repo')
          setSelectedRepoId(fromQuery)
        } else if (ready.length > 0) {
          setSelectedRepoId(ready[0].id)
        } else if (list.length > 0) {
          setSelectedRepoId(list[0].id)
        }

        if (!selectedAppId && apps.length > 0) {
          setSelectedAppId(apps[0].id)
        }
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [searchParams])

  const selectedRepo = repos.find((r) => r.id === selectedRepoId)
  const selectedApp = applications.find((a) => a.id === selectedAppId)

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-[400px] w-full" />
      </div>
    )
  }

  const hasTargets =
    mode === 'tenant'
      ? repos.some((r) => r.status === 'ready')
      : mode === 'repo'
        ? repos.length > 0
        : applications.length > 0

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Wiki Chat</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Chat per repository or across all repos in an application with federated retrieval.
        </p>
      </div>

      {!hasTargets ? (
        <Card>
          <CardHeader>
            <CardTitle>No scope available</CardTitle>
            <CardDescription>
              Connect repositories or create an application, then return here to chat.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">
                Scope{' '}
                <span className="font-normal text-muted-foreground">
                  (choose where chat retrieves answers from)
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
              <div className="flex flex-wrap gap-1">
                <Button
                  type="button"
                  size="sm"
                  variant={mode === 'repo' ? 'default' : 'outline'}
                  onClick={() => setMode('repo')}
                >
                  Repository
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={mode === 'application' ? 'default' : 'outline'}
                  onClick={() => setMode('application')}
                >
                  Application
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={mode === 'tenant' ? 'default' : 'outline'}
                  onClick={() => setMode('tenant')}
                >
                  All repos
                </Button>
              </div>

              {mode === 'repo' && (
                <div className="min-w-0 flex-1 sm:max-w-md">
                  <Label htmlFor="repo-select" className="mb-1 block text-xs text-muted-foreground">
                    Repository
                  </Label>
                  <select
                    id="repo-select"
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={selectedRepoId}
                    onChange={(e) => setSelectedRepoId(e.target.value)}
                  >
                    {repos.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name} {r.status !== 'ready' ? `(${r.status})` : ''}
                      </option>
                    ))}
                  </select>
                  {selectedRepo && selectedRepo.status !== 'ready' && (
                    <p className="mt-1 text-xs text-amber-600">
                      Index this repository for best results.
                    </p>
                  )}
                </div>
              )}

              {mode === 'application' && (
                <div className="min-w-0 flex-1 sm:max-w-md">
                  <Label htmlFor="app-select" className="mb-1 block text-xs text-muted-foreground">
                    Application
                  </Label>
                  <select
                    id="app-select"
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={selectedAppId}
                    onChange={(e) => setSelectedAppId(e.target.value)}
                  >
                    {applications.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {mode === 'tenant' && (
                <p className="text-sm text-muted-foreground sm:pb-2">
                  Searching across all indexed repositories in your tenant.
                </p>
              )}
            </CardContent>
          </Card>

          {mode === 'repo' && selectedRepoId && (
            <WikiChatPanel
              scope={{ type: 'repo', id: selectedRepoId, label: selectedRepo?.name }}
            />
          )}
          {mode === 'application' && selectedAppId && (
            <WikiChatPanel
              scope={{ type: 'application', id: selectedAppId, label: selectedApp?.name }}
            />
          )}
          {mode === 'tenant' && (
            <WikiChatPanel scope={{ type: 'tenant', label: 'your estate' }} />
          )}
        </div>
      )}
    </div>
  )
}
