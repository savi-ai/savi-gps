'use client'

import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'

export interface WikiHtmlIframeProps {
  title: string
  html: string
  className?: string
  sandbox?: string
}

/**
 * Renders wiki HTML in an iframe without nesting the app shell.
 *
 * `srcDoc` + `allow-same-origin` makes hash links like `#overview` resolve against
 * the parent page URL, so the iframe navigates to the full Next.js wiki route
 * (recursive chrome). Blob URLs keep in-document anchors local; we also intercept
 * clicks as a fallback.
 */
export function WikiHtmlIframe({
  title,
  html,
  className,
  sandbox = 'allow-scripts allow-same-origin',
}: WikiHtmlIframeProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const blobUrlRef = useRef<string | null>(null)

  useEffect(() => {
    const iframe = iframeRef.current
    if (!iframe) return

    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current)
      blobUrlRef.current = null
    }

    const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    blobUrlRef.current = url
    iframe.src = url

    const onLoad = () => {
      const doc = iframe.contentDocument
      if (!doc) return

      const onClick = (event: MouseEvent) => {
        const target = event.target as Element | null
        const anchor = target?.closest?.('a') as HTMLAnchorElement | null
        if (!anchor) return

        const rawHref = anchor.getAttribute('href')
        if (!rawHref) return

        // In-document TOC / section anchors
        if (rawHref.startsWith('#')) {
          event.preventDefault()
          const id = decodeURIComponent(rawHref.slice(1))
          if (!id) return
          const el =
            doc.getElementById(id) ||
            doc.querySelector(`[name="${CSS.escape(id)}"]`)
          el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          return
        }

        let resolved: URL
        try {
          resolved = new URL(rawHref, iframe.contentWindow?.location.href || window.location.href)
        } catch {
          return
        }

        // Same-origin app routes must not load inside the iframe (nesting bug).
        if (resolved.origin === window.location.origin) {
          event.preventDefault()
          if (resolved.hash && resolved.pathname === new URL(url).pathname) {
            const id = decodeURIComponent(resolved.hash.slice(1))
            const el =
              (id && doc.getElementById(id)) ||
              (id && doc.querySelector(`[name="${CSS.escape(id)}"]`))
            el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
            return
          }
          window.open(resolved.href, '_blank', 'noopener,noreferrer')
        }
      }

      doc.addEventListener('click', onClick)
    }

    iframe.addEventListener('load', onLoad)

    return () => {
      iframe.removeEventListener('load', onLoad)
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
      }
    }
  }, [html])

  return (
    <iframe
      ref={iframeRef}
      title={title}
      sandbox={sandbox}
      className={cn(className)}
    />
  )
}
