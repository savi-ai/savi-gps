'use client'

import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import axios from 'axios'
import { AUTH_LOGOUT_EVENT } from '@/lib/axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface User {
  id: string
  username: string
  email: string
  full_name: string | null
  is_active: boolean
  roles: string[]
  tenant_id?: string
  permissions?: string[]
}

export interface TenantCapabilities {
  build: boolean
  intelligence: boolean
  fleet: boolean
  modernize: boolean
  portfolio: boolean
}

export interface SpecLayerSettings {
  enabled: boolean
  specs_folder: string
  coding_agent: string
}

interface Tenant {
  id: string
  name: string
  description?: string
  capabilities?: TenantCapabilities
  onboarding_path?: string | null
  spec_layer_settings?: SpecLayerSettings
}

interface AuthContextType {
  user: User | null
  token: string | null
  currentTenant: Tenant | null
  tenants: Tenant[]
  login: (username: string, password: string, tenantId?: string) => Promise<void>
  register: (username: string, email: string, password: string, fullName: string, role: string, tenantId?: string) => Promise<void>
  logout: () => void
  setTenant: (tenantId: string) => Promise<void>
  fetchTenants: () => Promise<void>
  loading: boolean
  isAuthenticated: boolean
  hasRole: (role: string) => boolean
  hasPermission: (permission: string) => boolean
  hasCapability: (capability: keyof TenantCapabilities) => boolean
  refreshTenantConfig: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

const DEFAULT_CAPABILITIES: TenantCapabilities = {
  build: true,
  intelligence: false,
  fleet: false,
  modernize: false,
  portfolio: false,
}

function mergeTenantCapabilities(
  caps?: Partial<TenantCapabilities> | null
): TenantCapabilities {
  return { ...DEFAULT_CAPABILITIES, ...(caps ?? {}) }
}

// Helper function to extract tenant from URL path
export function getTenantFromPath(pathname: string): string | null {
  // Support both /t/[tenant] and /[tenant] patterns
  const match = pathname.match(/^\/(?:t\/)?([^\/]+)/)
  if (match && match[1] && match[1] !== 'login' && match[1] !== 'dashboard' && match[1] !== 'api') {
    return match[1]
  }
  return null
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [currentTenant, setCurrentTenant] = useState<Tenant | null>(null)
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)

  const fetchTenants = async () => {
    try {
      const response = await axios.get(`${API_URL}/api/v1/auth/tenants`)
      setTenants(response.data)
    } catch (error) {
      console.error('Error fetching tenants:', error)
      // Set empty array on error
      setTenants([])
    }
  }
  
  const fetchTenantById = async (tenantId: string) => {
    try {
      // Try to fetch tenant by ID endpoint first
      try {
        const response = await axios.get(`${API_URL}/api/v1/auth/tenants/${tenantId}`)
        if (response.data) {
          setCurrentTenant(response.data)
          localStorage.setItem('current_tenant', JSON.stringify(response.data))
          return response.data
        }
      } catch (e) {
        // If endpoint doesn't exist, fallback to fetching all tenants
        const response = await axios.get(`${API_URL}/api/v1/auth/tenants`)
        const tenants = Array.isArray(response.data) ? response.data : []
        const tenant = tenants.find((t: Tenant) => t.id === tenantId)
        if (tenant) {
          setCurrentTenant(tenant)
          localStorage.setItem('current_tenant', JSON.stringify(tenant))
          return tenant
        }
      }
    } catch (error) {
      console.error('Error fetching tenant:', error)
    }
    return null
  }
  
  const fetchTenantBySlug = async (tenantSlug: string) => {
    try {
      const response = await axios.get(`${API_URL}/api/v1/auth/tenants`)
      const tenants = Array.isArray(response.data) ? response.data : []
      const tenant = tenants.find((t: Tenant) => t.name === tenantSlug)
      if (tenant) {
        setCurrentTenant(tenant)
        localStorage.setItem('current_tenant', JSON.stringify(tenant))
        console.log('Tenant fetched by slug:', tenant)
        return tenant
      } else {
        console.warn(`Tenant with slug "${tenantSlug}" not found. Available tenants:`, tenants.map(t => t.name))
      }
    } catch (error) {
      console.error('Error fetching tenant by slug:', error)
    }
    return null
  }

  useEffect(() => {
    const onAuthLogout = () => {
      logout()
      const tenantSlug = localStorage.getItem('tenant_slug') || 'default'
      if (typeof window !== 'undefined') {
        window.location.href = `/${tenantSlug}/login`
      }
    }
    window.addEventListener(AUTH_LOGOUT_EVENT, onAuthLogout)
    return () => window.removeEventListener(AUTH_LOGOUT_EVENT, onAuthLogout)
  }, [])

