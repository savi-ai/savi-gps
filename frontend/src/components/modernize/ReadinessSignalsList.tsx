'use client'

import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, MinusCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface ReadinessSignal {
  id: string
  label: string
  value: string
  score?: number | null
  status: string
  detail: string
  recommendation?: string
  source?: string
  weight?: number
  category?: string
  applicable?: boolean
  remediation_scope?: string
  repository_id?: string
  repository_name?: string
  failed_policies?: Array<{
    policy_name?: string
    rule_id: string
    message: string
  }>
}

const CATEGORY_LABELS: Record<string, string> = {
  platform: 'Platform & documentation',
  runtime: 'Runtime',
  build: 'Build & framework',
  infra: 'Infrastructure & data',
  general: 'Other signals',
}

export function signalCategoryLabel(category?: string): string {
  return CATEGORY_LABELS[category || ''] || CATEGORY_LABELS.general
}

export function groupSignalsByCategory(signals: ReadinessSignal[]): Array<[string, ReadinessSignal[]]> {
  const groups = new Map<string, ReadinessSignal[]>()
  const order = ['platform', 'runtime', 'build', 'infra', 'general']

  for (const signal of signals) {
    const cat = signal.category || (signal.source === 'platform' ? 'platform' : 'general')
    const list = groups.get(cat) || []
    list.push(signal)
    groups.set(cat, list)
  }

  return order
    .filter((cat) => groups.has(cat))
    .map((cat) => [cat, groups.get(cat)!] as [string, ReadinessSignal[]])
}

interface ReadinessSignalRowProps {
  signal: ReadinessSignal
  showRepo?: boolean
}

export function ReadinessSignalRow({ signal, showRepo = false }: ReadinessSignalRowProps) {
  const [expanded, setExpanded] = useState(false)
  const isNa = signal.status === 'na' || signal.applicable === false

  const Icon = isNa ? MinusCircle : signal.status === 'good' ? CheckCircle2 : AlertTriangle
  const iconClass = isNa
    ? 'text-muted-foreground'
    : signal.status === 'good'
      ? 'text-emerald-600'
      : signal.status === 'bad'
        ? 'text-destructive'
        : 'text-amber-600'

  const failures = signal.failed_policies || []

  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="flex min-w-0 flex-1 items-start gap-2.5">
        <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', iconClass)} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium">{signal.label}</p>
            {showRepo && signal.repository_name && (
              <Badge variant="outline" className="text-[10px] font-normal">
                {signal.repository_name}
              </Badge>
            )}
            {isNa && (
              <Badge variant="secondary" className="text-[10px] font-normal">
                Not applicable
              </Badge>
            )}
          </div>
          {!isNa && signal.recommendation && signal.status !== 'good' && (
            <p className="mt-1 text-xs text-amber-800 dark:text-amber-200">
              {signal.recommendation}
            </p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {signal.source === 'analysis_config' && !isNa && (
              <Badge variant="outline" className="text-[10px] font-normal">
                Analysis Config
              </Badge>
            )}
            {signal.remediation_scope && signal.status !== 'good' && !isNa && (
              <Badge variant="secondary" className="text-[10px] font-normal">
                {signal.remediation_scope === 'simple_fix'
                  ? 'Fix plan'
                  : signal.remediation_scope === 'modernization'
                    ? 'Modernize plan'
                    : 'Either plan'}
              </Badge>
            )}
            {signal.detail && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 px-1.5 text-[10px] text-muted-foreground"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? (
                  <>
                    Hide evidence <ChevronUp className="ml-0.5 h-3 w-3" />
                  </>
                ) : (
                  <>
                    Show evidence <ChevronDown className="ml-0.5 h-3 w-3" />
                  </>
                )}
              </Button>
            )}
          </div>
          {expanded && signal.detail && (
            <p className="mt-1.5 rounded-md bg-muted/40 px-2 py-1.5 text-xs text-muted-foreground">
              {signal.detail}
            </p>
          )}
          {failures.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {failures.map((f, i) => (
                <li key={`${f.rule_id}-${i}`} className="text-xs text-destructive">
                  Policy: {f.message}
                  {f.policy_name ? ` (${f.policy_name})` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <p className={cn('text-sm font-medium', isNa && 'text-muted-foreground')}>
          {signal.value}
        </p>
        {!isNa && typeof signal.score === 'number' && (
          <p className="text-xs tabular-nums text-muted-foreground">{signal.score}/100</p>
        )}
      </div>
    </div>
  )
}

interface ReadinessSignalsListProps {
  signals: ReadinessSignal[]
  showRepo?: boolean
  hideNotApplicable?: boolean
  emptyMessage?: string
}

export default function ReadinessSignalsList({
  signals,
  showRepo = false,
  hideNotApplicable = true,
  emptyMessage = 'No assessment signals.',
}: ReadinessSignalsListProps) {
  const [showNa, setShowNa] = useState(false)

  const filtered = signals.filter((s) => {
    const isNa = s.status === 'na' || s.applicable === false
    if (hideNotApplicable && !showNa && isNa) return false
    return true
  })

  const naCount = signals.filter((s) => s.status === 'na' || s.applicable === false).length
  const groups = groupSignalsByCategory(filtered)

  if (filtered.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyMessage}</p>
  }

  return (
    <div className="space-y-4">
      {hideNotApplicable && naCount > 0 && (
        <div className="flex items-center justify-between rounded-md border border-dashed px-3 py-2">
          <p className="text-xs text-muted-foreground">
            {naCount} signal{naCount === 1 ? '' : 's'} not applicable to this stack (hidden)
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => setShowNa((v) => !v)}
          >
            {showNa ? 'Hide' : 'Show'}
          </Button>
        </div>
      )}
      {groups.map(([category, items]) => (
        <div key={category} className="rounded-md border">
          <div className="border-b bg-muted/30 px-3 py-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {signalCategoryLabel(category)}
            </p>
          </div>
          <div className="divide-y px-3">
            {items.map((signal) => (
              <ReadinessSignalRow
                key={`${signal.id}-${signal.repository_id || ''}`}
                signal={signal}
                showRepo={showRepo}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export const READINESS_LEVEL_VARIANT: Record<
  string,
  'default' | 'secondary' | 'destructive' | 'outline'
> = {
  high: 'default',
  medium: 'secondary',
  low: 'destructive',
  ready: 'default',
  partial: 'secondary',
  blocked: 'destructive',
}

export function formatReadinessLevel(level?: string | null): string {
  if (!level) return 'Unknown'
  const map: Record<string, string> = {
    ready: 'Ready',
    partial: 'Partial readiness',
    blocked: 'Blocked',
    high: 'High readiness',
    medium: 'Partial readiness',
    low: 'Low readiness',
  }
  return map[level] || level.replace(/_/g, ' ')
}
