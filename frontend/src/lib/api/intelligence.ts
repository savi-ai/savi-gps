import apiClient from '@/lib/axios'
import type { ApplicationSummary, RepositoryConnectionsResponse, RepositorySummary } from './types'

export const intelligenceApi = {
  listApplications() {
    return apiClient
      .get<{ applications: ApplicationSummary[] }>('/api/v1/intelligence/applications')
      .then((r) => r.data.applications ?? [])
  },

  listRepositories() {
    return apiClient
      .get<{ repositories: RepositorySummary[] }>('/api/v1/intelligence/repos')
      .then((r) => r.data.repositories ?? [])
  },

  getRepository(id: string) {
    return apiClient
      .get<RepositorySummary>(`/api/v1/intelligence/repos/${id}`)
      .then((r) => r.data)
  },

  getRepositoryConnections(id: string) {
    return apiClient
      .get<RepositoryConnectionsResponse>(`/api/v1/intelligence/repos/${id}/connections`)
      .then((r) => r.data)
  },

  getNextActions() {
    return apiClient
      .get<{ next_actions: Array<{
        id: string
        priority: string
        title: string
        description: string
        href: string
        pillar: string
      }> }>('/api/v1/intelligence/next-actions')
      .then((r) => r.data.next_actions ?? [])
  },
}
