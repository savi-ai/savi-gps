'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import './sops.css'

interface SOP {
  id: string
  title: string
  description: string
  category: string
  applies_to: string[]
  tags: string[]
  checks: Array<{
    type: string
    description: string
    pattern?: string
    questions?: string[]
  }>
  remediation_hints: Record<string, string>
}

export default function SOPsPage() {
  const { token } = useAuth()
  const [sops, setSops] = useState<SOP[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedSOP, setSelectedSOP] = useState<SOP | null>(null)
  const [filterCategory, setFilterCategory] = useState<string>('all')
  const [filterAppliesTo, setFilterAppliesTo] = useState<string>('all')

  useEffect(() => {
    if (token) {
      fetchSOPs()
    }
  }, [token])

  const fetchSOPs = async () => {
    try {
      setLoading(true)
      setError(null)
      
      // Note: SOPs API uses API key auth, but we'll try with JWT token
      // If it fails, we may need to update the backend to support JWT for SOPs
      const response = await apiClient.get('/api/v1/sops')
      setSops(response.data || [])
    } catch (err: any) {
      console.error('Error fetching SOPs:', err)
      setError(err.response?.data?.detail || err.message || 'Failed to load SOPs')
      // If API key auth fails, try to show a helpful message
      if (err.response?.status === 401 || err.response?.status === 403) {
        setError('SOPs API requires authentication. Please contact your administrator.')
      }
    } finally {
      setLoading(false)
    }
  }

  const filteredSOPs = sops.filter(sop => {
    if (filterCategory !== 'all' && sop.category !== filterCategory) return false
    if (filterAppliesTo !== 'all' && !sop.applies_to.includes(filterAppliesTo)) return false
    return true
  })

  const categories = Array.from(new Set(sops.map(sop => sop.category)))
  const appliesToOptions = Array.from(new Set(sops.flatMap(sop => sop.applies_to)))

  if (loading) {
    return (
      <div className="sops-page">
        <div className="sops-container">
          <div className="loading-state">Loading SOPs...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="sops-page">
        <div className="sops-container">
          <div className="error-state">
            <h2>Error Loading SOPs</h2>
            <p>{error}</p>
            <button onClick={fetchSOPs} className="retry-button">Retry</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="sops-page">
      <div className="sops-header">
        <h1 className="sops-title">Standard Operating Procedures (SOPs)</h1>
        <p className="sops-subtitle">View and understand the standards and procedures used in the system</p>
      </div>

      <div className="sops-layout">
        <div className="sops-sidebar">
          <div className="filters-section">
            <h3>Filters</h3>
            
            <div className="filter-group">
              <label>Category</label>
              <select 
                value={filterCategory} 
                onChange={(e) => setFilterCategory(e.target.value)}
                className="filter-select"
              >
                <option value="all">All Categories</option>
                {categories.map(cat => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <label>Applies To</label>
              <select 
                value={filterAppliesTo} 
                onChange={(e) => setFilterAppliesTo(e.target.value)}
                className="filter-select"
              >
                <option value="all">All</option>
                {appliesToOptions.map(option => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="sops-list">
            <h3>SOPs ({filteredSOPs.length})</h3>
            {filteredSOPs.length === 0 ? (
              <p className="empty-state">No SOPs found</p>
            ) : (
              <div className="sop-items">
                {filteredSOPs.map(sop => (
                  <button
                    key={sop.id}
                    className={`sop-item ${selectedSOP?.id === sop.id ? 'active' : ''}`}
                    onClick={() => setSelectedSOP(sop)}
                  >
                    <div className="sop-item-title">{sop.title}</div>
                    <div className="sop-item-category">{sop.category}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="sops-content">
          {selectedSOP ? (
            <div className="sop-detail">
              <div className="sop-detail-header">
                <h2>{selectedSOP.title}</h2>
                <div className="sop-meta">
                  <span className="sop-badge sop-badge-category">{selectedSOP.category}</span>
                  {selectedSOP.tags.map(tag => (
                    <span key={tag} className="sop-badge sop-badge-tag">{tag}</span>
                  ))}
                </div>
              </div>

              <div className="sop-section">
                <h3>Description</h3>
                <p>{selectedSOP.description}</p>
              </div>

              <div className="sop-section">
                <h3>Applies To</h3>
                <div className="applies-to-list">
                  {selectedSOP.applies_to.map(item => (
                    <span key={item} className="applies-to-item">{item}</span>
                  ))}
                </div>
              </div>

              <div className="sop-section">
                <h3>Validation Checks</h3>
                {selectedSOP.checks.length === 0 ? (
                  <p className="empty-state">No validation checks defined</p>
                ) : (
                  <div className="checks-list">
                    {selectedSOP.checks.map((check, index) => (
                      <div key={index} className="check-item">
                        <div className="check-header">
                          <span className="check-type">{check.type}</span>
                          <span className="check-description">{check.description}</span>
                        </div>
                        {check.pattern && (
                          <div className="check-detail">
                            <strong>Pattern:</strong> <code>{check.pattern}</code>
                          </div>
                        )}
                        {check.questions && check.questions.length > 0 && (
                          <div className="check-detail">
                            <strong>Questions:</strong>
                            <ul>
                              {check.questions.map((q, qIndex) => (
                                <li key={qIndex}>{q}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {Object.keys(selectedSOP.remediation_hints).length > 0 && (
                <div className="sop-section">
                  <h3>Remediation Hints</h3>
                  <div className="remediation-hints">
                    {Object.entries(selectedSOP.remediation_hints).map(([key, value]) => (
                      <div key={key} className="remediation-item">
                        <strong>{key}:</strong> {value}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="sop-placeholder">
              <p>Select a SOP from the list to view details</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
