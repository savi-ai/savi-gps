import { useQuery } from '@tanstack/react-query'
import { intelligenceApi } from '@/lib/api/intelligence'
import { queryKeys } from '@/lib/queryClient'

export function useApplications(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.intelligence.applications,
    queryFn: () => intelligenceApi.listApplications(),
    enabled: options?.enabled ?? true,
  })
}

export function useRepositories(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.intelligence.repositories,
    queryFn: () => intelligenceApi.listRepositories(),
    enabled: options?.enabled ?? true,
  })
}

export function useRepository(repositoryId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.intelligence.repository(repositoryId ?? ''),
    queryFn: () => intelligenceApi.getRepository(repositoryId!),
    enabled: !!repositoryId,
  })
}

export function useRepositoryConnections(repositoryId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.intelligence.connections(repositoryId ?? ''),
    queryFn: () => intelligenceApi.getRepositoryConnections(repositoryId!),
    enabled: !!repositoryId,
  })
}

export function useNextActions(enabled = true) {
  return useQuery({
    queryKey: queryKeys.intelligence.nextActions,
    queryFn: () => intelligenceApi.getNextActions(),
    enabled,
  })
}
