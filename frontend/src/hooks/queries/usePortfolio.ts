import { useQuery } from '@tanstack/react-query'
import { portfolioApi } from '@/lib/api/portfolio'
import { queryKeys } from '@/lib/queryClient'

export function usePortfolioSummary(enabled = true) {
  return useQuery({
    queryKey: queryKeys.portfolio.summary,
    queryFn: () => portfolioApi.getSummary(),
    enabled,
  })
}

export function usePortfolioHealth(enabled = true) {
  return useQuery({
    queryKey: queryKeys.portfolio.health,
    queryFn: () => portfolioApi.getHealth(),
    enabled,
  })
}
