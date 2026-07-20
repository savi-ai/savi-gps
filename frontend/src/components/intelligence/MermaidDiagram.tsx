'use client'

import { useEffect, useId, useRef, useState } from 'react'

interface MermaidDiagramProps {
  chart: string
}

export function MermaidDiagram({ chart }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const renderId = useId().replace(/:/g, '')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const render = async () => {
      try {
        const mermaid = (await import('mermaid')).default
        const isDark =
          typeof document !== 'undefined' &&
          document.documentElement.classList.contains('dark')

        mermaid.initialize({
          startOnLoad: false,
          theme: isDark ? 'dark' : 'neutral',
          securityLevel: 'loose',
          fontFamily: 'inherit',
        })

        const { svg } = await mermaid.render(`wiki-mermaid-${renderId}`, chart.trim())
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg
          setError(null)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to render diagram')
        }
      }
    }

    render()
    return () => {
      cancelled = true
    }
  }, [chart, renderId])

  if (error) {
    return (
      <div className="my-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4">
        <p className="mb-2 text-sm text-destructive">Could not render diagram: {error}</p>
        <pre className="overflow-x-auto text-xs text-muted-foreground">{chart}</pre>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="my-4 flex justify-center overflow-x-auto rounded-lg border bg-card p-4 [&_svg]:max-w-full"
      aria-label="Architecture diagram"
    />
  )
}
