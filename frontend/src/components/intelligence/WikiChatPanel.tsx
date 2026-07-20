'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Loader2, MessageSquare, Send } from 'lucide-react'
import { WikiMarkdownContent } from '@/components/intelligence/WikiMarkdownContent'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: ChatSource[]
  citations?: string[]
}

export interface ChatSource {
  type: string
  file_path: string
  start_line?: number | null
  end_line?: number | null
  title?: string | null
  excerpt: string
  score?: number
  repository_id?: string | null
  repository_name?: string | null
}

export type ChatScopeRef =
  | { type: 'repo'; id: string; label?: string }
  | { type: 'application'; id: string; label?: string }
  | { type: 'tenant'; label?: string }

interface WikiChatPanelProps {
  scope?: ChatScopeRef
  /** @deprecated Use scope={{ type: 'repo', id, label }} */
  repoId?: string
  /** @deprecated Use scope.label */
  repoName?: string
  pageContext?: string
  compact?: boolean
  className?: string
}

function resolveScope(props: WikiChatPanelProps): ChatScopeRef {
  if (props.scope) return props.scope
  if (props.repoId) {
    return { type: 'repo', id: props.repoId, label: props.repoName }
  }
  throw new Error('WikiChatPanel requires scope or repoId')
}

function scopeLabel(scope: ChatScopeRef): string {
  if (scope.label) return scope.label
  if (scope.type === 'tenant') return 'your estate'
  return scope.type === 'repo' ? 'this repository' : 'this application'
}

export function WikiChatPanel(props: WikiChatPanelProps) {
  const { pageContext, compact = false, className = '' } = props
  const scope = resolveScope(props)
  const displayLabel = scopeLabel(scope)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  const chatUrl =
    scope.type === 'tenant'
      ? '/api/v1/intelligence/tenant/chat'
      : scope.type === 'application'
        ? `/api/v1/intelligence/applications/${scope.id}/chat`
        : `/api/v1/intelligence/repos/${scope.id}/chat`

  const send = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return

    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(nextMessages)
    setInput('')
    setLoading(true)
    setError(null)

    try {
      const res = await apiClient.post(chatUrl, {
        messages: nextMessages.map((m) => ({ role: m.role, content: m.content })),
        top_k: 8,
        page_context: pageContext || undefined,
      })
      setMessages([
        ...nextMessages,
        {
          role: 'assistant',
          content: res.data.answer,
          sources: res.data.sources,
          citations: res.data.citations,
        },
      ])
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to get a response'
      setError(typeof detail === 'string' ? detail : 'Chat failed')
    } finally {
      setLoading(false)
    }
  }, [chatUrl, input, loading, messages, pageContext])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const placeholder =
    scope.type === 'tenant'
      ? 'Ask across all indexed repositories in your tenant…'
      : scope.type === 'application'
        ? 'Ask about cross-repo architecture, APIs, or flows…'
        : 'Ask a question about this wiki…'

  return (
    <Card className={`flex flex-col ${compact ? 'h-full border-0 shadow-none' : ''} ${className}`}>
      <CardHeader className={`pb-3 ${compact ? 'px-0 pt-0' : ''}`}>
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquare className="h-4 w-4" />
          Ask about {displayLabel}
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {scope.type === 'tenant'
            ? 'Federated search across your tenant (up to 25 repositories).'
            : scope.type === 'application'
              ? 'Answers federate indexed content across all repositories in this application.'
              : 'Answers are grounded in indexed code and wiki pages with citations.'}
        </p>
      </CardHeader>
      <CardContent className={`flex flex-1 flex-col gap-3 ${compact ? 'px-0 pb-0' : ''}`}>
        <div
          ref={scrollRef}
          className={`flex-1 space-y-3 overflow-y-auto rounded-md border bg-muted/30 p-3 ${
            compact ? 'min-h-[280px] max-h-[50vh]' : 'min-h-[320px] max-h-[480px]'
          }`}
        >
          {messages.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center gap-2 py-8 text-center text-sm text-muted-foreground">
              <MessageSquare className="h-8 w-8 opacity-40" />
              <p>
                {scope.type === 'tenant'
                  ? 'Ask estate-wide questions — search spans all indexed repositories.'
                  : scope.type === 'application'
                    ? 'Ask how frontend and backend connect, or about shared contracts across repos.'
                    : "Ask anything about this repository's architecture, APIs, or business logic."}
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`rounded-lg px-3 py-2 text-sm ${
                msg.role === 'user'
                  ? 'ml-8 bg-primary text-primary-foreground'
                  : 'mr-4 bg-card border'
              }`}
            >
              {msg.role === 'assistant' ? (
                <WikiMarkdownContent content={msg.content} />
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
              {msg.role === 'assistant' && msg.citations && msg.citations.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1 border-t pt-2">
                  {msg.citations.map((cite) => (
                    <Badge key={cite} variant="outline" className="text-[10px] font-mono">
                      {cite}
                    </Badge>
                  ))}
                </div>
              )}
              {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
                <details className="mt-2 text-xs text-muted-foreground">
                  <summary className="cursor-pointer hover:text-foreground">
                    {msg.sources.length} source{msg.sources.length !== 1 ? 's' : ''} used
                  </summary>
                  <ul className="mt-1 space-y-1 pl-2">
                    {msg.sources.slice(0, 5).map((src, j) => (
                      <li key={j} className="font-mono">
                        {src.repository_name && (
                          <span className="text-foreground">{src.repository_name}: </span>
                        )}
                        {src.type === 'wiki' ? src.title || src.file_path : src.file_path}
                        {src.start_line ? `:${src.start_line}` : ''}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Searching indexed content…
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            rows={compact ? 2 : 3}
            disabled={loading}
            className="resize-none"
          />
          <Button
            type="button"
            size="icon"
            className="shrink-0 self-end"
            onClick={send}
            disabled={loading || !input.trim()}
            aria-label="Send message"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
