'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, Loader2, RefreshCw } from 'lucide-react'
import { ApplicationWikiGenerateDialog } from '@/components/intelligence/ApplicationWikiGenerateDialog'

export default function ApplicationWikiSitePage() {
  const params = useParams()
  const router = useRouter()
  const { hasCapability } = useAuth()
  const appId = params?.id as string
  const [html, setHtml] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [source, setSource] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [generateOpen, setGenerateOpen] = useState(false)
  const [banner, setBanner] = useState<string | null>(null)

  const load = async () => {
    try {
      const [meta, statusRes] = await Promise.all([
        apiClient.get(`/api/v1/intelligence/applications/${appId}/wiki-site`),
        apiClient.get(`/api/v1/intelligence/applications/${appId}/wiki/status`).catch(() => null),
      ])
      setTitle(meta.data.title || 'Application Wiki')
      setSource(meta.data.source || null)
      setStatus(statusRes?.data?.status || meta.data.status?.status || null)
      const htmlRes = await apiClient.get(
        `/api/v1/intelligence/applications/${appId}/wiki-site/html`,
        { responseType: 'text' }
      )
      setHtml(typeof htmlRes.data === 'string' ? htmlRes.data : String(htmlRes.data))
    } catch {
      setHtml(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }
    load()
  }, [appId, hasCapability, router])

  const pollUntilDone = async () => {
    setStatus('running')
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      const statusRes = await apiClient.get(
        `/api/v1/intelligence/applications/${appId}/wiki/status`
      )
      const st = statusRes.data?.status
      setStatus(st || null)
      if (st === 'completed' || st === 'failed') {
        await load()
        break
      }
    }
  }

  const onGenerateCompleted = async (result: {
    deferred?: boolean
    message?: string
  }) => {
    setBanner(result.message || null)
    if (result.deferred) {
      setStatus(null)
      return
    }
    setGenerating(true)
    try {
      await pollUntilDone()
    } catch {
      setStatus('failed')
    } finally {
      setGenerating(false)
    }
  }

  if (loading) return <Skeleton className="h-[80vh] w-full" />

  if (!html) {
    return (
      <div className="space-y-4 py-12 text-center">
        <p className="text-muted-foreground">
          Application wiki not available yet. Generate a multi-repo wiki or index member repositories.
        </p>
        {banner && <p className="mx-auto max-w-md text-sm text-foreground">{banner}</p>}
        <div className="flex justify-center gap-2">
          <Button
            onClick={() => {
              setBanner(null)
              setGenerateOpen(true)
            }}
            disabled={generating}
          >
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Generate application wiki
          </Button>
          <Button variant="link" onClick={() => router.push(`/dashboard/intelligence/applications/${appId}`)}>
            Back to application
          </Button>
        </div>
        <ApplicationWikiGenerateDialog
          open={generateOpen}
          applicationId={appId}
          onOpenChange={setGenerateOpen}
          onCompleted={(result) => void onGenerateCompleted(result)}
        />
      </div>
    )
  }

  const label =
    source === 'generated' ? 'Generated · HTML' : source === 'synthesized' ? 'Synthesized · HTML' : 'HTML'

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <div className="flex items-center gap-2 border-b bg-card px-4 py-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push(`/dashboard/intelligence/applications/${appId}?tab=wiki`)}
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">{label}</span>
        {status && <span className="text-xs text-muted-foreground">· {status}</span>}
        <div className="ml-auto">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setBanner(null)
              setGenerateOpen(true)
            }}
            disabled={generating || status === 'running'}
          >
            {generating || status === 'running' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Regenerate
          </Button>
        </div>
      </div>
      {banner && (
        <p className="border-b bg-primary/5 px-4 py-2 text-xs text-foreground">{banner}</p>
      )}
      <iframe title={title} srcDoc={html} className="min-h-0 flex-1 w-full border-0 bg-white" />
      <ApplicationWikiGenerateDialog
        open={generateOpen}
        applicationId={appId}
        onOpenChange={setGenerateOpen}
        onCompleted={(result) => void onGenerateCompleted(result)}
      />
    </div>
  )
}
