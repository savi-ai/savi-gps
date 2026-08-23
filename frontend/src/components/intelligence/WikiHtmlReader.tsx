'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, MessageSquare, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  WikiChatPanel,
  type ChatScopeRef,
} from '@/components/intelligence/WikiChatPanel'
import { WikiHtmlIframe } from '@/components/intelligence/WikiHtmlIframe'
import { cn } from '@/lib/utils'

export interface WikiHtmlReaderProps {
  title: string
  subtitle?: string
  html: string
  scope: ChatScopeRef
  backHref: string
  backLabel?: string
  badges?: string[]
  headerActions?: React.ReactNode
  initiallyChatOpen?: boolean
}

export function WikiHtmlReader({
  title,
  subtitle,
  html,
  scope,
  backHref,
  backLabel = 'Back',
  badges,
  headerActions,
  initiallyChatOpen = true,
}: WikiHtmlReaderProps) {
  const [chatOpen, setChatOpen] = useState(initiallyChatOpen)

  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="flex shrink-0 items-center gap-3 border-b bg-card px-3 py-2">
        <Button variant="ghost" size="sm" asChild>
          <Link href={backHref}>
            <ArrowLeft className="h-4 w-4" />
            {backLabel}
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{title}</p>
          {subtitle ? (
            <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        {badges && badges.length > 0 ? (
          <div className="hidden items-center gap-1.5 sm:flex">
            {badges.map((b) => (
              <Badge key={b} variant="secondary" className="capitalize">
                {b}
              </Badge>
            ))}
          </div>
        ) : null}
        <div className="flex items-center gap-2">
          {headerActions}
          <Button
            variant={chatOpen ? 'secondary' : 'outline'}
            size="sm"
            onClick={() => setChatOpen((v) => !v)}
          >
            <MessageSquare className="h-4 w-4" />
            Chat
          </Button>
        </div>
      </header>

      <div className="relative min-h-0 flex-1">
        <WikiHtmlIframe
          title={title}
          html={html}
          className={cn(
            'h-full w-full border-0 bg-white transition-[padding]',
            chatOpen && 'lg:pr-[400px]'
          )}
        />

        {/* Desktop / tablet drawer */}
        <aside
          className={cn(
            'absolute inset-y-0 right-0 z-20 hidden w-[400px] flex-col border-l bg-background shadow-xl transition-transform lg:flex',
            chatOpen ? 'translate-x-0' : 'translate-x-full'
          )}
        >
          <div className="flex items-center justify-between border-b px-3 py-2">
            <p className="text-sm font-medium">Ask about this wiki</p>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => setChatOpen(false)}
              aria-label="Close chat"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden p-3">
            <WikiChatPanel scope={scope} compact fill className="h-full" />
          </div>
        </aside>

        {/* Mobile: floating panel */}
        {chatOpen && (
          <div className="absolute inset-x-3 bottom-3 top-16 z-30 flex flex-col overflow-hidden rounded-xl border bg-background shadow-2xl lg:hidden">
            <div className="flex items-center justify-between border-b px-3 py-2">
              <p className="text-sm font-medium">Ask about this wiki</p>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => setChatOpen(false)}
                aria-label="Close chat"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden p-3">
              <WikiChatPanel scope={scope} compact fill className="h-full" />
            </div>
          </div>
        )}

        {!chatOpen && (
          <Button
            size="lg"
            className="absolute bottom-5 right-5 z-20 h-12 rounded-full px-5 shadow-lg"
            onClick={() => setChatOpen(true)}
          >
            <MessageSquare className="h-5 w-5" />
            Chat
          </Button>
        )}
      </div>
    </div>
  )
}
