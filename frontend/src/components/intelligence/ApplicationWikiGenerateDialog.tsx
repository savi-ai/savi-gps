'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Loader2 } from 'lucide-react'

export interface MemberWikiReadiness {
  repository_id: string
  name: string
  role?: string | null
  repo_status: string
  has_wiki_site: boolean
  wiki_ready: boolean
  index_run_status?: string | null
  index_progress?: number | null
  last_error?: string | null
}

export interface MemberReadinessSummary {
  all_ready: boolean
  ready_count: number
  total_count: number
  incomplete_count: number
  members: MemberWikiReadiness[]
}

export type AppWikiGenerateMode = 'generate_now' | 'retry_incomplete_then_generate'

interface GenerateResult {
  ok: boolean
  deferred?: boolean
  message?: string
  started?: { repository_id: string; name: string }[]
  member_readiness?: MemberReadinessSummary
}

interface ApplicationWikiGenerateDialogProps {
  open: boolean
  applicationId: string
  onOpenChange: (open: boolean) => void
  onCompleted: (result: GenerateResult) => void
}

function statusBadge(member: MemberWikiReadiness) {
  if (member.wiki_ready) return { label: 'Wiki ready', variant: 'default' as const }
  if (member.index_run_status === 'pending' || member.index_run_status === 'running') {
    return {
      label: `Analyzing ${member.index_progress ?? 0}%`,
      variant: 'secondary' as const,
    }
  }
  if (member.repo_status === 'error' || member.index_run_status === 'failed') {
    return { label: 'Failed', variant: 'destructive' as const }
  }
  return { label: member.repo_status || 'Pending', variant: 'outline' as const }
}

export function ApplicationWikiGenerateDialog({
  open,
  applicationId,
  onOpenChange,
  onCompleted,
}: ApplicationWikiGenerateDialogProps) {
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState<AppWikiGenerateMode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [readiness, setReadiness] = useState<MemberReadinessSummary | null>(null)

  const loadReadiness = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get(
        `/api/v1/intelligence/applications/${applicationId}/wiki/status`
      )
      setReadiness(res.data?.member_readiness || null)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to load member wiki status')
      setReadiness(null)
    } finally {
      setLoading(false)
    }
  }, [applicationId])

  useEffect(() => {
    if (open) void loadReadiness()
  }, [open, loadReadiness])

  const submit = async (mode: AppWikiGenerateMode) => {
    setSubmitting(mode)
    setError(null)
    try {
      const res = await apiClient.post<GenerateResult>(
        `/api/v1/intelligence/applications/${applicationId}/wiki/generate`,
        { mode }
      )
      onCompleted(res.data)
      onOpenChange(false)
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Failed to start application wiki generation')
    } finally {
      setSubmitting(null)
    }
  }

  const allReady = readiness?.all_ready === true
  const incomplete = readiness?.members.filter((m) => !m.wiki_ready) || []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Generate application wiki</DialogTitle>
          <DialogDescription>
            Application wiki combines member repository wikis. Choose how to proceed when some
            repos are not ready yet.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking member repositories…
          </div>
        ) : readiness ? (
          <div className="space-y-3">
            <p className="text-sm">
              Member wikis ready:{' '}
              <span className="font-medium">
                {readiness.ready_count}/{readiness.total_count}
              </span>
              {allReady ? ' — all set.' : null}
            </p>
            <ul className="max-h-56 space-y-2 overflow-y-auto rounded-md border p-2">
              {readiness.members.map((m) => {
                const badge = statusBadge(m)
                return (
                  <li
                    key={m.repository_id}
                    className="flex items-start justify-between gap-2 text-sm"
                  >
                    <div className="min-w-0">
                      <Link
                        href={`/dashboard/intelligence/repositories/${m.repository_id}`}
                        className="font-medium text-primary hover:underline"
                        onClick={() => onOpenChange(false)}
                      >
                        {m.name}
                      </Link>
                      {m.role ? (
                        <span className="ml-1 text-xs text-muted-foreground">({m.role})</span>
                      ) : null}
                      {!m.wiki_ready && m.last_error ? (
                        <p className="mt-0.5 line-clamp-2 text-xs text-destructive">
                          {m.last_error}
                        </p>
                      ) : null}
                    </div>
                    <Badge variant={badge.variant} className="shrink-0 capitalize">
                      {badge.label}
                    </Badge>
                  </li>
                )
              })}
            </ul>
            {!allReady && incomplete.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                You can generate the application wiki from whatever is ready now, or re-run
                analysis on incomplete repos first. When those finish successfully, the
                application wiki starts automatically.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No member readiness data available.</p>
        )}

        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        <DialogFooter className="flex-col gap-2 sm:flex-col sm:space-x-0">
          {allReady ? (
            <Button
              disabled={!!submitting || loading}
              onClick={() => void submit('generate_now')}
            >
              {submitting === 'generate_now' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              Generate application wiki
            </Button>
          ) : (
            <>
              <Button
                disabled={!!submitting || loading || !readiness?.total_count}
                onClick={() => void submit('generate_now')}
              >
                {submitting === 'generate_now' ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : null}
                Generate app wiki now
                {readiness
                  ? ` (${readiness.ready_count}/${readiness.total_count} ready)`
                  : ''}
              </Button>
              <Button
                variant="outline"
                disabled={
                  !!submitting ||
                  loading ||
                  !readiness?.incomplete_count ||
                  incomplete.every(
                    (m) =>
                      m.index_run_status === 'pending' || m.index_run_status === 'running'
                  )
                }
                onClick={() => void submit('retry_incomplete_then_generate')}
              >
                {submitting === 'retry_incomplete_then_generate' ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : null}
                Retry incomplete repos first
              </Button>
            </>
          )}
          <Button
            variant="ghost"
            disabled={!!submitting}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
