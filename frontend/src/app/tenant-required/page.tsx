'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import './tenant-required.css'

export default function TenantRequiredPage() {
  const router = useRouter()
  const { currentTenant, logout, user, loading } = useAuth()
  
  const storedTenantSlug = typeof window !== 'undefined' ? localStorage.getItem('tenant_slug') : null

  // If tenant becomes available, redirect to dashboard
  useEffect(() => {
    if (!loading && currentTenant) {
      router.push('/dashboard')
    }
  }, [currentTenant, loading, router])

  const handleGoToLogin = () => {
    if (storedTenantSlug) {
      router.push(`/${storedTenantSlug}/login`)
    } else {
      // If no stored tenant, show message
      alert('Please contact your administrator for the correct tenant URL.')
    }
  }

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
        
        <h1 className="tenant-required-title">Tenant Information Required</h1>
        
        <p className="tenant-required-message">
          We couldn't identify your tenant information. To access the application, please use the tenant-specific URL that was provided to you.
        </p>
        
        <div className="tenant-required-details">
          <p className="tenant-required-subtitle">What you need to do:</p>
          <ul className="tenant-required-list">
            <li>Access the application through your tenant-specific URL (e.g., <code>/tenant1/login</code> or <code>/tenant2/login</code>)</li>
            <li>If you don't have the URL, please contact your system administrator</li>
            <li>After logging in through the correct tenant URL, your session will be saved for future access</li>
          </ul>
        </div>

        {storedTenantSlug && (
          <div className="tenant-required-action">
            <button 
              className="tenant-required-button"
              onClick={handleGoToLogin}
            >
              Go to Login ({storedTenantSlug})
            </button>
          </div>
        )}

        <div className="tenant-required-footer">
          <button 
            className="tenant-required-link"
            onClick={() => {
              logout()
              router.push('/')
            }}
          >
            Return to Home
          </button>
        </div>
      </div>
    </div>
  )
}
