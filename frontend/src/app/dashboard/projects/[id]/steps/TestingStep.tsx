'use client'

import { useState, useEffect } from 'react'
import apiClient from '@/lib/axios'
import { useAuth } from '@/contexts/AuthContext'
import type { StepContentProps } from '../types'

export function TestingStepContent({ project, canEdit, onUpdate }: StepContentProps) {
  const { hasPermission } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'unit' | 'integration' | 'fixtures' | 'config'>('unit')
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set())
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    // Poll for task status if we have a taskId
    if (taskId) {
      const pollInterval = setInterval(async () => {
        try {
          const response = await apiClient.get(`/api/v1/golden-path/wizard/tests-status/${project.id}`)
          const status = response.data.status
          
          if (status === 'completed') {
            clearInterval(pollInterval)
            setLoading(false)
            setTaskId(null)
            onUpdate() // Refresh to get the generated tests
          } else if (status === 'failed') {
            clearInterval(pollInterval)
            setLoading(false)
            setTaskId(null)
            setError(response.data.error || 'Test generation failed')
          }
        } catch (err: any) {
          console.error('Error polling tests status:', err)
        }
      }, 2000) // Poll every 2 seconds

      return () => clearInterval(pollInterval)
    }
  }, [taskId, project.id, onUpdate])

  const handleGenerateTests = async () => {
    if (!canEdit) return

    try {
      setLoading(true)
      setError(null)
      
      const response = await apiClient.post(`/api/v1/golden-path/wizard/generate-tests?project_id=${project.id}`)
      
      setTaskId(response.data.task_id)
      // Polling will start via useEffect
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate tests')
      setLoading(false)
      console.error('Error generating tests:', err)
    }
  }

  const handleDownloadTests = async () => {
    try {
      setDownloading(true)
      const response = await apiClient.post(
        `/api/v1/golden-path/projects/${project.id}/tests/download`,
        {},
        { responseType: 'blob' }
      )
      
      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `${project.name.replace(/\s+/g, '_')}_tests.zip`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to download tests')
    } finally {
      setDownloading(false)
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

  const getSelectedFileContent = (files: any[]): string => {
    if (!selectedFile || !files) return ''
    
    const file = files.find((f: any) => f.path === selectedFile)
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
      'json': 'json',
      'yaml': 'yaml',
      'yml': 'yaml',
      'ini': 'ini',
      'toml': 'toml'
    }
    return langMap[ext || ''] || 'plaintext'
  }

  const tests = project.tests as {
    unit_tests?: Array<{ path: string; content?: string }>
    integration_tests?: Array<{ path: string; content?: string }>
    coverage_target?: number
    test_data?: { fixtures?: unknown[]; factories?: unknown[] }
    test_configuration?: unknown[]
    test_commands?: {
      run_all?: string
      run_unit?: string
      run_integration?: string
      coverage?: string
    }
  } | null | undefined

  return (
    <div className="step-panel">
      <div className="step-panel-header">
        <h2>Testing Agent - Test Suite</h2>
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
            Generating tests... This may take a few moments.
          </div>
        </div>
      )}

      {tests ? (
        <>
          <div className="code-actions">
            <div className="test-info">
              <span className="test-stat">
                🧪 {tests.unit_tests?.length || 0} Unit Tests
              </span>
              <span className="test-stat">
                🔗 {tests.integration_tests?.length || 0} Integration Tests
              </span>
              <span className="test-stat">
                🎯 Target: {tests.coverage_target || 80}%
              </span>
            </div>
            <button 
              className="button button-download"
              onClick={handleDownloadTests}
              disabled={downloading}
            >
              {downloading ? 'Downloading...' : '⬇ Download Tests'}
            </button>
          </div>

          <div className="code-tabs">
            <button 
              className={`tab-button ${activeTab === 'unit' ? 'active' : ''}`}
              onClick={() => setActiveTab('unit')}
            >
              Unit Tests ({tests.unit_tests?.length || 0})
            </button>
            <button 
              className={`tab-button ${activeTab === 'integration' ? 'active' : ''}`}
              onClick={() => setActiveTab('integration')}
            >
              Integration Tests ({tests.integration_tests?.length || 0})
            </button>
            <button 
              className={`tab-button ${activeTab === 'fixtures' ? 'active' : ''}`}
              onClick={() => setActiveTab('fixtures')}
            >
              Fixtures & Data
            </button>
            <button 
              className={`tab-button ${activeTab === 'config' ? 'active' : ''}`}
              onClick={() => setActiveTab('config')}
            >
              Configuration
            </button>
          </div>

          <div className="code-content">
            {activeTab === 'unit' && (
              <div className="code-browser">
                <div className="file-tree-panel">
                  <h3>Unit Tests</h3>
                  <div className="file-tree">
                    {tests.unit_tests && tests.unit_tests.length > 0 ? (
                      renderFileTree(buildFileTree(tests.unit_tests))
                    ) : (
                      <p>No unit tests generated</p>
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
                          <code>{getSelectedFileContent(tests.unit_tests || [])}</code>
                        </pre>
                      </div>
                    </>
                  ) : (
                    <div className="file-viewer-empty">
                      <p>Select a test file to view its contents</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'integration' && (
              <div className="code-browser">
                <div className="file-tree-panel">
                  <h3>Integration Tests</h3>
                  <div className="file-tree">
                    {tests.integration_tests && tests.integration_tests.length > 0 ? (
                      renderFileTree(buildFileTree(tests.integration_tests))
                    ) : (
                      <p>No integration tests generated</p>
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
                          <code>{getSelectedFileContent(tests.integration_tests || [])}</code>
                        </pre>
                      </div>
                    </>
                  ) : (
                    <div className="file-viewer-empty">
                      <p>Select a test file to view its contents</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'fixtures' && (
              <div className="test-data-panel">
                <div className="test-data-section">
                  <h3>Fixtures</h3>
                  {tests.test_data?.fixtures && tests.test_data.fixtures.length > 0 ? (
                    <div className="data-grid">
                      {tests.test_data.fixtures.map((fixture: any, idx: number) => (
                        <div key={idx} className="data-card">
                          <h4>{fixture.path}</h4>
                          <pre className="data-content">{fixture.content}</pre>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>No fixtures generated</p>
                  )}
                </div>

                <div className="test-data-section">
                  <h3>Factories</h3>
                  {tests.test_data?.factories && tests.test_data.factories.length > 0 ? (
                    <div className="data-grid">
                      {tests.test_data.factories.map((factory: any, idx: number) => (
                        <div key={idx} className="data-card">
                          <h4>{factory.path}</h4>
                          <pre className="data-content">{factory.content}</pre>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>No factories generated</p>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'config' && (
              <div className="configuration-panel">
                <div className="config-section">
                  <h3>Test Configuration</h3>
                  {tests.test_configuration && tests.test_configuration.length > 0 ? (
                    <div className="config-grid">
                      {tests.test_configuration.map((config: any, idx: number) => (
                        <div key={idx} className="config-card">
                          <h4>{config.path}</h4>
                          <pre className="config-content">{config.content}</pre>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>No configuration files generated</p>
                  )}
                </div>

                <div className="config-section">
                  <h3>Test Commands</h3>
                  {tests.test_commands ? (
                    <div className="commands-list">
                      <div className="command-item">
                        <strong>Run All Tests:</strong>
                        <code>{tests.test_commands.run_all}</code>
                      </div>
                      <div className="command-item">
                        <strong>Run Unit Tests:</strong>
                        <code>{tests.test_commands.run_unit}</code>
                      </div>
                      <div className="command-item">
                        <strong>Run Integration Tests:</strong>
                        <code>{tests.test_commands.run_integration}</code>
                      </div>
                      <div className="command-item">
                        <strong>Run with Coverage:</strong>
                        <code>{tests.test_commands.coverage}</code>
                      </div>
                    </div>
                  ) : (
                    <p>No test commands available</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="empty-state">
          <p>No tests generated yet. Generate tests from your code implementation to continue.</p>
          {canEdit && (
            <button 
              className="button" 
              onClick={handleGenerateTests}
              disabled={loading || !project.code_implementation}
            >
              {loading ? 'Generating Tests...' : 'Generate Tests'}
            </button>
          )}
          {!project.code_implementation && (
            <p className="hint-text">You need to generate code first before creating tests.</p>
          )}
        </div>
      )}
    </div>
  )
}

