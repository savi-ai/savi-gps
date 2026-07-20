'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Skeleton } from '@/components/ui/skeleton'

interface LegacyRedirectProps {
  href: string
}

/** Temporary redirect for deprecated routes (one release window). */
export function LegacyRedirect({ href }: LegacyRedirectProps) {
  const router = useRouter()

  useEffect(() => {
    router.replace(href)
  }, [router, href])

  return <Skeleton className="h-8 w-48" />
}
