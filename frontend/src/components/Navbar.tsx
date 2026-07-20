'use client'

import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import Link from 'next/link'

export default function Navbar() {
  const { user, logout, hasRole } = useAuth()
  const router = useRouter()

  const handleLogout = () => {
    logout()
    router.push('/login')
  }

  const getRoleDisplayName = (role: string) => {
    const roleMap: Record<string, string> = {
      product_manager: 'Product Manager',
      architect: 'Architect',
      developer: 'Developer',
      qa: 'QA'
    }
    return roleMap[role] || role
  }

  return (
    <nav style={{
      background: 'var(--card-bg)',
      borderBottom: '1px solid var(--card-border)',
      padding: '1rem 2rem',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      boxShadow: 'var(--shadow-sm)'
    }}>
      <Link href="/" style={{ textDecoration: 'none' }}>
        <h1 style={{ 
          margin: 0, 
          fontSize: '1.5rem',
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text'
        }}>
          Savi GPS
        </h1>
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
        {user && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <div style={{ textAlign: 'right' }}>
                <div style={{ 
                  fontWeight: 600, 
                  fontSize: '0.9375rem',
                  color: 'var(--text-primary)'
                }}>
                  {user.full_name || user.username}
                </div>
                <div style={{ 
                  fontSize: '0.8125rem',
                  color: 'var(--text-secondary)'
                }}>
                  {user.roles.map(getRoleDisplayName).join(', ')}
                </div>
              </div>
              <button
                onClick={handleLogout}
                className="button"
                style={{ 
                  padding: '0.5rem 1rem',
                  fontSize: '0.875rem'
                }}
              >
                Logout
              </button>
            </div>
          </>
        )}
      </div>
    </nav>
  )
}
