'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import apiClient from '@/lib/axios'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { MermaidDiagram } from '@/components/intelligence/MermaidDiagram'
import { GitBranch, Network } from 'lucide-react'

interface ServiceMapNode {
  repository_id: string
  name: string
  role?: string | null
  status: string
  graph_available?: boolean
}

interface ServiceMapEdge {
  source_repository_id: string
  target_repository_id: string
  source_name: string
  target_name: string
  kind: string
  evidence: string
  confidence?: string
}

interface ServiceMapResult {
  summary: string
  mermaid: string
  nodes: ServiceMapNode[]
  edges: ServiceMapEdge[]
  repository_count: number
  edge_count: number
  available?: boolean
  has_dependencies?: boolean
  cached?: boolean
}

interface ServiceMapPanelProps {
  applicationId: string
  repositoryCount: number
}

export function ServiceMapPanel({ applicationId, repositoryCount }: ServiceMapPanelProps) {
  const [result, setResult] = useState<ServiceMapResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.get(
        `/api/v1/intelligence/applications/${applicationId}/analysis/service-map`
      )
      setResult(res.data)
    } catch (e: unknown) {
      setResult(null)
      setError(e instanceof Error ? e.message : 'Failed to load service map')
    } finally {
      setLoading(false)
    }
  }, [applicationId])

  useEffect(() => {
    void load()
  }, [load])

  if (repositoryCount < 2) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <GitBranch className="h-4 w-4" />
            Cross-repo dependencies
          </CardTitle>
          <CardDescription>
            Link at least two repositories to this application to map how services talk to each
            other.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (loading) {
    return <Skeleton className="h-56 w-full" />
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Cross-repo dependencies</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive">{error}</p>
        </CardContent>
      </Card>
    )
  }

  if (!result) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <GitBranch className="h-4 w-4" />
          Cross-repo dependencies
        </CardTitle>
        <CardDescription>
          How member repositories call each other — coral edges are cross-repo links.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border bg-muted/30 p-4">
          <p className="text-sm leading-relaxed">{result.summary}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="outline">{result.repository_count} repos</Badge>
            <Badge variant="outline">{result.edge_count} links</Badge>
            {result.cached && <Badge variant="outline">cached</Badge>}
          </div>
        </div>

        {result.mermaid ? (
          <MermaidDiagram chart={result.mermaid} />
        ) : (
          <p className="text-sm text-muted-foreground">
            No cross-repo links detected yet. Re-index repositories after adding HTTP clients,
            Feign interfaces, or shared protos.
          </p>
        )}

        {result.edges.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Detected links</p>
            <ul className="divide-y rounded-md border text-sm">
              {result.edges.map((edge, idx) => (
                <li key={`${edge.source_repository_id}-${edge.target_repository_id}-${idx}`} className="px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{edge.source_name}</span>
                    <span className="text-muted-foreground">→</span>
                    <span className="font-medium">{edge.target_name}</span>
                    <Badge variant="secondary" className="text-xs capitalize">
                      {edge.kind.replace(/_/g, ' ')}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{edge.evidence}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" asChild>
                      <Link
                        href={`/dashboard/intelligence/repositories/${edge.source_repository_id}?tab=analysis`}
                      >
                        <Network className="h-3 w-3" />
                        Blast-radius · {edge.source_name}
                      </Link>
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.nodes.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Member services</p>
            <div className="flex flex-wrap gap-2">
              {result.nodes.map((node) => (
                <Button key={node.repository_id} variant="outline" size="sm" asChild>
                  <Link href={`/dashboard/intelligence/repositories/${node.repository_id}?tab=analysis`}>
                    {node.name}
                    {node.role && (
                      <Badge variant="secondary" className="ml-2 capitalize text-[10px]">
                        {node.role}
                      </Badge>
                    )}
                  </Link>
                </Button>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
