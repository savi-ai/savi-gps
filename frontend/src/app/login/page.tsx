'use client'

import { useState, useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuth, getTenantFromPath } from '@/contexts/AuthContext'
import './login.css'

export default function LoginPage() {
  const router = useRouter()
  const pathname = usePathname()
  const { login, register, isAuthenticated, currentTenant, fetchTenants } = useAuth()
  const [isLogin, setIsLogin] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  // Form state
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState('product_manager')
  
  // Get tenant from URL path
  const tenantSlug = getTenantFromPath(pathname || '')
  
  useEffect(() => {
    // Validate tenant from URL
    if (!tenantSlug) {
      setError('Invalid tenant URL. Please access through a tenant URL (e.g., /tenant1/login or /t/tenant1/login)')
    }
  }, [tenantSlug])

  useEffect(() => {
    if (isAuthenticated && currentTenant) {
      // Redirect to dashboard (without tenant in URL)
      router.push('/dashboard')
    }
  }, [isAuthenticated, currentTenant, router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    if (!tenantSlug) {
      setError('Tenant is required. Please access through a tenant URL.')
      setLoading(false)
      return
    }

    try {
      if (isLogin) {
        await login(username, password)
        // Redirect to dashboard without tenant in URL
        router.push('/dashboard')
      } else {
        await register(username, email, password, fullName, role)
        // Redirect to dashboard without tenant in URL
        router.push('/dashboard')
      }
    } catch (err: any) {
      setError(err.message || 'An error occurred')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-container">
      {/* Background with subtle pattern */}
      <div className="login-background">
        <div className="login-background-gradient"></div>
        <div className="login-background-pattern"></div>
      </div>

      {/* Main content */}
      <div className="login-content">
        {/* Left side - Branding */}
        <div className="login-branding">
          <div className="login-brand-content">
            <div className="login-logo">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="48" height="48" rx="12" fill="url(#logoGradient)"/>
                <path d="M24 14L32 20V28L24 34L16 28V20L24 14Z" fill="white" opacity="0.95"/>
                <defs>
                  <linearGradient id="logoGradient" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#2563eb"/>
                    <stop offset="1" stopColor="#1d4ed8"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <h1 className="login-brand-title">Savi GPS</h1>
            <p className="login-brand-subtitle">
              Transform ideas into production-ready applications with AI-powered workflow automation
            </p>
            <div className="login-features">
              <div className="login-feature-item">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                  <path d="M16.667 5L7.5 14.167 3.333 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <span>Multi-Agent Workflow</span>
              </div>
              <div className="login-feature-item">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                  <path d="M16.667 5L7.5 14.167 3.333 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <span>Role-Based Access</span>
              </div>
              <div className="login-feature-item">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                  <path d="M16.667 5L7.5 14.167 3.333 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <span>Policies</span>
              </div>
            </div>
          </div>
        </div>

        {/* Right side - Login Form */}
        <div className="login-form-wrapper">
          <div className="login-form-card">
            <div className="login-form-header">
              <h2 className="login-form-title">
                {isLogin ? 'Welcome back' : 'Create account'}
              </h2>
              <p className="login-form-subtitle">
                {isLogin 
                  ? 'Sign in to continue to Savi GPS' 
                  : 'Get started with your free account'}
              </p>
            </div>

            {error && (
              <div className="login-error">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                  <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="2"/>
                  <path d="M10 6V10M10 14H10.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                </svg>
                <span>{error}</span>
              </div>
            )}
            
            {!tenantSlug && (
              <div className="login-error" style={{ backgroundColor: '#fef3c7', borderColor: '#fbbf24', color: '#92400e' }}>
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                  <path d="M10 2C5.58 2 2 5.58 2 10s3.58 8 8 8 8-3.58 8-8-3.58-8-8-8zm1 13H9v-2h2v2zm0-4H9V7h2v4z" fill="currentColor"/>
                </svg>
                <span>Please access through a tenant URL: /tenant1/login or /t/tenant1/login</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="login-form">
              {!isLogin && (
                <>
                  <div className="login-input-group">
                    <label className="login-label">Full Name</label>
                    <input
                      type="text"
                      className="login-input"
                      placeholder="John Doe"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="login-input-group">
                    <label className="login-label">Email</label>
                    <input
                      type="email"
                      className="login-input"
                      placeholder="john@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required
                    />
                  </div>
                  <div className="login-input-group">
                    <label className="login-label">Role</label>
                    <select
                      className="login-input"
                      value={role}
                      onChange={(e) => setRole(e.target.value)}
                      required
                    >
                      <option value="product_manager">Product Manager</option>
                      <option value="architect">Architect</option>
                      <option value="developer">Developer</option>
                      <option value="qa">QA</option>
                    </select>
                  </div>
                </>
              )}

              <div className="login-input-group">
                <label className="login-label">Username</label>
                <input
                  type="text"
                  className="login-input"
                  placeholder="Enter your username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoFocus
                />
              </div>

              <div className="login-input-group">
                <label className="login-label">Password</label>
                <input
                  type="password"
                  className="login-input"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>

              <button
                type="submit"
                className="login-submit-button"
                disabled={loading}
              >
                {loading ? (
                  <>
                    <svg className="login-spinner" width="20" height="20" viewBox="0 0 20 20" fill="none">
                      <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeDasharray="31.416" strokeDashoffset="31.416">
                        <animate attributeName="stroke-dasharray" dur="2s" values="0 31.416;15.708 15.708;0 31.416;0 31.416" repeatCount="indefinite"/>
                        <animate attributeName="stroke-dashoffset" dur="2s" values="0;-15.708;-31.416;-31.416" repeatCount="indefinite"/>
                      </circle>
                    </svg>
                    <span>Please wait...</span>
                  </>
                ) : (
                  <span>{isLogin ? 'Sign In' : 'Create Account'}</span>
                )}
              </button>
            </form>

            <div className="login-switch">
              <button
                type="button"
                onClick={() => {
                  setIsLogin(!isLogin)
                  setError(null)
                }}
                className="login-switch-button"
              >
                {isLogin ? (
                  <>
                    Don't have an account? <span>Sign up</span>
                  </>
                ) : (
                  <>
                    Already have an account? <span>Sign in</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
