'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { WikiHtmlReader } from '@/components/intelligence/WikiHtmlReader'

export default function RepositoryWikiReaderPage() {
  const params = useParams()
  const router = useRouter()
  const { hasCapability } = useAuth()
  const repoId = params?.id as string
  const [html, setHtml] = useState<string | null>(null)
  const [title, setTitle] = useState('Repository Wiki')
  const [repoName, setRepoName] = useState('')
  const [loading, setLoading] = useState(true)

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
        setRepoName(
          repoRes.data.github_full_name || repoRes.data.name || meta.data.title || 'Repository'
        )
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
    void load()
  }, [repoId, hasCapability, router])

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
          Wiki HTML is not generated yet. Run indexing on this repository.
        </p>
        <Button
          variant="outline"
          onClick={() => router.push(`/dashboard/intelligence/repositories/${repoId}`)}
        >
          Back to repository
        </Button>
      </div>
    )
  }

  return (
    <WikiHtmlReader
      title={title}
      subtitle="Repository wiki · chat grounded in indexed code and pages"
      html={html}
      scope={{ type: 'repo', id: repoId, label: repoName }}
      backHref={`/dashboard/intelligence/repositories/${repoId}`}
      backLabel="Repository"
      badges={['Generated', 'HTML']}
    />
  )
}