  useEffect(() => {
    let mounted = true
    
    // Check for stored token on mount
    const storedToken = localStorage.getItem('auth_token')
    const storedUser = localStorage.getItem('auth_user')
    const storedTenant = localStorage.getItem('current_tenant')
    
    // Get tenant from URL path if available
    const getTenantFromUrl = async () => {
      if (typeof window !== 'undefined' && mounted) {
        const tenantSlug = getTenantFromPath(window.location.pathname)
        if (tenantSlug) {
          await fetchTenantBySlug(tenantSlug)
        }
      }
    }
    
    // Fetch tenants once (with error handling to prevent infinite loops)
    const loadTenants = async () => {
      if (!mounted) return
      try {
        await fetchTenants()
      } catch (error) {
        console.error('Failed to load tenants:', error)
        // Don't retry on error to prevent infinite loops
      }
    }
    
    if (storedToken && storedUser) {
      setToken(storedToken)
      const userData = JSON.parse(storedUser)
      setUser(userData)
      
      // Load tenant if available
      if (storedTenant) {
        try {
          const tenant = JSON.parse(storedTenant)
          setCurrentTenant(tenant)
          console.log('Tenant loaded from localStorage:', tenant)
        } catch (e) {
          console.error('Error parsing stored tenant:', e)
          // If parsing fails, try to fetch it
          if (userData.tenant_id) {
            fetchTenantById(userData.tenant_id)
          } else {
            getTenantFromUrl()
          }
        }
      } else if (userData.tenant_id) {
        // Fetch tenant info if we have tenant_id but no tenant object
        fetchTenantById(userData.tenant_id).catch(err => {
          console.error('Failed to fetch tenant by ID, trying slug:', err)
          getTenantFromUrl()
        })
      } else {
        // Try to get tenant from URL or localStorage slug
        const tenantSlug = localStorage.getItem('tenant_slug')
        if (tenantSlug) {
          fetchTenantBySlug(tenantSlug).catch(err => {
            console.error('Failed to fetch tenant by slug:', err)
          })
        } else {
          getTenantFromUrl()
        }
      }
      
      // Verify token is still valid
      verifyToken(storedToken)
    } else {
      // Try to get tenant from URL even if not logged in
      getTenantFromUrl()
      setLoading(false)
    }
    
    // Fetch available tenants (only once on mount)
    loadTenants()
    
    return () => {
      mounted = false
    }
  }, [])

  const verifyToken = async (tokenToVerify: string) => {
    try {
      const response = await axios.get(`${API_URL}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${tokenToVerify}` }
      })
      const userData = response.data
      setUser(userData)
      localStorage.setItem('auth_user', JSON.stringify(userData))
      
