'use client'

import { useCallback, useEffect, useState } from 'react'
import apiClient from '@/lib/axios'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { MermaidDiagram } from '@/components/intelligence/MermaidDiagram'
import { Boxes } from 'lucide-react'

interface DomainGraphResult {
  summary: string
  mermaid: string
  entities: Array<{ name: string; source?: string; fields?: unknown[] }>
  relationships: Array<{ from_entity: string; to_entity: string; label: string }>
  sources: string[]
  entity_count: number
  relationship_count: number
  available?: boolean
  cached?: boolean
}

interface DomainGraphPanelProps {
  repoId: string
  repoStatus: string
}

export function DomainGraphPanel({ repoId, repoStatus }: DomainGraphPanelProps) {
  const [result, setResult] = useState<DomainGraphResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get(
        `/api/v1/intelligence/repos/${repoId}/analysis/domain-graph`
      )
      setResult(res.data)
    } catch (e: unknown) {
      setResult(null)
      setError(e instanceof Error ? e.message : 'Failed to load domain graph')
    } finally {
      setLoading(false)
    }
  }, [repoId])

  useEffect(() => {
    if (repoStatus === 'ready') {
      void load()
    } else {
      setLoading(false)
    }
  }, [repoStatus, load])

  if (repoStatus !== 'ready') {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Boxes className="h-4 w-4" />
            Domain model
          </CardTitle>
          <CardDescription>
            Index this repository to extract entities from JPA mappings, SQL DDL, or protobuf.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (loading) {
    return <Skeleton className="h-48 w-full" />
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Boxes className="h-4 w-4" />
            Domain model
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive">{error}</p>
        </CardContent>
      </Card>
    )
  }

  if (!result?.available) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Boxes className="h-4 w-4" />
            Domain model
          </CardTitle>
          <CardDescription>{result?.summary}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No JPA <code className="text-xs">@Entity</code> classes, SQL{' '}
            <code className="text-xs">CREATE TABLE</code> scripts, or{' '}
            <code className="text-xs">.proto</code> messages were detected. This is common for
            frontend-only or infrastructure repos.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Boxes className="h-4 w-4" />
          Domain model
        </CardTitle>
        <CardDescription>
          Entity-relationship view extracted from ORM mappings, SQL schema, or protobuf.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border bg-muted/30 p-4">
          <p className="text-sm leading-relaxed">{result.summary}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="outline">{result.entity_count} entities</Badge>
            <Badge variant="outline">{result.relationship_count} relationships</Badge>
            {result.sources.map((s) => (
              <Badge key={s} variant="secondary" className="uppercase">
                {s}
              </Badge>
            ))}
            {result.cached && <Badge variant="outline">cached</Badge>}
          </div>
        </div>

        {result.mermaid && <MermaidDiagram chart={result.mermaid} />}

        {result.entities.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Entities</p>
            <div className="flex flex-wrap gap-2">
              {result.entities.map((e) => (
                <Badge key={e.name} variant="outline" className="font-mono text-xs">
                  {e.name}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
