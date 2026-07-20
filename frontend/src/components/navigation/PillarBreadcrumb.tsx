'use client'

import Link from 'next/link'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface BreadcrumbItem {
  label: string
  href?: string
}

interface PillarBreadcrumbProps {
  items: BreadcrumbItem[]
  className?: string
}

export default function PillarBreadcrumb({ items, className }: PillarBreadcrumbProps) {
  if (items.length === 0) return null

  return (
    <nav aria-label="Breadcrumb" className={cn('flex flex-wrap items-center gap-1 text-sm', className)}>
      {items.map((item, index) => {
        const isLast = index === items.length - 1
        return (
          <span key={`${item.label}-${index}`} className="flex items-center gap-1">
            {index > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
            {item.href && !isLast ? (
              <Link href={item.href} className="text-muted-foreground hover:text-foreground hover:underline">
                {item.label}
              </Link>
            ) : (
              <span className={isLast ? 'font-medium text-foreground' : 'text-muted-foreground'}>
                {item.label}
              </span>
            )}
          </span>
        )
      })}
    </nav>
  )
}
