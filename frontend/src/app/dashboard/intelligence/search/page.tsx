'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Label } from '@/components/ui/label'
import { Search, GitBranch, FileText, Code2 } from 'lucide-react'

interface SearchResult {
  repository_id: string
  repository_name: string
  type: string
  title: string
  file_path: string
  start_line?: number | null
  excerpt: string
  score: number
}

interface ApplicationOption {
  id: string
  name: string
}

type SearchScope = 'tenant' | 'repository' | 'application'

export default function IntelligenceSearchPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { hasCapability, hasPermission } = useAuth()
  const [query, setQuery] = useState(searchParams.get('q') || '')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searched, setSearched] = useState(false)
  const [applications, setApplications] = useState<ApplicationOption[]>([])

  const initialScope = searchParams.get('application_id')
    ? 'application'
    : searchParams.get('repo')
      ? 'repository'
      : 'tenant'

  const [scope, setScope] = useState<SearchScope>(initialScope as SearchScope)
  const [repoFilter, setRepoFilter] = useState(searchParams.get('repo') || '')
  const [applicationFilter, setApplicationFilter] = useState(searchParams.get('application_id') || '')

  useEffect(() => {
    apiClient
      .get('/api/v1/intelligence/applications')
      .then((res) => setApplications(res.data?.applications || []))
      .catch(() => setApplications([]))
  }, [])

  const runSearch = useCallback(
    async (q: string, searchScope: SearchScope, repositoryId?: string, applicationId?: string) => {
      if (!q.trim()) return
      try {
        setLoading(true)
        setError(null)
        setSearched(true)
        const params: Record<string, string | number> = { q: q.trim(), limit: 25 }
        if (searchScope === 'repository' && repositoryId) {
          params.repository_id = repositoryId
        } else if (searchScope === 'application' && applicationId) {
          params.application_id = applicationId
        }
        const res = await apiClient.get('/api/v1/intelligence/search', { params })
        setResults(res.data?.results || [])
      } catch (err: unknown) {
        const detail =
          err && typeof err === 'object' && 'response' in err
            ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
            : null
        setError(detail || 'Search failed')
        setResults([])
      } finally {
        setLoading(false)
      }
    },
    []
  )

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    const initial = searchParams.get('q')
    if (initial) {
      runSearch(
        initial,
        initialScope as SearchScope,
        searchParams.get('repo') || undefined,
        searchParams.get('application_id') || undefined
      )
    }
  }, [hasCapability, router, searchParams, runSearch, initialScope])

  if (!hasPermission('can_use_intelligence')) return null

  const scopeDescription =
    scope === 'application' && applicationFilter
      ? applications.find((a) => a.id === applicationFilter)?.name || 'selected application'
      : scope === 'repository' && repoFilter
        ? 'one repository'
        : 'all repositories in your tenant'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Search</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Search across code and documentation. Scoped to {scopeDescription}.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Search scope</CardTitle>
          <CardDescription>Search across a repository, an application, or the full tenant</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {(['tenant', 'repository', 'application'] as const).map((s) => (
              <Button
                key={s}
                type="button"
                size="sm"
                variant={scope === s ? 'default' : 'outline'}
                className="capitalize"
                onClick={() => setScope(s)}
              >
                {s === 'tenant' ? 'All repos' : s}
              </Button>
            ))}
          </div>

          {scope === 'repository' && (
            <div className="space-y-2">
              <Label htmlFor="repo-scope">Repository ID</Label>
              <Input
                id="repo-scope"
                value={repoFilter}
                onChange={(e) => setRepoFilter(e.target.value)}
                placeholder="Paste repository ID or use ?repo= from repo page"
              />
            </div>
          )}

          {scope === 'application' && (
            <div className="space-y-2">
              <Label htmlFor="app-scope">Application</Label>
              <select
                id="app-scope"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={applicationFilter}
                onChange={(e) => setApplicationFilter(e.target.value)}
              >
                <option value="">Select application</option>
                {applications.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Query</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              runSearch(
                query,
                scope,
                scope === 'repository' ? repoFilter : undefined,
                scope === 'application' ? applicationFilter : undefined
              )
            }}
          >
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. UserService login, checkout cart, Spring version"
              className="flex-1"
            />
            <Button
              type="submit"
              disabled={
                loading ||
                !query.trim() ||
                (scope === 'repository' && !repoFilter) ||
                (scope === 'application' && !applicationFilter)
              }
            >
              <Search className="h-4 w-4" />
              Search
            </Button>
          </form>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : searched && results.length === 0 ? (
        <p className="text-sm text-muted-foreground">No results. Try different terms or re-index a repository.</p>
      ) : (
        <ul className="space-y-3">
          {results.map((r, idx) => (
            <li key={`${r.repository_id}-${r.file_path}-${idx}`}>
              <Card className="shadow-sm">
                <CardContent className="pt-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        {r.type === 'wiki' ? (
                          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                        ) : (
                          <Code2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                        )}
                        <span className="truncate text-sm font-medium">{r.title}</span>
                        <Badge variant="outline" className="capitalize text-xs">
                          {r.type}
                        </Badge>
                        <Badge variant="secondary" className="text-xs">
                          score {r.score}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        <GitBranch className="mr-1 inline h-3 w-3" />
                        {r.repository_name}
                        {' · '}
                        <code className="text-[11px]">
                          {r.file_path}
                          {r.start_line ? `:${r.start_line}` : ''}
                        </code>
                      </p>
                      <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">{r.excerpt}</p>
                    </div>
                    <Button variant="ghost" size="sm" asChild>
                      <Link href={`/dashboard/intelligence/repositories/${r.repository_id}`}>Repo</Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
