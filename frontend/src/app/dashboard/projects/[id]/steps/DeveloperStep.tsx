'use client'

import { useState, useEffect } from 'react'
import apiClient from '@/lib/axios'
import { useAuth } from '@/contexts/AuthContext'
import type { StepContentProps } from '../types'
import { CheckCircle2 } from 'lucide-react'

export function DeveloperStepContent({ project, canEdit, onUpdate }: StepContentProps) {
  const { hasPermission } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'files' | 'docs' | 'config'>('files')
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set())
  const [downloading, setDownloading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [githubRepoUrl, setGithubRepoUrl] = useState(project.github_repo_url || '')
  const [editingGithubUrl, setEditingGithubUrl] = useState(false)
  const [savingGithubUrl, setSavingGithubUrl] = useState(false)
  const [pushingToGithub, setPushingToGithub] = useState(false)
  const [githubPushResult, setGithubPushResult] = useState<any>(null)

  useEffect(() => {
    // Poll for task status if we have a taskId
    if (taskId) {
      const pollInterval = setInterval(async () => {
        try {
          const response = await apiClient.get(`/api/v1/golden-path/wizard/code-status/${project.id}`)
          const status = response.data.status
          
          if (status === 'completed') {
            clearInterval(pollInterval)
            setLoading(false)
            setTaskId(null)
            onUpdate() // Refresh to get the generated code
          } else if (status === 'failed') {
            clearInterval(pollInterval)
            setLoading(false)
            setTaskId(null)
            setError(response.data.error || 'Code generation failed')
          }
        } catch (err: any) {
          console.error('Error polling code status:', err)
        }
      }, 2000) // Poll every 2 seconds

      return () => clearInterval(pollInterval)
    }
  }, [taskId, project.id, onUpdate])

  const handleGenerateCode = async () => {
    if (!canEdit) return

    try {
      setLoading(true)
      setError(null)
      
      const response = await apiClient.post(`/api/v1/golden-path/wizard/generate-code?project_id=${project.id}`)
      
      setTaskId(response.data.task_id)
      // Polling will start via useEffect
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate code')
      setLoading(false)
      console.error('Error generating code:', err)
    }
  }

  const handleDownloadCode = async () => {
    try {
      setDownloading(true)
      const response = await apiClient.post(
        `/api/v1/golden-path/projects/${project.id}/code/download`,
        {},
        { responseType: 'blob' }
      )
      
      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `${project.name.replace(/\s+/g, '_')}_code.zip`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to download code')
    } finally {
      setDownloading(false)
    }
  }

  const handleApproveAndSubmit = async () => {
    if (!hasPermission('can_use_developer_agent')) return

    try {
      setSubmitting(true)
      // Update step to testing
      await apiClient.patch(`/api/v1/golden-path/projects/${project.id}/step?step=testing`)
      onUpdate()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to submit for testing')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSaveGithubUrl = async () => {
    try {
      setSavingGithubUrl(true)
      setError(null)
      const response = await apiClient.put(
        `/api/v1/golden-path/projects/${project.id}/github-repo`,
        null,
        { params: { github_repo_url: githubRepoUrl } }
      )
      setEditingGithubUrl(false)
      if (response.data?.graduation?.repository?.id) {
        setGithubPushResult({
          success: true,
          message: 'GitHub URL saved and registered in Intelligence',
          graduation: response.data.graduation,
        })
      }
      onUpdate()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save GitHub URL')
    } finally {
      setSavingGithubUrl(false)
    }
  }

  const handlePushToGithub = async () => {
    try {
      setPushingToGithub(true)
      setGithubPushResult(null)
      setError(null)
      
      const response = await apiClient.post(`/api/v1/golden-path/projects/${project.id}/push-to-github`)
      
      setGithubPushResult(response.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to push to GitHub')
    } finally {
      setPushingToGithub(false)
    }
  }

  const toggleDirectory = (dirPath: string) => {
    const newExpanded = new Set(expandedDirs)
    if (newExpanded.has(dirPath)) {
      newExpanded.delete(dirPath)
    } else {
      newExpanded.add(dirPath)
    }
    setExpandedDirs(newExpanded)
  }

  const buildFileTree = (files: any[]): any => {
    const tree: any = {}
    
    files.forEach(file => {
      const parts = file.path.split('/')
      let current = tree
      
      parts.forEach((part: string, index: number) => {
        if (index === parts.length - 1) {
          // It's a file
          if (!current._files) current._files = []
          current._files.push({ name: part, path: file.path, content: file.content })
        } else {
          // It's a directory
          if (!current[part]) current[part] = {}
          current = current[part]
        }
      })
    })
    
    return tree
  }

  const renderFileTree = (tree: any, path: string = '', level: number = 0): JSX.Element[] => {
    const elements: JSX.Element[] = []
    
    // Render directories
    Object.keys(tree).forEach(key => {
      if (key === '_files') return
      
      const dirPath = path ? `${path}/${key}` : key
      const isExpanded = expandedDirs.has(dirPath)
      
      elements.push(
        <div key={dirPath} style={{ marginLeft: `${level * 16}px` }}>
          <div 
            className="file-tree-item directory"
            onClick={() => toggleDirectory(dirPath)}
          >
            <span className="file-icon">{isExpanded ? '📂' : '📁'}</span>
            <span className="file-name">{key}</span>
          </div>
          {isExpanded && renderFileTree(tree[key], dirPath, level + 1)}
        </div>
      )
    })
    
    // Render files
    if (tree._files) {
      tree._files.forEach((file: any) => {
        elements.push(
          <div 
            key={file.path} 
            className={`file-tree-item file ${selectedFile === file.path ? 'selected' : ''}`}
            style={{ marginLeft: `${level * 16}px` }}
            onClick={() => setSelectedFile(file.path)}
          >
            <span className="file-icon">📄</span>
            <span className="file-name">{file.name}</span>
          </div>
        )
      })
    }
    
    return elements
  }

  const getSelectedFileContent = (): string => {
    const codeImpl = project.code_implementation as { files?: Array<{ path: string; content?: string }> } | null | undefined
    if (!selectedFile || !codeImpl?.files) return ''

    const file = codeImpl.files.find((f) => f.path === selectedFile)
    return file?.content || ''
  }

  const getFileLanguage = (filename: string): string => {
    const ext = filename.split('.').pop()?.toLowerCase()
    const langMap: { [key: string]: string } = {
      'js': 'javascript',
      'jsx': 'javascript',
      'ts': 'typescript',
      'tsx': 'typescript',
      'py': 'python',
      'java': 'java',
      'go': 'go',
      'rs': 'rust',
      'rb': 'ruby',
      'php': 'php',
      'html': 'html',
      'css': 'css',
      'json': 'json',
      'yaml': 'yaml',
      'yml': 'yaml',
      'md': 'markdown',
      'sh': 'bash',
      'sql': 'sql'
    }
    return langMap[ext || ''] || 'plaintext'
  }

  const codeImpl = project.code_implementation as {
    files?: Array<{ path: string; content?: string }>
    documentation?: Record<string, string>
    configuration?: Record<string, string>
  } | null | undefined

  return (
    <div className="step-panel">
      <div className="step-panel-header">
        <h2>Developer Agent - Code Implementation</h2>
        {!canEdit && <span className="read-only-indicator">Read Only</span>}
      </div>
      
      {error && (
        <div className="error-message" style={{ margin: '1rem 0', padding: '0.75rem', background: '#fee2e2', color: '#dc2626', borderRadius: '8px' }}>
          {error}
        </div>
      )}

      {loading && (
        <div className="status-message generating-features">
          <div className="generating-animation">
            <div className="spinner"></div>
          </div>
          <div className="status-text">
            Generating code... This may take a few moments.
          </div>
        </div>
      )}

      {codeImpl ? (
        <>
          <div className="code-actions">
            <div className="github-section">
              {editingGithubUrl ? (
                <div className="github-url-edit">
                  <input
                    type="text"
                    value={githubRepoUrl}
                    onChange={(e) => setGithubRepoUrl(e.target.value)}
                    placeholder="https://github.com/username/repo.git"
                    className="github-url-input"
                  />
                  <button 
                    className="button button-small"
                    onClick={handleSaveGithubUrl}
                    disabled={savingGithubUrl}
                  >
                    {savingGithubUrl ? 'Saving...' : 'Save'}
                  </button>
                  <button 
                    className="button button-small button-secondary"
                    onClick={() => {
                      setEditingGithubUrl(false)
                      setGithubRepoUrl(project.github_repo_url || '')
                    }}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="github-url-display">
                  {project.github_repo_url ? (
                    <>
                      <span className="github-url-label">📦 {project.github_repo_url}</span>
                      {canEdit && (
                        <button 
                          className="button button-small button-secondary"
                          onClick={() => setEditingGithubUrl(true)}
                        >
                          Edit
                        </button>
                      )}
                      <button 
                        className="button button-github"
                        onClick={handlePushToGithub}
                        disabled={pushingToGithub}
                      >
                        {pushingToGithub ? 'Pushing...' : '🚀 Push to GitHub'}
                      </button>
                    </>
                  ) : canEdit ? (
                    <button 
                      className="button button-secondary"
                      onClick={() => setEditingGithubUrl(true)}
                    >
                      + Add GitHub Repository
                    </button>
                  ) : null}
                </div>
              )}
              {githubPushResult && githubPushResult.success && (
                <div className="github-success-message space-y-1">
                  <div>✓ {githubPushResult.message}</div>
                  {githubPushResult.graduation?.repository?.id && (
                    <div className="text-sm">
                      Graduated into Intelligence:{' '}
                      <a
                        href={`/dashboard/intelligence/repositories/${githubPushResult.graduation.repository.id}`}
                        className="underline"
                      >
                        {githubPushResult.graduation.repository.github_full_name ||
                          githubPushResult.graduation.repository.name}
                      </a>
                      {githubPushResult.graduation.index_run_id
                        ? ' — indexing queued'
                        : ''}
                      {githubPushResult.graduation.application_id ? (
                        <>
                          {' · '}
                          <a
                            href={`/dashboard/intelligence/applications/${githubPushResult.graduation.application_id}`}
                            className="underline"
                          >
                            Application
                          </a>
                        </>
                      ) : null}
                    </div>
                  )}
                </div>
              )}
            </div>
            <button 
              className="button button-download"
              onClick={handleDownloadCode}
              disabled={downloading}
            >
              {downloading ? 'Downloading...' : '⬇ Download Code'}
            </button>
          </div>

          <div className="code-tabs">
            <button 
              className={`tab-button ${activeTab === 'files' ? 'active' : ''}`}
              onClick={() => setActiveTab('files')}
            >
              Files
            </button>
            <button 
              className={`tab-button ${activeTab === 'docs' ? 'active' : ''}`}
              onClick={() => setActiveTab('docs')}
            >
              Documentation
            </button>
            <button 
              className={`tab-button ${activeTab === 'config' ? 'active' : ''}`}
              onClick={() => setActiveTab('config')}
            >
              Configuration
            </button>
          </div>

          <div className="code-content">
            {activeTab === 'files' && (
              <div className="code-browser">
                <div className="file-tree-panel">
                  <h3>Project Structure</h3>
                  <div className="file-tree">
                    {codeImpl.files && codeImpl.files.length > 0 ? (
                      renderFileTree(buildFileTree(codeImpl.files))
                    ) : (
                      <p>No files generated</p>
                    )}
                  </div>
                </div>
                <div className="file-viewer-panel">
                  {selectedFile ? (
                    <>
                      <div className="file-viewer-header">
                        <h3>{selectedFile}</h3>
                      </div>
                      <div className="file-viewer-content">
                        <pre className={`language-${getFileLanguage(selectedFile)}`}>
                          <code>{getSelectedFileContent()}</code>
                        </pre>
                      </div>
                    </>
                  ) : (
                    <div className="file-viewer-empty">
                      <p>Select a file to view its contents</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'docs' && (
              <div className="documentation-panel">
                {codeImpl.documentation ? (
                  <div className="docs-grid">
                    {Object.entries(codeImpl.documentation).map(([docName, content]) => (
                      <div key={docName} className="doc-card">
                        <h3>{docName}</h3>
                        <pre className="doc-content">{String(content)}</pre>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p>No documentation available</p>
                )}
              </div>
            )}

            {activeTab === 'config' && (
              <div className="configuration-panel">
                {codeImpl.configuration ? (
                  <div className="config-grid">
                    {Object.entries(codeImpl.configuration).map(([configName, content]) => (
                      <div key={configName} className="config-card">
                        <h3>{configName}</h3>
                        <pre className="config-content">{String(content)}</pre>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p>No configuration files available</p>
                )}
              </div>
            )}
          </div>

          {hasPermission('can_use_developer_agent') && canEdit && (
            <div className="approve-section">
              <div className="approve-message">
                <CheckCircle2 className="h-5 w-5" />
                <span>Review the generated code above. When ready, approve and submit for testing.</span>
              </div>
              <button 
                className="button approve-button"
                onClick={handleApproveAndSubmit}
                disabled={submitting}
              >
                {submitting ? 'Submitting...' : 'Approve and Submit for Testing'}
              </button>
            </div>
          )}
        </>
      ) : (
        <div className="empty-state">
          <p>No code generated yet. Generate code from your architecture and stories to continue.</p>
          {canEdit && (
            <button 
              className="button" 
              onClick={handleGenerateCode}
              disabled={loading || !project.architecture || !project.stories}
            >
              {loading ? 'Generating Code...' : 'Generate Code'}
            </button>
          )}
          {(!project.architecture || !project.stories) && (
            <p className="hint-text">You need to complete architecture and stories first before generating code.</p>
          )}
        </div>
      )}
    </div>
  )
}

