'use client'

import { useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'

/** Legacy dashboard route → dedicated wiki reader. */
export default function RepositoryWikiSiteRedirect() {
  const params = useParams()
  const router = useRouter()
  const repoId = params?.id as string

  useEffect(() => {
    if (repoId) router.replace(`/wiki/repositories/${repoId}`)
  }, [repoId, router])

  return null
}
