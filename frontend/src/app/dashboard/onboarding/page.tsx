'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { BookOpen, GitBranch, Layers, Loader2, Check, Sparkles } from 'lucide-react'

type OnboardingPath = 'alpha' | 'wiki_only' | 'modernization' | 'full'

const OPTIONS: {
  id: OnboardingPath
  title: string
  description: string
  icon: React.ComponentType<{ className?: string }>
  badge?: string
}[] = [
  {
    id: 'alpha',
    title: 'Alpha (recommended)',
    description:
      'Repository & application wikis, chat, search, and modernization assessments. Teams and Build stay off until you enable them for testing.',
    icon: Sparkles,
    badge: 'Alpha',
  },
  {
    id: 'wiki_only',
    title: 'Wiki only',
    description:
      'Connect repositories and generate citation-verified wikis, grounded chat, and code search. No assessments.',
    icon: BookOpen,
  },
  {
    id: 'modernization',
    title: 'Modernization + Build (Beta preview)',
    description:
      'Intelligence and assessments plus Idea → production Projects. Early preview for internal testing.',
    icon: GitBranch,
    badge: 'Beta',
  },
  {
    id: 'full',
    title: 'Full platform (testing)',
    description:
      'Unlock Build, Teams, Portfolio, and Fleet when server flags allow. Use for QA of upcoming releases.',
    icon: Layers,
    badge: 'Test',
  },
]

export default function OnboardingPage() {
  const router = useRouter()
  const { hasPermission, refreshTenantConfig, currentTenant } = useAuth()
  const [selected, setSelected] = useState<OnboardingPath | null>('alpha')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!hasPermission('can_manage_tenant_config')) {
    router.push('/dashboard')
    return null
  }

  const handleContinue = async () => {
    if (!selected) return
    setLoading(true)
    setError(null)
    try {
      await apiClient.post('/api/v1/tenant-config/onboarding', { path: selected })
      await refreshTenantConfig()
      if (selected === 'wiki_only' || selected === 'alpha' || selected === 'modernization') {
        router.push('/dashboard/intelligence/repositories')
      } else {
        router.push('/dashboard')
      }
    } catch (err: unknown) {
      const message =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : 'Failed to save onboarding preference'
      setError(message || 'Failed to save onboarding preference')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 py-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Welcome to Savi GPS</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Choose how {currentTenant?.name || 'your organization'} will use the platform. You can change
          this later in Tenant Settings — including turning on Beta modules for testing.
        </p>
      </div>

      <div className="grid gap-4">
        {OPTIONS.map((option) => {
          const Icon = option.icon
          const isSelected = selected === option.id
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => setSelected(option.id)}
              className="text-left"
            >
              <Card
                className={cn(
                  'transition-colors hover:border-primary/50',
                  isSelected && 'border-primary ring-1 ring-primary'
                )}
              >
                <CardHeader className="flex flex-row items-start gap-4 space-y-0">
                  <div
                    className={cn(
                      'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
                      isSelected ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                    )}
                  >
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <CardTitle className="text-base">{option.title}</CardTitle>
                      {option.badge ? <Badge variant="secondary">{option.badge}</Badge> : null}
                    </div>
                    <CardDescription className="mt-1">{option.description}</CardDescription>
                  </div>
                  {isSelected && <Check className="h-5 w-5 text-primary" />}
                </CardHeader>
              </Card>
            </button>
          )
        })}
      </div>

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      <Button onClick={handleContinue} disabled={!selected || loading} className="min-w-[140px]">
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Saving…
          </>
        ) : (
          'Continue'
        )}
      </Button>
    </div>
  )
}
