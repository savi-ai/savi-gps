'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { BookOpen, GitBranch, Layers, Loader2, Check } from 'lucide-react'

type OnboardingPath = 'wiki_only' | 'modernization' | 'full'

const OPTIONS: {
  id: OnboardingPath
  title: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}[] = [
  {
    id: 'wiki_only',
    title: 'Document existing systems',
    description:
      'Connect repositories and generate citation-verified wikis, grounded chat, and code search. No Build pipeline.',
    icon: BookOpen,
  },
  {
    id: 'modernization',
    title: 'Legacy modernization',
    description:
      'Understand legacy code with Intelligence, then plan and rebuild using the Build agent pipeline with wiki context.',
    icon: GitBranch,
  },
  {
    id: 'full',
    title: 'Full platform',
    description:
      'Build new software from ideas and maintain existing repos with Intelligence. Fleet remediation when enabled.',
    icon: Layers,
  },
]

export default function OnboardingPage() {
  const router = useRouter()
  const { hasPermission, refreshTenantConfig, currentTenant } = useAuth()
  const [selected, setSelected] = useState<OnboardingPath | null>(null)
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
      if (selected === 'wiki_only') {
        router.push('/dashboard/intelligence/repositories')
      } else if (selected === 'modernization') {
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
          this later in tenant settings.
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
                    <CardTitle className="text-base">{option.title}</CardTitle>
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
