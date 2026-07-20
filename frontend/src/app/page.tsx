'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import axios from 'axios'
import ProtectedRoute from '@/components/ProtectedRoute'
import Navbar from '@/components/Navbar'
import { useAuth } from '@/contexts/AuthContext'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Project {
  id: string
  name: string
  current_step: string
  created_at: string
  updated_at: string
}

export default function Home() {
  const router = useRouter()
  const { token, hasPermission } = useAuth()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (token) {
      console.log('Home component mounted, fetching projects...')
      fetchProjects()
    }
  }, [token])

  const fetchProjects = async () => {
    try {
      setLoading(true)
      setError(null)
      console.log('Fetching projects from:', `${API_URL}/api/v1/golden-path/projects`)
      
      const response = await axios.get(
        `${API_URL}/api/v1/golden-path/projects`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      
      console.log('Projects API response:', response.data)
      const projectsList = response.data?.projects || response.data || []
      console.log('Projects list:', projectsList)
      setProjects(projectsList)
    } catch (err: any) {
      console.error('Error fetching projects:', err)
      console.error('Error details:', err.response?.data || err.message)
      setError(err.response?.data?.detail || err.message || 'Failed to load projects')
      setProjects([])
    } finally {
      setLoading(false)
    }
  }

  const handleStartWizard = () => {
    router.push('/gps')
  }

  const handleProjectClick = (projectId: string) => {
    router.push(`/gps?project=${projectId}`)
  }

  const getStepLabel = (step: string) => {
    const stepMap: { [key: string]: string } = {
      'idea': 'Idea Agent',
      'features': 'Product Manager',
      'architecture': 'Architecture',
      'stories': 'Story Agent',
      'developer': 'Developer',
      'testing': 'Testing'
    }
    return stepMap[step] || step
  }

  const getStepProgress = (step: string) => {
    const stepOrder = ['idea', 'features', 'architecture', 'stories', 'developer', 'testing']
    const currentIndex = stepOrder.indexOf(step)
    return currentIndex >= 0 ? ((currentIndex + 1) / stepOrder.length) * 100 : 0
  }

  // Redirect to dashboard after login
  useEffect(() => {
    if (token && !loading) {
      router.push('/dashboard')
      return
    }
  }, [token, loading, router])

  if (token && !loading) {
    return null // Will redirect
  }

  return (
    <ProtectedRoute>
      <Navbar />
      <main className="container">
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'flex-start', 
        marginBottom: '3rem',
        gap: '2rem'
      }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ marginBottom: '0.75rem' }}>Savi GPS</h1>
          <p style={{ 
            color: 'var(--text-secondary)', 
            fontSize: '1.125rem',
            lineHeight: '1.6',
            maxWidth: '600px'
          }}>
            Transform your ideas into production-ready applications with AI-powered workflow automation
          </p>
        </div>
        {hasPermission('can_create_project') && (
          <button 
            className="button" 
            onClick={handleStartWizard}
            style={{ 
              fontSize: '1rem', 
              padding: '0.875rem 2rem',
              whiteSpace: 'nowrap'
            }}
          >
            Start New Project
          </button>
        )}
      </div>

      <div className="card">
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center',
          marginBottom: '1.5rem',
          paddingBottom: '1rem',
          borderBottom: '1px solid var(--card-border)'
        }}>
          <h2 style={{ margin: 0 }}>Saved Projects</h2>
          <span style={{ 
            color: 'var(--text-secondary)', 
            fontSize: '0.875rem',
            fontWeight: 500
          }}>
            {projects.length} {projects.length === 1 ? 'project' : 'projects'}
          </span>
        </div>
        
        {loading ? (
          <div style={{ textAlign: 'center', padding: '4rem 2rem' }}>
            <div className="loading-spinner"></div>
            <p style={{ marginTop: '1.5rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
              Loading projects...
            </p>
          </div>
        ) : error ? (
          <div className="error-card">
            <p style={{ margin: 0, fontWeight: 500 }}>{error}</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            {projects.length === 0 ? (
              <div style={{ 
                padding: '3rem', 
                textAlign: 'center', 
                color: 'var(--text-secondary)',
                fontSize: '0.9375rem'
              }}>
                No projects yet. Click "Start New Project" to create your first project.
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Project Name</th>
                    <th>Current Step</th>
                    <th>Progress</th>
                    <th>Last Updated</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((project) => (
                    <tr key={project.id} style={{ cursor: 'pointer' }} onClick={() => handleProjectClick(project.id)}>
                      <td style={{ fontWeight: 500 }}>{project.name}</td>
                      <td>
                        <span className="status-badge in_progress">
                          {getStepLabel(project.current_step)}
                        </span>
                      </td>
                      <td>
                        <div style={{ 
                          width: '100%', 
                          backgroundColor: 'var(--item-bg)', 
                          borderRadius: '4px',
                          height: '8px',
                          overflow: 'hidden'
                        }}>
                          <div style={{
                            width: `${getStepProgress(project.current_step)}%`,
                            backgroundColor: 'var(--primary)',
                            height: '100%',
                            transition: 'width 0.3s ease'
                          }} />
                        </div>
                      </td>
                      <td style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                        {new Date(project.updated_at).toLocaleDateString()}
                      </td>
                      <td>
                        <button 
                          className="button" 
                          style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                          onClick={(e) => {
                            e.stopPropagation()
                            handleProjectClick(project.id)
                          }}
                        >
                          Open
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
      </main>
    </ProtectedRoute>
  )
}
