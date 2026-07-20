'use client'

import { Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export interface IndexRunInfo {
  status: string
  progress: number
  error?: string | null
}

function getAnalysisStage(progress: number, status: string): { title: string; detail: string } {
  if (status === 'pending') {
    return {
      title: 'Queued for analysis',
      detail: 'Waiting for the index worker to pick up this repository…',
    }
  }
  if (status === 'failed') {
    return { title: 'Analysis failed', detail: 'See error details below and try re-indexing.' }
  }
  if (progress < 20) {
    return { title: 'Cloning repository', detail: 'Fetching source code from GitHub…' }
  }
  if (progress < 30) {
    return { title: 'Security scan', detail: 'Scanning for secrets before indexing…' }
  }
  if (progress < 50) {
    return { title: 'Chunking code', detail: 'Splitting files for search and wiki generation…' }
  }
  if (progress < 85) {
    return { title: 'Indexing for semantic search', detail: 'Building search index for code and wiki…' }
  }
  if (progress < 100) {
    return { title: 'Wiki Agent', detail: 'Generating HTML wiki, diagrams, and analysis attributes…' }
  }
  return { title: 'Analysis complete', detail: 'Repository is ready.' }
}

const STAGES = [
  { key: 'clone', label: 'Clone', min: 0 },
  { key: 'scan', label: 'Scan', min: 20 },
  { key: 'chunk', label: 'Chunk', min: 30 },
  { key: 'embed', label: 'Index', min: 50 },
  { key: 'wiki', label: 'Wiki', min: 85 },
  { key: 'done', label: 'Done', min: 100 },
]

interface IndexingProgressCardProps {
  run: IndexRunInfo
  repositoryName?: string
  compact?: boolean
  className?: string
}

export function isAnalysisActive(run?: IndexRunInfo | null, repoStatus?: string): boolean {
  if (!run) return repoStatus === 'indexing'
  return ['pending', 'running'].includes(run.status) || repoStatus === 'indexing'
}

export function IndexingProgressCard({
  run,
  repositoryName,
  compact = false,
  className,
}: IndexingProgressCardProps) {
  const active = isAnalysisActive(run, undefined)
  const failed = run.status === 'failed'
  const progress = run.progress ?? 0
  const stage = getAnalysisStage(progress, run.status)

  if (!active && !failed) return null

  const displayProgress = run.status === 'pending' ? 3 : Math.max(progress, 5)

  return (
    <Card
      className={cn(
        'border-primary/20 bg-primary/5',
        failed && 'border-destructive/30 bg-destructive/5',
        className
      )}
    >
      <CardContent className={cn('pt-4', compact ? 'pb-3' : 'pb-5')}>
        <div className="flex items-start gap-3">
          {failed ? (
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
          ) : run.status === 'completed' || progress >= 100 ? (
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          ) : (
            <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-primary" />
          )}
          <div className="min-w-0 flex-1 space-y-2">
            <div>
              <p className="text-sm font-semibold">
                {failed ? 'Analysis failed' : `Analyzing${repositoryName ? `: ${repositoryName}` : ''}`}
              </p>
              <p className="text-xs text-muted-foreground">{stage.detail}</p>
            </div>

            {!failed && (
              <>
                <div className="flex items-center gap-2">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-all duration-500"
                      style={{ width: `${displayProgress}%` }}
                    />
                  </div>
                  <span className="w-10 text-right text-xs font-medium tabular-nums">
                    {run.status === 'pending' ? '…' : `${progress}%`}
                  </span>
                </div>

                {!compact && (
                  <div className="flex justify-between gap-1 pt-1">
                    {STAGES.map((s, i) => {
                      const reached = progress >= s.min || (run.status === 'pending' && i === 0)
                      const current =
                        progress >= s.min &&
                        (i === STAGES.length - 1 || progress < STAGES[i + 1].min)
                      return (
                        <div key={s.key} className="flex flex-1 flex-col items-center gap-1">
                          <div
                            className={cn(
                              'h-1.5 w-full rounded-full',
                              reached ? 'bg-primary' : 'bg-muted',
                              current && 'ring-2 ring-primary/30'
                            )}
                          />
                          <span
                            className={cn(
                              'text-[10px]',
                              reached ? 'font-medium text-foreground' : 'text-muted-foreground'
                            )}
                          >
                            {s.label}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </>
            )}

            {failed && run.error && (
              <p className="text-xs text-destructive">{run.error}</p>
            )}

            {!compact && active && (
              <p className="text-[11px] text-muted-foreground">
                Progress is saved on the server — you can leave this page or log out and return later.
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
