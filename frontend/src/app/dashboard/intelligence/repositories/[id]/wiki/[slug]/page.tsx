'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ArrowLeft, CheckCircle2, RefreshCw, XCircle, AlertTriangle } from 'lucide-react'
import { WikiMarkdownContent } from '@/components/intelligence/WikiMarkdownContent'
import { WikiChatPanel } from '@/components/intelligence/WikiChatPanel'

interface WikiClaim {
  id: string
  claim_text: string
  citation_file: string
  line_start: number | null
  line_end: number | null
  verified: boolean
  status: string
}

interface WikiPageData {
  title: string
  content_md: string
  state: string
  drift_status: string
  verified_claim_count: number
  total_claim_count: number
  citation_coverage: number
  review_notes?: string | null
}

function StateBadge({ state }: { state: string }) {
  if (state === 'live') {
    return <Badge className="bg-emerald-600 hover:bg-emerald-600">Live</Badge>
  }
  return <Badge variant="secondary">Draft</Badge>
}

function DriftBadge({ drift }: { drift: string }) {
  if (drift === 'stale') {
    return (
      <Badge variant="destructive" className="gap-1">
        <AlertTriangle className="h-3 w-3" />
        Stale — re-indexed
      </Badge>
    )
  }
  if (drift === 'pending_review') {
    return <Badge variant="outline">Pending review</Badge>
  }
  return null
}

export default function WikiPageReader() {
  const params = useParams()
  const router = useRouter()
  const { hasCapability, hasPermission } = useAuth()
  const repoId = params?.id as string
  const slug = params?.slug as string
  const [page, setPage] = useState<WikiPageData | null>(null)
  const [claims, setClaims] = useState<WikiClaim[]>([])
  const [loading, setLoading] = useState(true)
  const [notes, setNotes] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canApprove = hasPermission('can_approve_wiki')

  const load = async () => {
    try {
      const [pageRes, claimsRes] = await Promise.all([
        apiClient.get(`/api/v1/intelligence/repos/${repoId}/pages/${slug}`),
        apiClient.get(`/api/v1/intelligence/repos/${repoId}/pages/${slug}/claims`),
      ])
      setPage(pageRes.data)
      setClaims(claimsRes.data?.claims || [])
      setError(null)
    } catch {
      setPage(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    load()
  }, [repoId, slug, hasCapability, router])

  const runVerify = async () => {
    setActionLoading(true)
    try {
      await apiClient.post(`/api/v1/intelligence/repos/${repoId}/pages/${slug}/verify`)
      await load()
    } finally {
      setActionLoading(false)
    }
  }

  const approve = async () => {
    setActionLoading(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/intelligence/repos/${repoId}/pages/${slug}/approve`, {
        notes: notes || null,
      })
      await load()
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Approval failed'
      setError(msg)
    } finally {
      setActionLoading(false)
    }
  }

  const reject = async () => {
    setActionLoading(true)
    setError(null)
    try {
      await apiClient.post(`/api/v1/intelligence/repos/${repoId}/pages/${slug}/reject`, {
        feedback: notes || null,
      })
      await load()
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Rejection failed'
      setError(msg)
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) return <Skeleton className="h-64 w-full" />

  if (!page) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        Page not found
      </div>
    )
  }

  const coveragePct = Math.round((page.citation_coverage || 0) * 100)

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => router.push(`/dashboard/intelligence/repositories/${repoId}`)}
      >
        <ArrowLeft className="h-4 w-4" />
        Back to repository
      </Button>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{page.title}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            <StateBadge state={page.state} />
            <DriftBadge drift={page.drift_status} />
            <Badge variant="outline">
              Citations: {page.verified_claim_count}/{page.total_claim_count} ({coveragePct}%)
            </Badge>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={runVerify} disabled={actionLoading}>
            <RefreshCw className={`h-4 w-4 ${actionLoading ? 'animate-spin' : ''}`} />
            Re-verify
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {canApprove && page.state === 'draft' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Review &amp; publish</CardTitle>
            <CardDescription>
              Approve to publish as live wiki. Requires at least 50% verified citations when
              citations exist.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              placeholder="Optional review notes…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
            />
            <div className="flex gap-2">
              <Button onClick={approve} disabled={actionLoading}>
                <CheckCircle2 className="h-4 w-4" />
                Approve &amp; publish
              </Button>
              <Button variant="outline" onClick={reject} disabled={actionLoading}>
                <XCircle className="h-4 w-4" />
                Request changes
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {claims.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Citation verification</CardTitle>
            <CardDescription>
              File references extracted from this page and checked against the index.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="max-h-48 divide-y overflow-y-auto text-sm">
              {claims.map((c) => (
                <li key={c.id} className="flex items-center justify-between py-2">
                  <code className="text-xs">{c.citation_file}</code>
                  <Badge
                    variant={c.verified ? 'default' : 'destructive'}
                    className={c.verified ? 'bg-emerald-600 hover:bg-emerald-600' : undefined}
                  >
                    {c.status}
                  </Badge>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <div className="rounded-lg border bg-card p-6">
        <WikiMarkdownContent content={page.content_md} />
      </div>

      <WikiChatPanel
        repoId={repoId}
        pageContext={`# ${page.title}\n\n${page.content_md}`}
      />
    </div>
  )
}
