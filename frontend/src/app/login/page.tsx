'use client'

import { useState, useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import {
  useAuth,
  getTenantFromPath,
  pickDefaultTenant,
  rememberTenantSlug,
  DEFAULT_TENANT_SLUG,
} from '@/contexts/AuthContext'
import './login.css'

export default function LoginPage() {
  const router = useRouter()
  const pathname = usePathname()
  const { login, register, isAuthenticated, currentTenant, fetchTenants } = useAuth()
  const [isLogin, setIsLogin] = useState(true)
  const [loading, setLoading] = useState(false)
  const [resolvingTenant, setResolvingTenant] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [resolvedSlug, setResolvedSlug] = useState<string | null>(null)

  // Form state
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState('product_manager')

  // Alpha: /login works without a tenant path; optional /[tenant]/login still supported
  useEffect(() => {
    let cancelled = false
    const resolve = async () => {
      setResolvingTenant(true)
      setError(null)
      try {
        const fromPath = getTenantFromPath(pathname || '')
        const list = await fetchTenants()
        const picked =
          (fromPath ? list.find((t) => t.name === fromPath) : undefined) ||
          pickDefaultTenant(list)
        const slug =
          fromPath ||
          picked?.name ||
          (typeof window !== 'undefined' ? localStorage.getItem('tenant_slug') : null) ||
          DEFAULT_TENANT_SLUG
        rememberTenantSlug(slug)
        if (!cancelled) setResolvedSlug(slug)
      } catch {
        const slug =
          getTenantFromPath(pathname || '') ||
          (typeof window !== 'undefined' ? localStorage.getItem('tenant_slug') : null) ||
          DEFAULT_TENANT_SLUG
        rememberTenantSlug(slug)
        if (!cancelled) setResolvedSlug(slug)
      } finally {
        if (!cancelled) setResolvingTenant(false)
      }
    }
    void resolve()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resolve once per path
  }, [pathname])

  useEffect(() => {
    if (isAuthenticated && currentTenant) {
      router.push('/dashboard')
    }
  }, [isAuthenticated, currentTenant, router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      if (!localStorage.getItem('tenant_slug') && resolvedSlug) {
        rememberTenantSlug(resolvedSlug)
      }
      if (isLogin) {
        await login(username, password)
        router.push('/dashboard')
      } else {
        await register(username, email, password, fullName, role)
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
                disabled={loading || resolvingTenant}
              >
                {loading || resolvingTenant ? (
                  <>
                    <svg className="login-spinner" width="20" height="20" viewBox="0 0 20 20" fill="none">
                      <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeDasharray="31.416" strokeDashoffset="31.416">
                        <animate attributeName="stroke-dasharray" dur="2s" values="0 31.416;15.708 15.708;0 31.416;0 31.416" repeatCount="indefinite"/>
                        <animate attributeName="stroke-dashoffset" dur="2s" values="0;-15.708;-31.416;-31.416" repeatCount="indefinite"/>
                      </circle>
                    </svg>
                    <span>{resolvingTenant ? 'Preparing…' : 'Please wait...'}</span>
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
