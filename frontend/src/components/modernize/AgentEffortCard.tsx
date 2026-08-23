'use client'

import { Badge } from '@/components/ui/badge'

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

export default function AgentEffortCard({
  effort,
  synthesis,
  compact = false,
}: AgentEffortCardProps) {
  if (!effort && !synthesis) return null

  return (
    <div className="space-y-3 rounded-md border bg-muted/20 p-3">
      {synthesis?.narrative && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">
            Assessment narrative
            {synthesis.source === 'llm' ? (
              <span className="ml-2 font-normal normal-case text-muted-foreground">
                (LLM)
              </span>
            ) : null}
          </p>
          <p className="text-sm leading-relaxed">{synthesis.narrative}</p>
        </div>
      )}

      {effort && (
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <p className="text-xs font-medium uppercase text-muted-foreground">
              Agent effort
            </p>
            {effort.band && (
              <Badge variant="outline" className="text-xs">
                Band {effort.band}
              </Badge>
            )}
            {typeof effort.estimated_agent_hours === 'number' && (
              <span className="text-sm font-semibold">
                {effort.estimated_agent_hours} agent-hours
              </span>
            )}
            {effort.confidence && (
              <span className="text-xs text-muted-foreground capitalize">
                {effort.confidence} confidence
              </span>
            )}
          </div>
          <p className="mb-2 text-xs text-muted-foreground">
            {effort.disclaimer ||
              'Agent effort ≠ calendar developer weeks — Savi orchestration estimate for Requirements → Push.'}
          </p>
          {!compact && (effort.stage_breakdown || []).length > 0 && (
            <ul className="space-y-1">
              {(effort.stage_breakdown || []).map((s) => (
                <li key={s.stage} className="flex justify-between gap-2 text-xs">
                  <span className="capitalize text-muted-foreground">
                    {s.stage}
                    {s.notes ? ` — ${s.notes}` : ''}
                  </span>
                  <span className="shrink-0 font-medium">{s.agent_hours}h</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {!compact && (synthesis?.prioritized_recommendations || []).length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">
            Prioritized recommendations
          </p>
          <ul className="list-disc space-y-1 pl-4">
            {(synthesis?.prioritized_recommendations || []).map((r, i) => (
              <li key={i} className="text-xs">
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
