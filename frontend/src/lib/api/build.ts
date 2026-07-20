import apiClient from '@/lib/axios'
import type { BuildProject, ContextPreviewResponse } from './types'

export const buildApi = {
  listProjects(pillar?: string) {
    const params = pillar && pillar !== 'all' ? { pillar } : undefined
    return apiClient
      .get<{ projects: BuildProject[] }>('/api/v1/golden-path/projects', { params })
      .then((r) => r.data.projects ?? [])
  },

  getProject(id: string) {
    return apiClient
      .get<BuildProject>(`/api/v1/golden-path/projects/${id}`)
      .then((r) => r.data)
  },

  createProject(body: Record<string, unknown>) {
    return apiClient.post('/api/v1/golden-path/projects', body).then((r) => r.data)
  },

  contextPreview(params: { repository_ids?: string; application_id?: string }) {
    return apiClient
      .get<ContextPreviewResponse>('/api/v1/golden-path/context-preview', { params })
      .then((r) => r.data)
  },
}
