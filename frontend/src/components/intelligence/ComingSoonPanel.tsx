'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

interface ComingSoonPanelProps {
  title: string
  description: string
  phase?: string
}

export function ComingSoonPanel({ title, description, phase = '1' }: ComingSoonPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">
          This surface is scaffolded in Phase 0. Full functionality ships in Phase {phase}.
        </p>
      </CardContent>
    </Card>
  )
}
