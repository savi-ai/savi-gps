'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import { MermaidDiagram } from './MermaidDiagram'

interface WikiMarkdownContentProps {
  content: string
}

const components: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')
    const code = String(children).replace(/\n$/, '')

    if (match?.[1] === 'mermaid') {
      return <MermaidDiagram chart={code} />
    }

    if (match) {
      return (
        <pre className="overflow-x-auto rounded-md border bg-muted/50 p-4 text-sm">
          <code className={className} {...props}>
            {children}
          </code>
        </pre>
      )
    }

    return (
      <code
        className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]"
        {...props}
      >
        {children}
      </code>
    )
  },
  table({ children }) {
    return (
      <div className="my-4 overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">{children}</table>
      </div>
    )
  },
  th({ children }) {
    return (
      <th className="border-b bg-muted/50 px-4 py-2 text-left font-semibold">{children}</th>
    )
  },
  td({ children }) {
    return <td className="border-b px-4 py-2">{children}</td>
  },
}

export function WikiMarkdownContent({ content }: WikiMarkdownContentProps) {
  return (
    <article className="prose prose-sm max-w-none dark:prose-invert prose-headings:scroll-mt-20 prose-pre:p-0 prose-pre:bg-transparent">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </article>
  )
}
