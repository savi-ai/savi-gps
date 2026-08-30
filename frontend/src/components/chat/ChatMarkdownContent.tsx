'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import { normalizeChatMarkdown } from './normalizeChatMarkdown'

interface ChatMarkdownContentProps {
  content: string
}

const components: Components = {
  p({ children }) {
    return <p className="chat-md-p">{children}</p>
  },
  ul({ children }) {
    return <ul className="chat-md-list">{children}</ul>
  },
  ol({ children }) {
    return <ol className="chat-md-list">{children}</ol>
  },
  li({ children }) {
    return <li className="chat-md-li">{children}</li>
  },
  strong({ children }) {
    return <strong className="chat-md-strong">{children}</strong>
  },
  code({ children }) {
    return <code className="chat-md-code">{children}</code>
  },
}

export function ChatMarkdownContent({ content }: ChatMarkdownContentProps) {
  const normalized = normalizeChatMarkdown(content)

  return (
    <div className="chat-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {normalized}
      </ReactMarkdown>
    </div>
  )
}
