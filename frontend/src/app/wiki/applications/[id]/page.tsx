'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Loader2, RefreshCw } from 'lucide-react'
import { WikiHtmlReader } from '@/components/intelligence/WikiHtmlReader'
import { ApplicationWikiGenerateDialog } from '@/components/intelligence/ApplicationWikiGenerateDialog'

export default function ApplicationWikiReaderPage() {
  const params = useParams()
  const router = useRouter()
  const { hasCapability } = useAuth()
  const appId = params?.id as string
  const [html, setHtml] = useState<string | null>(null)
  const [title, setTitle] = useState('Application Wiki')
  const [appName, setAppName] = useState('')
  const [source, setSource] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [generateOpen, setGenerateOpen] = useState(false)
  const [generating, setGenerating] = useState(false)

  const load = async () => {
    try {
      const [meta, statusRes, appRes] = await Promise.all([
        apiClient.get(`/api/v1/intelligence/applications/${appId}/wiki-site`),
        apiClient.get(`/api/v1/intelligence/applications/${appId}/wiki/status`).catch(() => null),
        apiClient.get(`/api/v1/intelligence/applications/${appId}`).catch(() => null),
      ])
      setTitle(meta.data.title || 'Application Wiki')
      setSource(meta.data.source || null)
      setStatus(statusRes?.data?.status || meta.data.status?.status || null)
      setAppName(appRes?.data?.name || meta.data.title || 'Application')
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
    void load()
  }, [appId, hasCapability, router])

  useEffect(() => {
    if (status !== 'running') return
    const t = setInterval(async () => {
      try {
        const statusRes = await apiClient.get(
          `/api/v1/intelligence/applications/${appId}/wiki/status`
        )
        const st = statusRes.data?.status
        setStatus(st || null)
        if (st === 'completed' || st === 'failed') await load()
      } catch {
        /* ignore */
      }
    }, 4000)
    return () => clearInterval(t)
  }, [status, appId])

  const onGenerateCompleted = async (result: { deferred?: boolean }) => {
    if (result.deferred) return
    setGenerating(true)
    setStatus('running')
    try {
      for (let i = 0; i < 90; i++) {
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
    } finally {
      setGenerating(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center p-8">
        <Skeleton className="h-full w-full max-w-5xl" />
      </div>
    )
  }

  if (!html) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="text-muted-foreground">
          Application wiki HTML is not available yet. Generate it from the application page.
        </p>
        <div className="flex gap-2">
          <Button onClick={() => setGenerateOpen(true)} disabled={generating || status === 'running'}>
            {generating || status === 'running' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Generate application wiki
          </Button>
          <Button
            variant="outline"
            onClick={() =>
              router.push(`/dashboard/intelligence/applications/${appId}?tab=wiki`)
            }
          >
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

  const badges = [
    source === 'generated' ? 'Generated' : source === 'synthesized' ? 'Synthesized' : 'HTML',
    status || undefined,
  ].filter(Boolean) as string[]

  return (
    <>
      <WikiHtmlReader
        title={title}
        subtitle="Application wiki · chat grounded across member repos"
        html={html}
        scope={{ type: 'application', id: appId, label: appName }}
        backHref={`/dashboard/intelligence/applications/${appId}?tab=wiki`}
        backLabel="Application"
        badges={badges}
        headerActions={
          <Button
            size="sm"
            variant="outline"
            disabled={generating || status === 'running'}
            onClick={() => setGenerateOpen(true)}
          >
            {generating || status === 'running' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Regenerate
          </Button>
        }
      />
      <ApplicationWikiGenerateDialog
        open={generateOpen}
        applicationId={appId}
        onOpenChange={setGenerateOpen}
        onCompleted={(result) => void onGenerateCompleted(result)}
      />
    </>
  )
}
