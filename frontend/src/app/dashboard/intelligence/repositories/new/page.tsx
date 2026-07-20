'use client'

import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import ConnectRepositoryWizard from '@/components/intelligence/ConnectRepositoryWizard'

export default function ConnectRepositoryPage() {
  const router = useRouter()
  const { hasCapability } = useAuth()

  if (!hasCapability('intelligence')) {
    router.push('/dashboard')
    return null
  }

  return <ConnectRepositoryWizard />
}
