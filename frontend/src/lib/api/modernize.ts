import apiClient from '@/lib/axios'
import type { ModernizationPlanSummary } from './types'

export const modernizeApi = {
  listPlans(params?: Record<string, string>) {
    return apiClient
      .get<{ plans: ModernizationPlanSummary[] }>('/api/v1/modernize/plans', { params })
      .then((r) => r.data.plans ?? [])
  },
}
