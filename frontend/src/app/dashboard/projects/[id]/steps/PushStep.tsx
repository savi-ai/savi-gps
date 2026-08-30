'use client'

import { useState } from 'react'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2, Upload } from 'lucide-react'
import type { StepContentProps } from '../types'

/**
 * W5 Push stage (Alpha preview): confirm then push generated code to the
 * user-provided target GitHub repo. Never invents a remote.
 */
export function PushStepContent({ project, canEdit, onUpdate }: StepContentProps) {
  const [pushing, setPushing] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{
    success?: boolean
    branch_name?: string
    base_branch?: string
    message?: string
    repo_url?: string
  } | null>(null)

  const targetUrl = project.github_repo_url
  const targetBranch = project.target_branch || 'main'
  const hasCode = Boolean(project.code_implementation)
  const hasTests = Boolean(project.tests)
  const alreadyPushed =
    project.current_step === 'push' || Boolean(result?.success)

  const handlePush = async () => {
    if (!targetUrl) {
      setError('Target GitHub repository URL is missing. Re-spawn from the plan with a URL.')
      return
    }
    if (!hasCode) {
      setError('Generate code in the Code step before pushing.')
      return
    }
    setPushing(true)
    setError(null)
    try {
      const res = await apiClient.post(
        `/api/v1/golden-path/projects/${project.id}/push-to-github`
      )
      setResult(res.data)
      setConfirmOpen(false)
      onUpdate()
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setError(detail || 'Push failed')
    } finally {
      setPushing(false)
    }
  }

  return (
    <Card className="border-l-4 border-emerald-600/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Upload className="h-4 w-4" />
          Push to target repository
        </CardTitle>
        <CardDescription>
          Alpha preview — pushes a Savi branch to the GitHub URL you provided when starting
          modernization. Does not invent a remote.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border bg-muted/30 p-4 space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground">Target repo</span>
            {targetUrl ? (
              <a
                href={targetUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
              >
                {targetUrl}
                <ExternalLink className="h-3 w-3" />
              </a>
            ) : (
              <Badge variant="destructive">Not configured</Badge>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">Base branch · {targetBranch}</Badge>
            <Badge variant={hasCode ? 'secondary' : 'outline'}>
              Code {hasCode ? 'ready' : 'missing'}
            </Badge>
            <Badge variant={hasTests ? 'secondary' : 'outline'}>
              Tests {hasTests ? 'ready' : 'optional'}
            </Badge>
          </div>
        </div>

        {!hasTests && hasCode && (
          <p className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Tests are not present yet. You can still push (Alpha). Prefer completing the Test
            step first when possible.
          </p>
        )}

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {alreadyPushed && (
          <div className="flex items-start gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-800 dark:text-emerald-300">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">Push recorded</p>
              {result?.branch_name && (
                <p className="text-xs opacity-90">Branch: {result.branch_name}</p>
              )}
              <p className="mt-1 text-xs opacity-80">
                Open a PR on GitHub from the Savi branch into {targetBranch} when ready.
              </p>
            </div>
          </div>
        )}

        {confirmOpen ? (
          <div className="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
            <p className="text-sm font-medium">Confirm push</p>
            <p className="text-sm text-muted-foreground">
              This will push generated code to <strong>{targetUrl}</strong> on a Savi working
              branch. Confirm this is the repo you intended — Savi never invents a remote.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => void handlePush()} disabled={pushing || !canEdit}>
                {pushing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                Confirm &amp; push
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={pushing}
                onClick={() => setConfirmOpen(false)}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <Button
            size="sm"
            disabled={!canEdit || !targetUrl || !hasCode || pushing || alreadyPushed}
            onClick={() => setConfirmOpen(true)}
          >
            <Upload className="h-4 w-4" />
            {alreadyPushed ? 'Already pushed' : 'Push to GitHub…'}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
