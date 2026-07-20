import { useQuery } from '@tanstack/react-query'
import { buildApi } from '@/lib/api/build'
import { queryKeys } from '@/lib/queryClient'

export function useProjects(pillar?: string) {
  return useQuery({
    queryKey: queryKeys.projects.list(pillar),
    queryFn: () => buildApi.listProjects(pillar),
  })
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.projects.detail(projectId ?? ''),
    queryFn: () => buildApi.getProject(projectId!),
    enabled: !!projectId,
  })
}

export function useContextPreview(
  repositoryIds: string[],
  applicationId?: string,
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.projects.contextPreview(repositoryIds, applicationId),
    queryFn: () =>
      buildApi.contextPreview({
        repository_ids: repositoryIds.length > 0 ? repositoryIds.join(',') : undefined,
        application_id: applicationId || undefined,
      }),
    enabled: enabled && (repositoryIds.length > 0 || !!applicationId),
  })
}
