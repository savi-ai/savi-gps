'use client'

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/lib/axios'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { MermaidDiagram } from '@/components/intelligence/MermaidDiagram'
import { Network, Search } from 'lucide-react'

interface BlastRadiusAnchor {
  anchor: string
  label: string
  summary?: string
}

interface BlastRadiusResult {
  symbol: string
  anchor: string | null
  summary: string
  mermaid: string
  nodes: Array<{ id: string; label?: string; role?: string }>
  edges: Array<{ source: string; target: string }>
  cross_repo: unknown[]
  hops: number
  cached?: boolean
  available?: boolean
}

interface BlastRadiusPanelProps {
  repoId: string
  graphAvailable: boolean
  repoStatus: string
}

export function BlastRadiusPanel({
  repoId,
  graphAvailable,
  repoStatus,
}: BlastRadiusPanelProps) {
  const [query, setQuery] = useState('')
  const [hops, setHops] = useState(1)
  const [anchors, setAnchors] = useState<BlastRadiusAnchor[]>([])
  const [suggestions, setSuggestions] = useState<Array<{ qualified_name: string; name: string }>>([])
  const [result, setResult] = useState<BlastRadiusResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [anchorsLoading, setAnchorsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadAnchors = useCallback(async () => {
    if (!graphAvailable) {
      setAnchorsLoading(false)
      return
    }
    try {
      const res = await apiClient.get(
        `/api/v1/intelligence/repos/${repoId}/graph/blast-radius/anchors`
      )
      setAnchors(res.data?.anchors ?? [])
    } catch {
      setAnchors([])
    } finally {
      setAnchorsLoading(false)
    }
  }, [repoId, graphAvailable])

  useEffect(() => {
    loadAnchors()
  }, [loadAnchors])

  const searchSymbols = async (q: string) => {
    if (!q.trim() || !graphAvailable) {
      setSuggestions([])
      return
    }
    try {
      const res = await apiClient.get(`/api/v1/intelligence/repos/${repoId}/graph/symbols`, {
        params: { q, limit: 8 },
      })
      setSuggestions(res.data?.symbols ?? [])
    } catch {
      setSuggestions([])
    }
  }

  const runBlastRadius = async (symbol: string, hopCount = hops) => {
    const trimmed = symbol.trim()
    if (!trimmed) return
    setLoading(true)
    setError(null)
    setQuery(trimmed)
    setSuggestions([])
    try {
      const res = await apiClient.get(
        `/api/v1/intelligence/repos/${repoId}/graph/blast-radius`,
        { params: { symbol: trimmed, hops: hopCount } }
      )
      setResult(res.data)
      if (!res.data?.available) {
        setError(res.data?.summary || 'Symbol not found in call graph')
      }
    } catch (e: unknown) {
      setResult(null)
      setError(e instanceof Error ? e.message : 'Failed to load blast radius')
    } finally {
      setLoading(false)
    }
  }

  if (repoStatus !== 'ready' && !graphAvailable) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Network className="h-4 w-4" />
            Blast radius
          </CardTitle>
          <CardDescription>
            Index this repository first to build a call graph for Java and Python sources.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (!graphAvailable) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Network className="h-4 w-4" />
            Blast radius
          </CardTitle>
          <CardDescription>
            No call graph available yet. Re-index after adding Java or Python code, or use Rebuild
            graph from the API if the repo was indexed before graph extraction shipped.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Network className="h-4 w-4" />
          Blast radius
        </CardTitle>
        <CardDescription>
          Pick a symbol to see who calls it and what it calls — one hop at a time.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Search symbol (e.g. OrderService.submit)"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                void searchSymbols(e.target.value)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void runBlastRadius(query)
              }}
            />
            {suggestions.length > 0 && (
              <ul className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-md border bg-popover shadow-md">
                {suggestions.map((s) => (
                  <li key={s.qualified_name}>
                    <button
                      type="button"
                      className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                      onClick={() => void runBlastRadius(s.qualified_name)}
                    >
                      <span className="font-medium">{s.name}</span>
                      <span className="ml-2 text-xs text-muted-foreground">{s.qualified_name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <select
            className="flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={hops}
            onChange={(e) => setHops(Number(e.target.value))}
          >
            <option value={1}>1 hop</option>
            <option value={2}>2 hops</option>
          </select>
          <Button onClick={() => void runBlastRadius(query)} disabled={loading || !query.trim()}>
            {loading ? 'Loading…' : 'Analyze'}
          </Button>
        </div>

        {anchorsLoading ? (
          <Skeleton className="h-8 w-full" />
        ) : anchors.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Suggested anchors</p>
            <div className="flex flex-wrap gap-2">
              {anchors.map((a) => (
                <Button
                  key={a.anchor}
                  variant="outline"
                  size="sm"
                  className="h-auto max-w-full whitespace-normal py-1 text-left"
                  onClick={() => void runBlastRadius(a.anchor)}
                >
                  {a.label}
                </Button>
              ))}
            </div>
          </div>
        ) : null}

        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}

        {loading && <Skeleton className="h-48 w-full" />}

        {result?.available && (
          <div className="space-y-4">
            <div className="rounded-lg border bg-muted/30 p-4">
              <p className="text-sm leading-relaxed">{result.summary}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {result.anchor && (
                  <Badge variant="secondary" className="font-mono text-xs">
                    {result.anchor}
                  </Badge>
                )}
                {result.cached && <Badge variant="outline">cached</Badge>}
                <Badge variant="outline">{result.nodes.length} nodes</Badge>
                <Badge variant="outline">{result.hops} hop{result.hops !== 1 ? 's' : ''}</Badge>
              </div>
            </div>
            {result.mermaid ? (
              <MermaidDiagram chart={result.mermaid} />
            ) : (
              <p className="text-sm text-muted-foreground">No diagram — isolated symbol with no edges.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
