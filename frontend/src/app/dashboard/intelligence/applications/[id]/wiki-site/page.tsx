'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft } from 'lucide-react'

export default function ApplicationWikiSitePage() {
  const params = useParams()
  const router = useRouter()
  const { hasCapability } = useAuth()
  const appId = params?.id as string
  const [html, setHtml] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }

    const load = async () => {
      try {
        const meta = await apiClient.get(`/api/v1/intelligence/applications/${appId}/wiki-site`)
        setTitle(meta.data.title || 'Application Wiki')
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
    load()
  }, [appId, hasCapability, router])

  if (loading) return <Skeleton className="h-[80vh] w-full" />

  if (!html) {
    return (
      <div className="space-y-4 py-12 text-center">
        <p className="text-muted-foreground">Application wiki not available yet. Index member repositories first.</p>
        <Button variant="link" onClick={() => router.push(`/dashboard/intelligence/applications/${appId}`)}>
          Back to application
        </Button>
      </div>
    )
  }

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
        <span className="text-xs text-muted-foreground">Synthesized · HTML</span>
      </div>
      <iframe
        title={title}
        srcDoc={html}
        className="min-h-0 flex-1 w-full border-0 bg-white"
        sandbox="allow-same-origin"
      />
    </div>
  )
}
