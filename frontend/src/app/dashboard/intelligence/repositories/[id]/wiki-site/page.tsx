'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ArrowLeft, ExternalLink, MessageSquare } from 'lucide-react'
import { WikiChatPanel } from '@/components/intelligence/WikiChatPanel'

export default function WikiSiteViewerPage() {
  const params = useParams()
  const router = useRouter()
  const { hasCapability } = useAuth()
  const repoId = params?.id as string
  const [html, setHtml] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [repoName, setRepoName] = useState('')
  const [loading, setLoading] = useState(true)
  const [chatOpen, setChatOpen] = useState(true)

  useEffect(() => {
    if (!hasCapability('intelligence')) {
      router.push('/dashboard')
      return
    }

    const load = async () => {
      try {
        const [meta, repoRes] = await Promise.all([
          apiClient.get(`/api/v1/intelligence/repos/${repoId}/wiki-site`),
          apiClient.get(`/api/v1/intelligence/repos/${repoId}`),
        ])
        setTitle(meta.data.title || 'Repository Wiki')
        setRepoName(repoRes.data.name || '')
        const htmlRes = await apiClient.get(
          `/api/v1/intelligence/repos/${repoId}/wiki-site/html`,
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
  }, [repoId, hasCapability, router])

  if (loading) return <Skeleton className="h-[80vh] w-full" />

  if (!html) {
    return (
      <div className="space-y-4 py-12 text-center">
        <p className="text-muted-foreground">Wiki HTML not generated yet. Run indexing on this repository.</p>
        <Button variant="link" onClick={() => router.push(`/dashboard/intelligence/repositories/${repoId}`)}>
          Back to repository
        </Button>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <div className="flex items-center justify-between border-b bg-card px-4 py-2">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push(`/dashboard/intelligence/repositories/${repoId}`)}
          >
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
          <span className="text-sm font-medium">{title}</span>
          <span className="text-xs text-muted-foreground">Wiki Agent · HTML</span>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={chatOpen ? 'secondary' : 'outline'}
            size="sm"
            onClick={() => setChatOpen((v) => !v)}
          >
            <MessageSquare className="h-4 w-4" />
            Chat
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const blob = new Blob([html], { type: 'text/html' })
              window.open(URL.createObjectURL(blob), '_blank')
            }}
          >
            <ExternalLink className="h-4 w-4" />
            Open in tab
          </Button>
        </div>
      </div>
      <div className="flex flex-1 min-h-0">
        <iframe
          title={title}
          srcDoc={html}
          className={`border-0 bg-white ${chatOpen ? 'w-[65%]' : 'w-full'}`}
          sandbox="allow-scripts allow-same-origin"
        />
        {chatOpen && (
          <div className="w-[35%] min-w-[320px] border-l bg-background p-4 overflow-y-auto">
            <WikiChatPanel repoId={repoId} repoName={repoName} compact />
          </div>
        )}
      </div>
    </div>
  )
}
