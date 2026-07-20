import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Construction } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ComingSoonPanelProps {
  title: string
  description: string
  pillar?: 'intelligence' | 'build' | 'modernize' | 'portfolio'
}

const PILLAR_ACCENT: Record<NonNullable<ComingSoonPanelProps['pillar']>, string> = {
  intelligence: 'pillar-accent-intelligence',
  build: 'pillar-accent-build',
  modernize: 'pillar-accent-modernize',
  portfolio: 'pillar-accent-portfolio',
}

export function ComingSoonPanel({ title, description, pillar }: ComingSoonPanelProps) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      <Card className={cn('border-l-4 shadow-sm', pillar && PILLAR_ACCENT[pillar])}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Construction className="h-4 w-4 text-muted-foreground" />
            Coming soon
          </CardTitle>
          <CardDescription>
            This surface is not included in the Alpha release. See the release notes for what
            ships today (Health, Assessments, Plans, Intelligence, Wiki Review).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Check back after the operational maturity wave, or ask your admin to prioritize this
            capability.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
