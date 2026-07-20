'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Search, Plus } from 'lucide-react'
import './policies.css'

interface Policy {
  id: string
  policy_id: string
  name: string
  description: string | null
  category: string
  status: 'draft' | 'active' | 'deprecated'
  applies_to: string[] | null
  stacks: string[] | null
  tags: string[] | null
  active_version_number: string | null
  created_by: string | null
  updated_by: string | null
  created_at: string
  updated_at: string
}

const CATEGORIES = [
  { id: 'ideation', name: 'Ideation' },
  { id: 'requirements', name: 'Requirements' },
  { id: 'stories', name: 'Stories' },
  { id: 'architecture', name: 'Architecture' },
  { id: 'coding', name: 'Coding' },
  { id: 'testing', name: 'Testing' },
  { id: 'security', name: 'Security' },
  { id: 'infra', name: 'Infrastructure' },
  { id: 'building_blocks', name: 'Building Blocks' }
]

const STATUSES = [
  { id: 'draft', name: 'Draft', color: 'gray' },
  { id: 'active', name: 'Active', color: 'green' },
  { id: 'deprecated', name: 'Deprecated', color: 'red' }
]

export default function PoliciesPage() {
  const router = useRouter()
  const { hasPermission } = useAuth()
  const [policies, setPolicies] = useState<Policy[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  // Filters
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null)
  const [selectedAppliesTo, setSelectedAppliesTo] = useState<string | null>(null)
  const [selectedStack, setSelectedStack] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    if (!hasPermission('can_manage_policies')) {
      router.push('/dashboard')
      return
    }
    fetchPolicies()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategory, selectedStatus, selectedAppliesTo, selectedStack, searchQuery])

  const fetchPolicies = async () => {
    try {
      setLoading(true)
      setError(null)
      
      const params = new URLSearchParams()
      if (selectedCategory) params.append('category', selectedCategory)
      if (selectedStatus) params.append('status', selectedStatus)
      if (selectedAppliesTo) params.append('applies_to', selectedAppliesTo)
      if (selectedStack) params.append('stack', selectedStack)
      if (searchQuery) params.append('search', searchQuery)
      
      const response = await apiClient.get(`/api/v1/policies?${params.toString()}`)
      setPolicies(response.data || [])
    } catch (err: any) {
      console.error('Error fetching policies:', err)
      setError(err.response?.data?.detail || 'Failed to load policies')
      setPolicies([])
    } finally {
      setLoading(false)
    }
  }

  const getStatusBadgeClass = (status: string) => {
    switch (status) {
      case 'active':
        return 'status-badge status-active'
      case 'draft':
        return 'status-badge status-draft'
      case 'deprecated':
        return 'status-badge status-deprecated'
      default:
        return 'status-badge'
    }
  }

  const getCategoryDisplayName = (category: string) => {
    const cat = CATEGORIES.find(c => c.id === category)
    return cat?.name || category
  }

  if (!hasPermission('can_manage_policies')) {
    return null
  }

  const handleLoadDefaults = async () => {
    try {
      setLoading(true)
      const response = await apiClient.post('/api/v1/policies/load-defaults')
      if (response.data) {
        alert(`Loaded ${response.data.count || 0} default policies`)
        fetchPolicies()
      }
    } catch (err: any) {
      console.error('Error loading defaults:', err)
      alert(err.response?.data?.detail || 'Failed to load default policies')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (policyId: string, policyName: string) => {
    if (!confirm(`Are you sure you want to delete "${policyName}"? This action cannot be undone.`)) {
      return
    }
    
    try {
      await apiClient.delete(`/api/v1/policies/${policyId}`)
      fetchPolicies()
    } catch (err: any) {
      console.error('Error deleting policy:', err)
      alert(err.response?.data?.detail || 'Failed to delete policy')
    }
  }

  return (
    <div className="policies-page">
      <div className="policies-header">
        <h1 className="policies-title">Policy Catalog</h1>
        <div className="header-actions">
          <button
            className="btn-secondary"
            onClick={handleLoadDefaults}
            disabled={loading}
          >
            Load Defaults
          </button>
          <button
            className="btn-primary"
            onClick={() => router.push('/dashboard/admin/policies/new')}
          >
            <Plus className="h-[18px] w-[18px]" />
            New Policy
          </button>
        </div>
      </div>

      <div className="policies-content">
        {/* Filters Sidebar */}
        <div className="policies-filters">
          <div className="filter-section">
            <h3 className="filter-title">Category</h3>
            <div className="filter-options">
              <button
                className={`filter-option ${selectedCategory === null ? 'active' : ''}`}
                onClick={() => setSelectedCategory(null)}
              >
                All
              </button>
              {CATEGORIES.map(cat => (
                <button
                  key={cat.id}
                  className={`filter-option ${selectedCategory === cat.id ? 'active' : ''}`}
                  onClick={() => setSelectedCategory(cat.id)}
                >
                  {cat.name}
                </button>
              ))}
            </div>
          </div>

          <div className="filter-section">
            <h3 className="filter-title">Status</h3>
            <div className="filter-options">
              <button
                className={`filter-option ${selectedStatus === null ? 'active' : ''}`}
                onClick={() => setSelectedStatus(null)}
              >
                All
              </button>
              {STATUSES.map(status => (
                <button
                  key={status.id}
                  className={`filter-option ${selectedStatus === status.id ? 'active' : ''}`}
                  onClick={() => setSelectedStatus(status.id)}
                >
                  {status.name}
                </button>
              ))}
            </div>
          </div>

          <div className="filter-section">
            <h3 className="filter-title">Applies To</h3>
            <div className="filter-options">
              <button
                className={`filter-option ${selectedAppliesTo === null ? 'active' : ''}`}
                onClick={() => setSelectedAppliesTo(null)}
              >
                All
              </button>
              {['story', 'architecture', 'backend', 'frontend', 'pipeline', 'infra'].map(applies => (
                <button
                  key={applies}
                  className={`filter-option ${selectedAppliesTo === applies ? 'active' : ''}`}
                  onClick={() => setSelectedAppliesTo(applies)}
                >
                  {applies.charAt(0).toUpperCase() + applies.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="filter-section">
            <h3 className="filter-title">Stack</h3>
            <div className="filter-options">
              <button
                className={`filter-option ${selectedStack === null ? 'active' : ''}`}
                onClick={() => setSelectedStack(null)}
              >
                All
              </button>
              {['Java/Spring', 'Next/React', 'Nuxt/Vue'].map(stack => (
                <button
                  key={stack}
                  className={`filter-option ${selectedStack === stack ? 'active' : ''}`}
                  onClick={() => setSelectedStack(stack)}
                >
                  {stack}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="policies-main">
          {/* Search Bar */}
          <div className="policies-search">
            <div className="search-input-wrapper">
              <Search className="search-icon h-5 w-5" />
              <input
                type="text"
                placeholder="Search policies..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="search-input"
              />
            </div>
          </div>

          {/* Policies List */}
          {loading ? (
            <div className="loading-state">Loading policies...</div>
          ) : error ? (
            <div className="error-state">{error}</div>
          ) : policies.length === 0 ? (
            <div className="empty-state">
              <p>No policies found</p>
              <button
                className="btn-primary"
                onClick={() => router.push('/dashboard/admin/policies/new')}
              >
                Create Your First Policy
              </button>
            </div>
          ) : (
            <div className="policies-list">
              <table className="policies-table">
                <thead>
                  <tr>
                    <th>Policy ID</th>
                    <th>Name</th>
                    <th>Category</th>
                    <th>Status</th>
                    <th>Version</th>
                    <th>Applies To</th>
                    <th>Last Updated</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {policies.map(policy => (
                    <tr key={policy.id} className="policy-row">
                      <td>
                        <span className="policy-id">{policy.policy_id}</span>
                      </td>
                      <td>
                        <div className="policy-name">{policy.name}</div>
                        {policy.description && (
                          <div className="policy-description">{policy.description}</div>
                        )}
                      </td>
                      <td>
                        <span className="category-badge">{getCategoryDisplayName(policy.category)}</span>
                      </td>
                      <td>
                        <span className={getStatusBadgeClass(policy.status)}>
                          {policy.status}
                        </span>
                      </td>
                      <td>
                        {policy.active_version_number ? (
                          <span className="version-badge">{policy.active_version_number}</span>
                        ) : (
                          <span className="version-badge no-version">No version</span>
                        )}
                      </td>
                      <td>
                        <div className="applies-to-chips">
                          {policy.applies_to && policy.applies_to.length > 0 ? (
                            policy.applies_to.slice(0, 2).map(applies => (
                              <span key={applies} className="chip">{applies}</span>
                            ))
                          ) : (
                            <span className="chip-empty">—</span>
                          )}
                          {policy.applies_to && policy.applies_to.length > 2 && (
                            <span className="chip-more">+{policy.applies_to.length - 2}</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="last-updated">
                          {new Date(policy.updated_at).toLocaleDateString()}
                        </div>
                      </td>
                      <td>
                        <div className="policy-actions">
                          <button
                            className="action-btn view"
                            onClick={() => router.push(`/dashboard/admin/policies/${policy.id}`)}
                            title="View"
                          >
                            View
                          </button>
                          <button
                            className="action-btn edit"
                            onClick={() => router.push(`/dashboard/admin/policies/${policy.id}/edit`)}
                            title="Edit"
                          >
                            Edit
                          </button>
                          <button
                            className="action-btn delete"
                            onClick={() => handleDelete(policy.id, policy.name)}
                            title="Delete"
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
