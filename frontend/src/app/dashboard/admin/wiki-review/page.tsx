'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ClipboardCheck } from 'lucide-react'

interface RepoSummary {
  id: string
  name: string
  github_full_name?: string
}

interface WikiPageSummary {
  slug: string
  title: string
  state: string
  drift_status: string
  verified_claim_count: number
  total_claim_count: number
  citation_coverage: number
}

interface QualitySummary {
  repository_id: string
  draft_count: number
  live_count: number
  stale_count: number
  citation_coverage: number
  pages: WikiPageSummary[]
}

export default function AdminWikiReviewPage() {
  const router = useRouter()
  const { hasPermission } = useAuth()
  const [repos, setRepos] = useState<RepoSummary[]>([])
  const [queue, setQueue] = useState<
    Array<WikiPageSummary & { repoId: string; repoName: string }>
  >([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!hasPermission('can_approve_wiki')) {
      router.push('/dashboard')
      return
    }

    const load = async () => {
      try {
        const reposRes = await apiClient.get('/api/v1/intelligence/repos')
        const repoList: RepoSummary[] = reposRes.data?.repositories || []
        setRepos(repoList)

        const summaries = await Promise.all(
          repoList.map(async (repo) => {
            try {
              const res = await apiClient.get(
                `/api/v1/intelligence/repos/${repo.id}/wiki-quality`
              )
              return { repo, summary: res.data as QualitySummary }
            } catch {
              return { repo, summary: null }
            }
          })
        )

        const pending: Array<WikiPageSummary & { repoId: string; repoName: string }> = []
        for (const { repo, summary } of summaries) {
          if (!summary?.pages) continue
          for (const page of summary.pages) {
            if (page.state === 'draft' || page.drift_status === 'stale') {
              pending.push({
                ...page,
                repoId: repo.id,
                repoName: repo.github_full_name || repo.name,
              })
            }
          }
        }
        setQueue(pending)
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [hasPermission, router])

  if (loading) return <Skeleton className="h-48 w-full" />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <ClipboardCheck className="h-6 w-6" />
          Wiki Review
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Admin queue for draft and out-of-date wiki pages across{' '}
          {repos.length} connected {repos.length === 1 ? 'repository' : 'repositories'}.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Review queue</CardTitle>
          <CardDescription>
            Approve draft wiki pages after verifying sources. Out-of-date pages need re-review after
            re-indexing.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {queue.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No pages pending review. Connect a repository and run indexing to generate wiki pages.
            </p>
          ) : (
            <ul className="divide-y">
              {queue.map((item) => (
                <li
                  key={`${item.repoId}-${item.slug}`}
                  className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="text-xs text-muted-foreground">{item.repoName}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={item.state === 'live' ? 'default' : 'secondary'}>
                      {item.state}
                    </Badge>
                    {item.drift_status === 'stale' && (
                      <Badge variant="destructive">Out of date</Badge>
                    )}
                    <Badge variant="outline">
                      {Math.round((item.citation_coverage || 0) * 100)}% verified
                    </Badge>
                    <Link
                      href={`/dashboard/intelligence/repositories/${item.repoId}/wiki/${item.slug}`}
                      className="text-sm font-medium text-primary hover:underline"
                    >
                      Review
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
