'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import './tenant-required.css'

export default function TenantRequiredPage() {
  const router = useRouter()
  const { currentTenant, logout, loading } = useAuth()

  // If tenant becomes available, redirect to dashboard
  useEffect(() => {
    if (!loading && currentTenant) {
      router.push('/dashboard')
    }
  }, [currentTenant, loading, router])

  // Show loading while checking tenant
  if (loading) {
    return (
      <div className="tenant-required-container">
        <div className="tenant-required-content">
          <div>Loading...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="tenant-required-container">
      <div className="tenant-required-content">
        <div className="tenant-required-icon">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2"/>
            <path d="M12 8V12M12 16H12.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        </div>

        <h1 className="tenant-required-title">Session needs a refresh</h1>

        <p className="tenant-required-message">
          We couldn&apos;t load your tenant context. For Alpha, sign in at{' '}
          <code>/login</code> — no tenant path is required.
        </p>

        <div className="tenant-required-details">
          <p className="tenant-required-subtitle">What you need to do:</p>
          <ul className="tenant-required-list">
            <li>
              Open <code>/login</code> and sign in again (seeded admin if you ran the seed script)
            </li>
            <li>
              Optional: tenant-scoped URLs like <code>/default/login</code> still work for later
              multi-tenant setups
            </li>
            <li>If this keeps happening, clear site data for localhost and try again</li>
          </ul>
        </div>

        <div className="tenant-required-action">
          <button
            className="tenant-required-button"
            onClick={() => {
              logout()
              router.push('/login')
            }}
          >
            Go to Login
          </button>
        </div>

        <div className="tenant-required-footer">
          <button
            className="tenant-required-link"
            onClick={() => {
              logout()
              router.push('/login')
            }}
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  )
}
