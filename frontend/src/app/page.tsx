'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'

/** Alpha entry: authenticated → dashboard; otherwise → /login (no tenant path). */
export default function Home() {
  const router = useRouter()
  const { token, loading, isAuthenticated } = useAuth()

  useEffect(() => {
    if (loading) return
    if (isAuthenticated || token) {
      router.replace('/dashboard')
    } else {
      router.replace('/login')
    }
  }, [loading, isAuthenticated, token, router])

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div className="loading-spinner" />
    </div>
  )
}
