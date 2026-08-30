'use client'

import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronDown, ChevronUp, Clock, Info } from 'lucide-react'

export interface AgentEffortStage {
  stage: string
  agent_hours: number
  notes?: string
}

export interface AgentEffort {
  band?: string
  estimated_agent_hours?: number
  stage_breakdown?: AgentEffortStage[]
  confidence?: string
  assumptions?: string[]
  disclaimer?: string
  purpose?: string
  source?: string
}

export interface AssessmentSynthesis {
  narrative?: string
  prioritized_recommendations?: string[]
  risks?: string[]
  source?: string
}

interface AgentEffortCardProps {
  effort?: AgentEffort | null
  synthesis?: AssessmentSynthesis | null
  compact?: boolean
}

const STAGE_LABELS: Record<string, string> = {
  requirements: 'Requirements — clarify scope from wiki & signals',
  tasks: 'Tasks — break work into agent-executable steps',
  code: 'Code — implement migrations, upgrades, refactors',
  test: 'Test — verify against acceptance criteria',
  push: 'Push — open PR / push to target remote',
}

const BAND_LABELS: Record<string, string> = {
  S: 'Small scope',
  M: 'Medium scope',
  L: 'Large scope',
  XL: 'Extra-large scope',
}

export default function AgentEffortCard({
  effort,
  synthesis,
  compact = false,
}: AgentEffortCardProps) {
  const [showEffortDetails, setShowEffortDetails] = useState(false)
  const [showNarrative, setShowNarrative] = useState(false)

  if (!effort && !synthesis) return null

  const topGaps = (synthesis?.prioritized_recommendations || []).slice(0, compact ? 2 : 5)

  return (
    <div className="space-y-4 rounded-lg border bg-card p-4">
      {synthesis?.narrative && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Assessment summary
              {synthesis.source === 'llm' ? (
                <span className="ml-2 font-normal normal-case">(AI-generated)</span>
              ) : null}
            </p>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={() => setShowNarrative((v) => !v)}
            >
              {showNarrative ? 'Hide full narrative' : 'Show full narrative'}
            </Button>
          </div>
          {!showNarrative && topGaps.length > 0 ? (
            <ul className="list-disc space-y-1 pl-4">
              {topGaps.map((r, i) => (
                <li key={i} className="text-sm leading-relaxed">
                  {r}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm leading-relaxed text-muted-foreground">{synthesis.narrative}</p>
          )}
        </div>
      )}

      {!compact && (synthesis?.prioritized_recommendations || []).length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Prioritized recommendations
          </p>
          <ul className="list-disc space-y-1.5 pl-4">
            {(synthesis?.prioritized_recommendations || []).map((r, i) => (
              <li key={i} className="text-sm leading-relaxed">
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {effort && (
        <div className="rounded-md border bg-muted/20 p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <p className="text-sm font-semibold">Estimated Savi pipeline time</p>
              </div>
              <p className="text-xs text-muted-foreground">
                {effort.purpose ||
                  'How long Savi agents may need to run Requirements → Push if you create a plan — not human calendar weeks.'}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {typeof effort.estimated_agent_hours === 'number' && (
                <span className="text-lg font-bold tabular-nums">
                  ~{effort.estimated_agent_hours}h
                </span>
              )}
              {effort.band && (
                <Badge variant="outline" className="text-xs">
                  {BAND_LABELS[effort.band] || `Band ${effort.band}`}
                </Badge>
              )}
              {effort.confidence && (
                <Badge variant="secondary" className="text-xs capitalize">
                  {effort.confidence} confidence
                </Badge>
              )}
            </div>
          </div>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-2 h-7 px-2 text-xs text-muted-foreground"
            onClick={() => setShowEffortDetails((v) => !v)}
          >
            <Info className="mr-1 h-3.5 w-3.5" />
            {showEffortDetails ? 'Hide stage breakdown' : 'How is this estimated?'}
            {showEffortDetails ? (
              <ChevronUp className="ml-1 h-3 w-3" />
            ) : (
              <ChevronDown className="ml-1 h-3 w-3" />
            )}
          </Button>

          {showEffortDetails && (
            <div className="mt-3 space-y-2 border-t pt-3">
              <p className="text-xs text-muted-foreground">
                {effort.disclaimer ||
                  'Agent effort ≠ calendar developer weeks — estimates Savi agent orchestration time for Requirements → Tasks → Code → Test → Push.'}
              </p>
              {(effort.stage_breakdown || []).length > 0 && (
                <ul className="space-y-2">
                  {(effort.stage_breakdown || []).map((s) => (
                    <li
                      key={s.stage}
                      className="flex items-start justify-between gap-3 rounded-md bg-background/80 px-2 py-1.5 text-xs"
                    >
                      <span className="text-muted-foreground">
                        {STAGE_LABELS[s.stage] || s.notes || s.stage}
                      </span>
                      <span className="shrink-0 font-semibold tabular-nums">{s.agent_hours}h</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