      // If user has tenant_id, fetch and store tenant info
      if (userData.tenant_id) {
        await fetchTenantById(userData.tenant_id)
      } else {
        // If no tenant_id in user data, try to load from localStorage
        const storedTenant = localStorage.getItem('current_tenant')
        if (storedTenant) {
          try {
            setCurrentTenant(JSON.parse(storedTenant))
          } catch (e) {
            // Ignore parse errors
          }
        }
      }
      await refreshTenantConfig(tokenToVerify)
    } catch (error) {
      // Token invalid, clear storage
      localStorage.removeItem('auth_token')
      localStorage.removeItem('auth_user')
      localStorage.removeItem('current_tenant')
      setToken(null)
      setUser(null)
      setCurrentTenant(null)
    } finally {
      setLoading(false)
    }
  }

  const login = async (username: string, password: string, tenantId?: string) => {
    try {
      // Use login-json endpoint to support tenant_id
      const response = await axios.post(`${API_URL}/api/v1/auth/login-json`, {
        username,
        password,
        tenant_id: tenantId
      })
      
      const { access_token, user: userData } = response.data
      
      setToken(access_token)
      setUser(userData)
      
      localStorage.setItem('auth_token', access_token)
      localStorage.setItem('auth_user', JSON.stringify(userData))
      
      // Get tenant slug from URL path first
      let tenantSlug: string | null = null
      if (typeof window !== 'undefined') {
        tenantSlug = getTenantFromPath(window.location.pathname)
        if (tenantSlug) {
          localStorage.setItem('tenant_slug', tenantSlug)
        }
      }
      
      // Fetch and set tenant - try multiple approaches
      let tenant = null
      if (userData.tenant_id) {
        // First try: use tenant_id from user data
        console.log('Fetching tenant by ID:', userData.tenant_id)
        tenant = await fetchTenantById(userData.tenant_id)
        if (tenant) {
          console.log('Tenant fetched by ID:', tenant)
        }
      }
      
      // Second try: if no tenant_id in user data, try to fetch by slug from URL
      if (!tenant && tenantSlug) {
        console.log('Fetching tenant by slug:', tenantSlug)
        tenant = await fetchTenantBySlug(tenantSlug)
        if (tenant) {
          console.log('Tenant fetched by slug:', tenant)
        }
      }
      
      if (!tenant) {
        console.error('Failed to fetch tenant information after login. User may need to be assigned to a tenant.')
        console.error('User data:', userData)
        console.error('Tenant slug from URL:', tenantSlug)
      } else {
        console.log('Tenant successfully loaded:', tenant)
      }
      await refreshTenantConfig(access_token)
    } catch (error: any) {
      throw new Error(error.response?.data?.detail || 'Login failed')
    }
  }
  
  const setTenant = async (tenantId: string) => {
    try {
      const tenant = tenants.find(t => t.id === tenantId)
      if (tenant) {
        setCurrentTenant(tenant)
        localStorage.setItem('current_tenant', JSON.stringify(tenant))
        // Re-authenticate with new tenant if user is logged in
        if (user && token) {
          // Token already contains tenant_id, but we update the UI
          // In a real scenario, you might want to re-login with the new tenant
        }
      }
    } catch (error: any) {
      throw new Error(error.response?.data?.detail || 'Failed to set tenant')
    }
  }

  const register = async (username: string, email: string, password: string, fullName: string, role: string, tenantId?: string) => {
    try {
      // Get tenant from URL if not provided
      let finalTenantId = tenantId
      if (!finalTenantId && typeof window !== 'undefined') {
        const tenantFromPath = getTenantFromPath(window.location.pathname)
        if (tenantFromPath) {
          // Fetch tenant by slug if not in tenants list yet
          const tenant = tenants.find(t => t.name === tenantFromPath)
          if (tenant) {
            finalTenantId = tenant.id
          } else {
            // Try to fetch tenant by slug
            const fetchedTenant = await fetchTenantBySlug(tenantFromPath)
            if (fetchedTenant) {
              finalTenantId = fetchedTenant.id
            }
          }
        }
      }
      
      if (!finalTenantId) {
        throw new Error('Tenant is required. Please access the application through a tenant URL (e.g., /tenant1/login)')
      }
      
      const response = await axios.post(`${API_URL}/api/v1/auth/register`, {
        username,
        email,
        password,
        full_name: fullName,
        role,
        tenant_id: finalTenantId
      })
      
      // Auto-login after registration
      await login(username, password, finalTenantId)
    } catch (error: any) {
      throw new Error(error.response?.data?.detail || error.message || 'Registration failed')
    }
  }

  const logout = () => {
    setToken(null)
    setUser(null)
    setCurrentTenant(null)
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    localStorage.removeItem('current_tenant')
  }

  const hasRole = (role: string): boolean => {
    return user?.roles.includes(role) ?? false
  }

  const hasPermission = (permission: string): boolean => {
    if (!user?.permissions?.length) return false
    return user.permissions.includes(permission)
  }

  const hasCapability = (capability: keyof TenantCapabilities): boolean => {
    const caps = currentTenant?.capabilities ?? DEFAULT_CAPABILITIES
    return Boolean(caps[capability])
  }

  const refreshTenantConfig = async (tokenOverride?: string) => {
    const authToken = tokenOverride ?? token
    if (!authToken) return
    try {
      const response = await axios.get(`${API_URL}/api/v1/tenant-config/me`, {
        headers: { Authorization: `Bearer ${authToken}` },
      })
      const data = response.data
      const layer = data.spec_layer_settings
      const specLayer: SpecLayerSettings = {
        enabled: Boolean(layer?.enabled),
        specs_folder: layer?.specs_folder || '.github',
        coding_agent: layer?.coding_agent || 'github_copilot',
      }
      setCurrentTenant((prev) => {
        let base = prev
        if (!base) {
          try {
            const stored = localStorage.getItem('current_tenant')
            if (stored) base = JSON.parse(stored) as Tenant
          } catch {
            return prev
          }
        }
        if (!base) return prev
        const updated: Tenant = {
          ...base,
          capabilities: mergeTenantCapabilities(data.capabilities),
          onboarding_path: data.onboarding_path ?? null,
          spec_layer_settings: specLayer,
        }
        localStorage.setItem('current_tenant', JSON.stringify(updated))
        return updated
      })
    } catch (error) {
      console.error('Error refreshing tenant config:', error)
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        currentTenant,
        tenants,
        login,
        register,
        logout,
        setTenant,
        fetchTenants,
        loading,
        isAuthenticated: !!user && !!token,
        hasRole,
        hasPermission,
        hasCapability,
        refreshTenantConfig,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
