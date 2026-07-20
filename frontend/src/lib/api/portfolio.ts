import apiClient from '@/lib/axios'

export const portfolioApi = {
  getSummary() {
    return apiClient.get('/api/v1/portfolio/summary').then((r) => r.data)
  },

  getHealth() {
    return apiClient.get('/api/v1/portfolio/health').then((r) => r.data)
  },
}
