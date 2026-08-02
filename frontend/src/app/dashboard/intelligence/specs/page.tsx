'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { FileSearch, GitBranch, AlertTriangle } from 'lucide-react'

interface SpecRow {
  path: string
  name: string
  category: string
  repository_id: string
  repository_name: string
  excerpt?: string
}

const AGENT_LABELS: Record<string, string> = {
  kiro: 'Kiro',
  github_copilot: 'GitHub Copilot',
  cursor: 'Cursor',
  claude_code: 'Claude Code',
}

export default function IntelligenceSpecsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const repoFilter = searchParams.get('repo') || ''
  const { hasCapability, hasPermission } = useAuth()
  const [specs, setSpecs] = useState<SpecRow[]>([])
  const [loading, setLoading] = useState(true)
  const [drift, setDrift] = useState<{
    drift_status?: string
    wiki_pending_review?: number
    wiki_stale?: number
    spec_count?: number
    has_specs?: boolean
    has_kiro_specs?: boolean
    spec_layer?: {
      enabled?: boolean
      specs_folder?: string
      coding_agent?: string
    }
  } | null>(null)
  const [specLayer, setSpecLayer] = useState<{
    enabled: boolean
    specs_folder: string
    coding_agent: string
  }>({ enabled: false, specs_folder: '.github', coding_agent: 'github_copilot' })

  const load = useCallback(async () => {
    try {
      setLoading(true)
      const [specsRes, driftRes, configRes] = await Promise.all([
        apiClient.get('/api/v1/intelligence/specs', {
          params: repoFilter ? { repository_id: repoFilter } : undefined,
        }),
        repoFilter
          ? apiClient.get(`/api/v1/intelligence/repos/${repoFilter}/specs/drift`).catch(() => ({ data: null }))
          : Promise.resolve({ data: null }),
        apiClient.get('/api/v1/tenant-config/me').catch(() => ({ data: null })),
      ])
      setSpecs(specsRes.data?.specs || [])
      setDrift(driftRes.data)
      const layer = configRes.data?.spec_layer_settings
      if (layer) {
        setSpecLayer({
          enabled: Boolean(layer.enabled),
          specs_folder: layer.specs_folder || '.github',
          coding_agent: layer.coding_agent || 'github_copilot',
        })
      }
    } finally {
      setLoading(false)
    }
  }, [repoFilter])

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    load()
  }, [hasCapability, router, load])

  if (!hasPermission('can_use_intelligence')) return null

  const byRepo = specs.reduce<Record<string, SpecRow[]>>((acc, s) => {
    const key = s.repository_id
    acc[key] = acc[key] || []
    acc[key].push(s)
    return acc
  }, {})

  const agentLabel = AGENT_LABELS[specLayer.coding_agent] || specLayer.coding_agent
  const folder = drift?.spec_layer?.specs_folder || specLayer.specs_folder
  const enabled = drift?.spec_layer?.enabled ?? specLayer.enabled

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Specs &amp; Drift</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {enabled ? (
            <>
              Specs for <span className="font-medium">{agentLabel}</span> under{' '}
              <code className="text-xs">{folder}/</code> discovered during indexing.
            </>
          ) : (
            <>
              Specs scanning is off. Enable it under{' '}
              <Link href="/dashboard/admin/tenant-settings" className="font-medium hover:underline">
                Tenant settings
              </Link>
              .
            </>
          )}
          {repoFilter && (
            <>
              {' '}
              Filtered to{' '}
              <Link
                href={`/dashboard/intelligence/repositories/${repoFilter}`}
                className="font-medium hover:underline"
              >
                one repository
              </Link>
              .
            </>
          )}
        </p>
      </div>

      {repoFilter && drift && (
        <div className="flex flex-wrap gap-2">
          {(drift.wiki_stale ?? 0) > 0 && (
            <Badge variant="destructive">{drift.wiki_stale} stale wiki pages</Badge>
          )}
          {(drift.wiki_pending_review ?? 0) > 0 && (
            <Badge variant="outline">{drift.wiki_pending_review} pending review</Badge>
          )}
          {drift.drift_status && (
            <Badge variant="secondary" className="capitalize">
              {drift.drift_status.replace(/_/g, ' ')}
            </Badge>
          )}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <FileSearch className="h-4 w-4" />
            Spec files
          </CardTitle>
          <CardDescription>
            {loading ? 'Loading…' : `${specs.length} spec file${specs.length !== 1 ? 's' : ''} across repositories`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : specs.length === 0 ? (
            <div className="py-10 text-center">
              <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                {enabled ? (
                  <>
                    No spec files found under <code>{folder}/</code>. Add specs and re-index.
                  </>
                ) : (
                  <>
                    Specs scanning is disabled. Turn it on in Tenant settings, then re-index.
                  </>
                )}
              </p>
              <div className="mt-4 flex justify-center gap-2">
                <Button size="sm" variant="outline" asChild>
                  <Link href="/dashboard/admin/tenant-settings">Tenant settings</Link>
                </Button>
                <Button size="sm" variant="outline" asChild>
                  <Link href="/dashboard/intelligence/repositories">View repositories</Link>
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {Object.entries(byRepo).map(([repoId, rows]) => (
                <div key={repoId}>
                  <div className="mb-2 flex items-center gap-2">
                    <GitBranch className="h-4 w-4 text-muted-foreground" />
                    <Link
                      href={`/dashboard/intelligence/repositories/${repoId}`}
                      className="text-sm font-medium hover:underline"
                    >
                      {rows[0].repository_name}
                    </Link>
                  </div>
                  <ul className="divide-y rounded-md border">
                    {rows.map((s) => (
                      <li key={s.path} className="px-3 py-3">
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p className="text-sm font-medium">{s.name}</p>
                            <p className="text-xs text-muted-foreground">{s.path}</p>
                          </div>
                          <Badge variant="outline" className="capitalize">
                            {s.category}
                          </Badge>
                        </div>
                        {s.excerpt && (
                          <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{s.excerpt}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
