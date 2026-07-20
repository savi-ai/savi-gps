'use client'

import { useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import DashboardLayout from '@/components/DashboardLayout'
import ProtectedRoute from '@/components/ProtectedRoute'
import { useAuth } from '@/contexts/AuthContext'
import './dashboard.css'

export default function DashboardLayoutWrapper({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const { currentTenant, loading, isAuthenticated, hasPermission, refreshTenantConfig } = useAuth()

  useEffect(() => {
    if (!loading && isAuthenticated) {
      refreshTenantConfig()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, isAuthenticated])

  useEffect(() => {
    if (
      !loading &&
      isAuthenticated &&
      currentTenant &&
      hasPermission('can_manage_tenant_config') &&
      !currentTenant.onboarding_path &&
      pathname !== '/dashboard/onboarding' &&
      pathname !== '/dashboard/admin/tenant-settings'
    ) {
      router.push('/dashboard/onboarding')
    }
  }, [loading, isAuthenticated, currentTenant, pathname, hasPermission, router])

  useEffect(() => {
    // Check if tenant is available after auth is loaded
    if (!loading && isAuthenticated && !currentTenant) {
      // Check if tenant info is in localStorage
      const storedTenant = localStorage.getItem('current_tenant')
      if (storedTenant) {
        // Tenant exists in localStorage, but not in state - AuthContext should load it
        // Wait a bit for AuthContext to sync
        const checkTenant = setTimeout(() => {
          if (!currentTenant) {
            // Still no tenant in state, but it's in localStorage - try to trigger a re-render
            // by checking again
            const tenant = localStorage.getItem('current_tenant')
            if (!tenant) {
              router.push('/tenant-required')
            }
          }
        }, 500)
        return () => clearTimeout(checkTenant)
      }
      
      // Try to get tenant from user data or URL
      const storedUser = localStorage.getItem('auth_user')
      const tenantSlug = localStorage.getItem('tenant_slug')
      
      if (storedUser && (tenantSlug || JSON.parse(storedUser).tenant_id)) {
        // Wait for tenant to be fetched from AuthContext (it should be fetching now)
        const checkTenant = setTimeout(() => {
          const tenant = localStorage.getItem('current_tenant')
          if (!tenant) {
            console.warn('Tenant not found after waiting. Redirecting to tenant-required page.')
            router.push('/tenant-required')
          }
        }, 3000) // Give more time for async tenant fetch
            
        return () => clearTimeout(checkTenant)
      }
      
      // No tenant info available, redirect to tenant-required page
      console.warn('No tenant information available. Redirecting to tenant-required page.')
      router.push('/tenant-required')
    }
  }, [loading, isAuthenticated, currentTenant, router])

  // Show loading while checking tenant
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-sm text-muted-foreground">Loading...</div>
      </div>
    )
  }

  // If authenticated but no tenant, the useEffect will redirect
  if (isAuthenticated && !currentTenant) {
    return null
  }

  return (
    <ProtectedRoute>
      <DashboardLayout>
        {children}
      </DashboardLayout>
    </ProtectedRoute>
  )
}
