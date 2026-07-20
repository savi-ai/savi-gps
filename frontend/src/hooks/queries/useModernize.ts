import { useQuery } from '@tanstack/react-query'
import { modernizeApi } from '@/lib/api/modernize'
import { queryKeys } from '@/lib/queryClient'

export function useModernizePlans(
  params?: Record<string, string>,
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.modernize.plans(params),
    queryFn: () => modernizeApi.listPlans(params),
    enabled,
  })
}
