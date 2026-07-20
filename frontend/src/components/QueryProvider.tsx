'use client'

import { useState } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/lib/queryClient'

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => createQueryClient())
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
