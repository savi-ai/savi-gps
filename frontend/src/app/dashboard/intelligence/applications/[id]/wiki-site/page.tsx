'use client'

import { useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'

/** Legacy dashboard route → dedicated wiki reader. */
export default function ApplicationWikiSiteRedirect() {
  const params = useParams()
  const router = useRouter()
  const appId = params?.id as string

  useEffect(() => {
    if (appId) router.replace(`/wiki/applications/${appId}`)
  }, [appId, router])

  return null
}
