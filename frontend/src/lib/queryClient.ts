import { QueryClient } from '@tanstack/react-query'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  })
}

export const queryKeys = {
  projects: {
    all: ['projects'] as const,
    list: (pillar?: string) => ['projects', 'list', pillar ?? 'all'] as const,
    detail: (id: string) => ['projects', 'detail', id] as const,
    contextPreview: (repoIds: string[], applicationId?: string) =>
      ['projects', 'context-preview', repoIds.join(','), applicationId ?? ''] as const,
  },
  intelligence: {
    applications: ['intelligence', 'applications'] as const,
    application: (id: string) => ['intelligence', 'applications', id] as const,
    repositories: ['intelligence', 'repositories'] as const,
    repository: (id: string) => ['intelligence', 'repository', id] as const,
    connections: (id: string) => ['intelligence', 'connections', id] as const,
    nextActions: ['intelligence', 'next-actions'] as const,
  },
  modernize: {
    plans: (filters?: Record<string, string>) => ['modernize', 'plans', filters ?? {}] as const,
  },
  portfolio: {
    health: ['portfolio', 'health'] as const,
    summary: ['portfolio', 'summary'] as const,
  },
}
