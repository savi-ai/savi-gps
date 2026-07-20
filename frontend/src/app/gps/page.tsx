'use client'

import { Suspense, useState, useCallback, useRef, useEffect } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import axios from 'axios'
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  ConnectionMode,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
} from 'reactflow'
import 'reactflow/dist/style.css'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type WizardStep = 'project-name' | 'idea' | 'features' | 'architecture' | 'stories' | 'developer' | 'testing'

const AI_THINKING_MESSAGES = [
  'Analyzing your idea...',
  'Gathering requirements...',
  'Reviewing best practices...',
  'Generating features...',
  'Designing architecture...',
  'Creating user stories...',
  'Implementing code...',
  'Generating tests...',
  'Optimizing structure...',
]

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export default function GPSPage() {
  return (
    <Suspense fallback={<main className="wizard-container"><p>Loading wizard…</p></main>}>
      <GPSWizard />
    </Suspense>
  )
}

function GPSWizard() {
  console.log('🔵 GPSWizard component rendering...')
  
  const searchParams = useSearchParams()
  const router = useRouter()
  const projectId = searchParams?.get('project') || null
  
  console.log('🔵 projectId from searchParams:', projectId)
  
  const [step, setStep] = useState<WizardStep>('project-name')
  const [loading, setLoading] = useState(false)
  const [loadingMessage, setLoadingMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  
  // Project management
  const [projectIdState, setProjectIdState] = useState<string | null>(null)
  const [projectName, setProjectName] = useState('')
  const [featurePolling, setFeaturePolling] = useState(false)
  const [architecturePolling, setArchitecturePolling] = useState(false)
  const [projectLoaded, setProjectLoaded] = useState(false)
  
  // Step 1: Idea Agent - Chat
  const [messages, setMessages] = useState<Message[]>([])
  const [inputMessage, setInputMessage] = useState('')
  const [readyForNext, setReadyForNext] = useState(false)
  const [questionsAnswered, setQuestionsAnswered] = useState(0)
  const [vision, setVision] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  
  // Step 2: Product Manager Agent - Features
  const [features, setFeatures] = useState<any[]>([])
  const [editingFeature, setEditingFeature] = useState<number | null>(null)
  
  // Step 3: Architecture Agent
  const [architecture, setArchitecture] = useState<any>(null)
  const [nodes, setNodes] = useState<Node[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  
  // Step 4: Story Agent
  const [stories, setStories] = useState<any[]>([])
  const [editingStory, setEditingStory] = useState<number | null>(null)
  
  // Step 5: Developer Agent
  const [selectedStory, setSelectedStory] = useState<any>(null)
  const [codeImplementation, setCodeImplementation] = useState<any>(null)
  
  // Step 6: Testing Agent
  const [tests, setTests] = useState<any>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    if (messages.length > 0) {
      // Small delay to ensure DOM is updated
      setTimeout(() => {
        scrollToBottom()
      }, 100)
    }
  }, [messages])

  // Load project if projectId is provided - this is the main effect
  useEffect(() => {
    console.log('=== GPS Wizard useEffect ===')
    console.log('projectId from URL:', projectId)
    console.log('projectIdState:', projectIdState)
    console.log('projectLoaded:', projectLoaded)
    
    if (projectId) {
      // We have a project ID from URL
      if (projectId !== projectIdState) {
        // Different project or not loaded yet - always load
        console.log('🚀 Calling loadProject with ID:', projectId)
        setStep('idea') // Set step first so UI shows idea agent
        loadProject(projectId)
      } else if (!projectLoaded) {
        // Same project but not marked as loaded - load it
        console.log('🚀 Project ID matches but not loaded, calling loadProject')
        loadProject(projectId)
      } else {
        console.log('✅ Project already loaded, skipping API call')
      }
    } else {
      // No project ID, show project name step
      console.log('📝 No project ID, showing project name step')
      if (!projectIdState) {
        setStep('project-name')
      }
    }
  }, [projectId, projectIdState, projectLoaded]) // Include all dependencies

  // Poll for feature status if polling is active
  useEffect(() => {
    if (featurePolling && projectName && step === 'features') {
      const pollInterval = setInterval(async () => {
        try {
          const response = await axios.get(
            `${API_URL}/api/v1/golden-path/wizard/features-status/${encodeURIComponent(projectName)}`,
            { headers: { 'X-API-Key': 'dev-key' } }
          )

          if (response.data.status === 'completed') {
            clearInterval(pollInterval)
            setFeaturePolling(false)
            setLoading(false)
            setFeatures(response.data.features || [])
          } else if (response.data.status === 'failed') {
            clearInterval(pollInterval)
            setFeaturePolling(false)
            setLoading(false)
            setError('Feature generation failed. Please try again.')
          }
        } catch (err: any) {
          console.error('Error polling feature status:', err)
        }
      }, 10000) // Poll every 10 seconds

      return () => clearInterval(pollInterval)
    }
  }, [featurePolling, projectName, step])

  // Poll for architecture status if polling is active
  useEffect(() => {
    if (architecturePolling && projectName && step === 'architecture') {
      const pollInterval = setInterval(async () => {
        try {
          const response = await axios.get(
            `${API_URL}/api/v1/golden-path/wizard/architecture-status/${encodeURIComponent(projectName)}`,
            { headers: { 'X-API-Key': 'dev-key' } }
          )

          if (response.data.status === 'completed') {
            clearInterval(pollInterval)
            setArchitecturePolling(false)
            setLoading(false)
            const archData = response.data.architecture || {}
            setArchitecture(archData)
            
            // Convert architecture_result.json schema to React Flow format
            if (archData.nodes && archData.edges) {
              const flowNodes: Node[] = archData.nodes.map((node: any) => ({
                id: node.id,
                type: node.type || 'default',
                position: node.position || { x: 0, y: 0 },
                data: {
                  label: node.data?.label || node.id,
                  description: node.data?.description || '',
                  technology: node.data?.technology || ''
                }
              }))
              const flowEdges: Edge[] = archData.edges.map((edge: any) => ({
                id: edge.id,
                source: edge.source,
                target: edge.target,
                type: edge.type || 'default',
                label: edge.label || ''
              }))
              setNodes(flowNodes)
              setEdges(flowEdges)
            }
          } else if (response.data.status === 'failed') {
            clearInterval(pollInterval)
            setArchitecturePolling(false)
            setLoading(false)
            setError('Architecture generation failed. Please try again.')
          }
        } catch (err: any) {
          console.error('Error polling architecture status:', err)
        }
      }, 10000) // Poll every 10 seconds

      return () => clearInterval(pollInterval)
    }
  }, [architecturePolling, projectName, step])

  const loadProject = async (id: string) => {
    try {
      console.log('Making API call to load project:', id)
      console.log('API URL:', `${API_URL}/api/v1/golden-path/projects/${id}`)
      setLoading(true)
      setLoadingMessage('Loading project...')
      
      const response = await axios.get(
        `${API_URL}/api/v1/golden-path/projects/${id}`,
        { headers: { 'X-API-Key': 'dev-key' } }
      )
      
      console.log('Project API response:', response.data)
      const project = response.data
      
      // Load conversation history first - ensure it's an array
      let conversationHistory = []
      if (project.conversation_history) {
        if (Array.isArray(project.conversation_history)) {
          conversationHistory = project.conversation_history
        } else if (typeof project.conversation_history === 'string') {
          try {
            conversationHistory = JSON.parse(project.conversation_history)
          } catch (e) {
            console.error('Error parsing conversation_history:', e)
            conversationHistory = []
          }
        }
      }
      
      console.log('Loaded conversation history:', conversationHistory)
      console.log('Number of messages:', conversationHistory.length)
      console.log('Messages content:', JSON.stringify(conversationHistory, null, 2))
      
      // Set all project data
      setProjectIdState(project.id)
      setProjectName(project.name)
      setMessages(conversationHistory)
      setProjectLoaded(true) // Mark as loaded
      
      // Load other project data
      setVision(project.vision || '')
      setFeatures(project.features || [])
      
      // Load architecture and convert to React Flow format
      if (project.architecture) {
        setArchitecture(project.architecture)
        if (project.architecture.nodes && project.architecture.edges) {
          const flowNodes: Node[] = project.architecture.nodes.map((node: any) => ({
            id: node.id,
            type: node.type || 'default',
            position: node.position || { x: 0, y: 0 },
            data: {
              label: node.data?.label || node.id,
              description: node.data?.description || '',
              technology: node.data?.technology || ''
            }
          }))
          const flowEdges: Edge[] = project.architecture.edges.map((edge: any) => ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
            type: edge.type || 'default',
            label: edge.label || ''
          }))
          setNodes(flowNodes)
          setEdges(flowEdges)
        }
      }
      
      setStories(project.stories || [])
      
      // Set step to the project's current step, or 'idea' if not set
      const projectStep = project.current_step || 'idea'
      console.log('Setting step to:', projectStep)
      setStep(projectStep as WizardStep)
      
      // Check if ready for next based on conversation
      if (conversationHistory && conversationHistory.length >= 7) {
        setReadyForNext(true)
        setQuestionsAnswered(3)
      } else {
        // Count questions answered from conversation
        const userMessages = conversationHistory.filter((m: Message) => m.role === 'user')
        const assistantMessages = conversationHistory.filter((m: Message) => m.role === 'assistant')
        if (userMessages.length > 1 && assistantMessages.length >= 3) {
          setQuestionsAnswered(3)
          setReadyForNext(true)
        } else if (userMessages.length > 1) {
          const qaPairs = Math.min(assistantMessages.length, userMessages.length - 1)
          setQuestionsAnswered(qaPairs)
          setReadyForNext(qaPairs >= 3)
        }
      }
      
      // If features are being generated, start polling
      if (projectStep === 'features' && project.feature_generation_status === 'started') {
        setFeaturePolling(true)
      }
      
      // If architecture is being generated, start polling
      if (projectStep === 'architecture') {
        // Check if architecture generation is in progress by checking status files
        // This will be handled by the polling useEffect when step is 'architecture'
        // For now, we'll check if architecture exists, if not, we might need to poll
        if (!project.architecture) {
          // Architecture might be generating, but we don't have a status field yet
          // The polling will handle this when the step is 'architecture'
        }
      }
      
    } catch (err: any) {
      console.error('Error loading project:', err)
      console.error('Error response:', err.response)
      setError(err.response?.data?.detail || err.message || 'Failed to load project')
      setProjectLoaded(true) // Mark as loaded even on error to prevent retry loops
    } finally {
      // Always clear loading state
      setLoading(false)
      setLoadingMessage('')
    }
  }

  const handleCreateProject = async () => {
    if (!projectName.trim()) {
      setError('Please enter a project name')
      return
    }

    try {
      setLoading(true)
      const response = await axios.post(
        `${API_URL}/api/v1/golden-path/projects`,
        { name: projectName },
        { headers: { 'X-API-Key': 'dev-key' } }
      )
      
      setProjectIdState(response.data.id)
      setStep('idea')
      router.push(`/gps?project=${response.data.id}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to create project')
    } finally {
      setLoading(false)
    }
  }

  const showLoadingAnimation = useCallback((messages: string[]) => {
    let messageIndex = 0
    const interval = setInterval(() => {
      setLoadingMessage(messages[messageIndex % messages.length])
      messageIndex++
    }, 2000)
    return interval
  }, [])

  // Step 1: Idea Agent Chat
  const handleSendMessage = async () => {
    if (!inputMessage.trim() || !projectIdState) return

    const userMessage: Message = { role: 'user', content: inputMessage }
    const newMessages = [...messages, userMessage]
    setMessages(newMessages)
    setInputMessage('')
    setLoading(true)

    try {
      const response = await axios.post(
        `${API_URL}/api/v1/golden-path/wizard/idea-chat`,
        {
          project_id: projectIdState,
          message: inputMessage,
          conversation_history: newMessages.map(m => ({ role: m.role, content: m.content }))
        },
        { headers: { 'X-API-Key': 'dev-key' } }
      )

      const assistantMessage: Message = { role: 'assistant', content: response.data.response }
      setMessages([...newMessages, assistantMessage])
      
      setQuestionsAnswered(response.data.questions_answered || 0)
      setReadyForNext(response.data.ready_for_next || false)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to send message')
    } finally {
      setLoading(false)
    }
  }

  const handleNextFromIdea = async () => {
    if (!readyForNext || !projectIdState || !projectName) {
      setError('Please answer all 3 questions from the Idea Agent first')
      return
    }

    // Start feature generation using script
    setError(null)
    setLoading(true)
    setFeaturePolling(true)

    try {
      const conversationHistory = messages.map(m => ({ role: m.role, content: m.content }))
      
      await axios.post(
        `${API_URL}/api/v1/golden-path/wizard/generate-features`,
        { 
          project_name: projectName,
          conversation_history: conversationHistory
        },
        { headers: { 'X-API-Key': 'dev-key' } }
      )

      setStep('features')
      setLoading(false)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to start feature generation')
      setFeaturePolling(false)
      setLoading(false)
    }
  }

  // Step 2: Generate Features (if not already generated)
  const handleGenerateFeatures = async () => {
    if (features.length > 0) {
      // Features already generated, just show them
      return
    }

    setError(null)
    setLoading(true)
    const interval = showLoadingAnimation(AI_THINKING_MESSAGES.slice(2, 4))

    try {
      const ideaText = messages.map(m => `${m.role}: ${m.content}`).join('\n')
      const conversationHistory = messages.map(m => ({ role: m.role, content: m.content }))
      const response = await axios.post(
        `${API_URL}/api/v1/golden-path/wizard/generate-features`,
        { 
          idea: ideaText,
          conversation_history: conversationHistory,
          vision 
        },
        { headers: { 'X-API-Key': 'dev-key' } }
      )

      setFeatures(response.data.features || [])
      if (response.data.vision && !vision) {
        setVision(response.data.vision)
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to generate features')
    } finally {
      clearInterval(interval)
      setLoading(false)
      setLoadingMessage('')
    }
  }

  const handleAddFeature = () => {
    setFeatures([...features, {
      title: 'New Feature',
      description: '',
      business_value: '',
      actors: [],
      high_level_flow: '',
      acceptance_criteria: []
    }])
    setEditingFeature(features.length)
  }

  const handleDeleteFeature = (index: number) => {
    setFeatures(features.filter((_, i) => i !== index))
  }

  const handleUpdateFeature = (index: number, field: string, value: any) => {
    const updated = [...features]
    updated[index] = { ...updated[index], [field]: value }
    setFeatures(updated)
  }

  // Step 3: Generate Architecture
  const handleGenerateArchitecture = async () => {
    if (features.length === 0) {
      setError('Please add at least one feature first')
      return
    }

    if (!projectIdState || !projectName) {
      setError('Project information is missing')
      return
    }

    setError(null)
    setLoading(true)
    setArchitecturePolling(true)

    try {
      await axios.post(
        `${API_URL}/api/v1/golden-path/wizard/generate-architecture`,
        { 
          project_id: projectIdState,
          project_name: projectName,
          features: features
        },
        { headers: { 'X-API-Key': 'dev-key' } }
      )

      // Polling will handle the result
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to start architecture generation')
      setArchitecturePolling(false)
      setLoading(false)
    }
  }

  const onNodesChange = useCallback((changes: any) => {
    setNodes((nds) => applyNodeChanges(changes, nds))
  }, [])

  const onEdgesChange = useCallback((changes: any) => {
    setEdges((eds) => applyEdgeChanges(changes, eds))
  }, [])

  const onConnect = useCallback((params: any) => {
    setEdges((eds) => addEdge(params, eds))
  }, [])

  // Step 4: Generate Stories
  const handleGenerateStories = async () => {
    if (features.length === 0) {
      setError('Please add at least one feature first')
      return
    }

    setError(null)
    setLoading(true)
    const interval = showLoadingAnimation(AI_THINKING_MESSAGES.slice(5, 6))

    try {
      const response = await axios.post(
        `${API_URL}/api/v1/golden-path/wizard/generate-stories`,
        { features },
        { headers: { 'X-API-Key': 'dev-key' } }
      )

      setStories(response.data.stories || [])
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to generate stories')
    } finally {
      clearInterval(interval)
      setLoading(false)
      setLoadingMessage('')
    }
  }

  const handleAddStory = () => {
    setStories([...stories, {
      title: 'New Story',
      description: '',
      persona: '',
      goal: '',
      gherkin_acceptance_criteria: 'Given...\nWhen...\nThen...',
      nfrs: []
    }])
    setEditingStory(stories.length)
  }

  const handleDeleteStory = (index: number) => {
    setStories(stories.filter((_, i) => i !== index))
  }

  const handleUpdateStory = (index: number, field: string, value: any) => {
    const updated = [...stories]
    updated[index] = { ...updated[index], [field]: value }
    setStories(updated)
  }

  // Step 5: Developer Agent
  const handleGenerateCode = async () => {
    if (!selectedStory) {
      setError('Please select a story first')
      return
    }

    setError(null)
    setLoading(true)
    const interval = showLoadingAnimation(AI_THINKING_MESSAGES.slice(6, 7))

    try {
      const response = await axios.post(
        `${API_URL}/api/v1/golden-path/wizard/generate-code`,
        {
          story: selectedStory,
          architecture: architecture || {},
          stack_selections: []
        },
        { headers: { 'X-API-Key': 'dev-key' } }
      )

      setCodeImplementation(response.data.code_implementation || {})
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to generate code')
    } finally {
      clearInterval(interval)
      setLoading(false)
      setLoadingMessage('')
    }
  }

  // Step 6: Testing Agent
  const handleGenerateTests = async () => {
    if (stories.length === 0) {
      setError('Please generate stories first')
      return
    }

    setError(null)
    setLoading(true)
    const interval = showLoadingAnimation(AI_THINKING_MESSAGES.slice(7, 8))

    try {
      const response = await axios.post(
        `${API_URL}/api/v1/golden-path/wizard/generate-tests`,
        {
          stories,
          code_implementation: codeImplementation || {},
          architecture: architecture || {}
        },
        { headers: { 'X-API-Key': 'dev-key' } }
      )

      setTests(response.data.tests || {})
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to generate tests')
    } finally {
      clearInterval(interval)
      setLoading(false)
      setLoadingMessage('')
    }
  }

  return (
    <main className="wizard-container">
      <div className="wizard-header">
        <h1>Savi GPS - Wizard</h1>
        <div className="wizard-steps">
          <div className={`step ${(step as string) === 'project-name' ? 'active' : (step as string) !== 'project-name' && projectIdState ? 'completed' : ''}`}>
            <span className="step-number">0</span>
            <span className="step-label">Project</span>
          </div>
          <div className={`step ${step === 'idea' ? 'active' : ['features', 'architecture', 'stories', 'developer', 'testing'].includes(step) ? 'completed' : ''}`}>
            <span className="step-number">1</span>
            <span className="step-label">Idea Agent</span>
          </div>
          <div className={`step ${step === 'features' ? 'active' : ['architecture', 'stories', 'developer', 'testing'].includes(step) ? 'completed' : ''}`}>
            <span className="step-number">2</span>
            <span className="step-label">Product Manager</span>
          </div>
          <div className={`step ${step === 'architecture' ? 'active' : ['stories', 'developer', 'testing'].includes(step) ? 'completed' : ''}`}>
            <span className="step-number">3</span>
            <span className="step-label">Architecture</span>
          </div>
          <div className={`step ${step === 'stories' ? 'active' : ['developer', 'testing'].includes(step) ? 'completed' : ''}`}>
            <span className="step-number">4</span>
            <span className="step-label">Story Agent</span>
          </div>
          <div className={`step ${step === 'developer' ? 'active' : step === 'testing' ? 'completed' : ''}`}>
            <span className="step-number">5</span>
            <span className="step-label">Developer</span>
          </div>
          <div className={`step ${step === 'testing' ? 'active' : ''}`}>
            <span className="step-number">6</span>
            <span className="step-label">Testing</span>
          </div>
        </div>
      </div>

      {error && (
        <div className="card error-card">
          <h3>Error</h3>
          <p>{error}</p>
        </div>
      )}

      {loading && loadingMessage && (
        <div className="card loading-card">
          <div className="loading-spinner"></div>
          <p className="loading-message">{loadingMessage}</p>
        </div>
      )}

      {/* Step 0: Project Name - Only show if no project is loaded */}
      {step === 'project-name' && !loading && !projectIdState && (
        <div className="card">
          <h2 style={{ marginBottom: '0.5rem' }}>Create New Project</h2>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            Enter a name for your project to get started.
          </p>

          <div style={{ maxWidth: '500px' }}>
            <input
              type="text"
              className="input"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleCreateProject()}
              placeholder="Enter project name..."
              disabled={loading}
            />
            <button 
              className="button" 
              onClick={handleCreateProject} 
              disabled={loading || !projectName.trim()}
            >
              Create Project
            </button>
          </div>
        </div>
      )}

      {/* Step 1: Idea Agent Chat */}
      {step === 'idea' && (
        loading && loadingMessage ? (
          <div className="card loading-card">
            <div className="loading-spinner"></div>
            <p className="loading-message">{loadingMessage}</p>
          </div>
        ) : projectIdState ? (
          <div className="card">
            <h2 style={{ marginBottom: '0.5rem' }}>Idea Agent - {projectName || 'Loading...'}</h2>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
              Describe your idea and the agent will ask questions to understand it better.
            </p>
            
            {questionsAnswered > 0 && questionsAnswered < 3 && (
              <div className="progress-indicator">
                Questions answered: {questionsAnswered} of 3
              </div>
            )}
            
            <div className="chat-container">
              {messages.length === 0 ? (
                <div style={{ 
                  color: 'var(--text-secondary)', 
                  textAlign: 'center', 
                  marginTop: '3rem',
                  fontSize: '0.9375rem'
                }}>
                  <p style={{ marginBottom: '0.5rem' }}>👋 Welcome to Idea Agent</p>
                  <p>Start by describing your idea or project...</p>
                </div>
              ) : (
                <>
                  {messages.map((msg, idx) => (
                    <div key={idx} className={`chat-message ${msg.role}`}>
                      <div className={`chat-bubble ${msg.role}`}>
                        <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{msg.content || ''}</p>
                      </div>
                    </div>
                  ))}
                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'stretch' }}>
              <input
                type="text"
                className="input"
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
                placeholder="Type your message..."
                disabled={loading && !!loadingMessage}
                style={{ marginBottom: 0, flex: 1 }}
                autoFocus
              />
              <button 
                className="button" 
                onClick={handleSendMessage} 
                disabled={(loading && !!loadingMessage) || !inputMessage.trim()}
                style={{ marginBottom: 0 }}
              >
                Send
              </button>
            </div>

            <div className="wizard-actions" style={{ marginTop: '1rem' }}>
              <button 
                className="button" 
                onClick={handleNextFromIdea} 
                disabled={!readyForNext}
              >
                Next: Product Manager Agent
              </button>
            </div>
          </div>
        ) : (
          <div className="card">
            <p style={{ color: 'var(--text-secondary)' }}>Loading project...</p>
          </div>
        )
      )}

      {/* Step 2: Product Manager Agent - Features */}
      {step === 'features' && !loading && (
        <div className="card">
          <h2 style={{ marginBottom: '0.5rem' }}>Product Manager Agent - Features</h2>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            Review and modify the generated features. You can add, edit, or delete features.
          </p>

          {featurePolling && (
            <div className="progress-indicator" style={{ marginBottom: '1.5rem' }}>
              Generating features... This may take a few minutes. Please wait.
            </div>
          )}

          {!featurePolling && (
            <div className="wizard-actions" style={{ marginBottom: '1rem' }}>
              <button className="button button-secondary" onClick={handleAddFeature}>
                Add Feature
              </button>
            </div>
          )}

          <div className="features-list">
            {features.map((feature, idx) => (
              <div key={idx} className="item-card">
                {editingFeature === idx ? (
                  <div>
                    <input
                      type="text"
                      className="input"
                      value={feature.title}
                      onChange={(e) => handleUpdateFeature(idx, 'title', e.target.value)}
                      placeholder="Feature Title"
                    />
                    <textarea
                      className="textarea"
                      value={feature.description}
                      onChange={(e) => handleUpdateFeature(idx, 'description', e.target.value)}
                      placeholder="Description"
                      rows={3}
                    />
                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                      <button className="button" onClick={() => setEditingFeature(null)}>
                        Save
                      </button>
                      <button className="button button-secondary" onClick={() => handleDeleteFeature(idx)}>
                        Delete
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                      <div style={{ flex: 1 }}>
                        <h4>{feature.title || `Feature ${idx + 1}`}</h4>
                        <p>{feature.description || ''}</p>
                        {feature.business_value && (
                          <p><strong>Business Value:</strong> {feature.business_value}</p>
                        )}
                        {feature.actors && feature.actors.length > 0 && (
                          <p><strong>Actors:</strong> {feature.actors.join(', ')}</p>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button className="button button-secondary" onClick={() => setEditingFeature(idx)}>
                          Edit
                        </button>
                        <button className="button button-secondary" onClick={() => handleDeleteFeature(idx)}>
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="wizard-actions" style={{ marginTop: '1rem' }}>
            <button className="button button-secondary" onClick={() => setStep('idea')}>
              Back
            </button>
            <button 
              className="button" 
              onClick={async () => {
                if (!architecture && features.length > 0) {
                  // Auto-trigger architecture generation when moving to architecture step
                  setStep('architecture')
                  await handleGenerateArchitecture()
                } else {
                  setStep('architecture')
                }
              }} 
              disabled={features.length === 0}
            >
              Next: Architecture Agent
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Architecture Agent */}
      {step === 'architecture' && (
        <div className="card">
          <h2 style={{ marginBottom: '0.5rem' }}>Architecture Agent</h2>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            Review and modify the system architecture. You can add or modify components in the diagram.
          </p>

          {architecturePolling && (
            <div style={{ 
              padding: '1rem', 
              background: 'var(--bg-secondary)', 
              borderRadius: '8px', 
              marginBottom: '1rem',
              textAlign: 'center'
            }}>
              <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
                {loadingMessage || 'Generating architecture... This may take a few minutes.'}
              </p>
              <p style={{ margin: '0.5rem 0 0 0', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                Polling for status every 10 seconds...
              </p>
            </div>
          )}

          {!architecturePolling && !architecture && (
            <div className="wizard-actions" style={{ marginBottom: '1rem' }}>
              <button className="button" onClick={handleGenerateArchitecture} disabled={features.length === 0}>
                Generate Architecture
              </button>
            </div>
          )}

          {architecture && nodes.length > 0 && (
            <>
              <div className="architecture-info" style={{ marginBottom: '1rem' }}>
                {architecture.project_name && (
                  <p><strong>Project:</strong> {architecture.project_name}</p>
                )}
                {architecture.version && (
                  <p><strong>Version:</strong> {architecture.version}</p>
                )}
                {nodes.length > 0 && (
                  <p><strong>Services:</strong> {nodes.length}</p>
                )}
                {edges.length > 0 && (
                  <p><strong>Connections:</strong> {edges.length}</p>
                )}
              </div>
              <div className="react-flow-container" style={{ height: '600px', border: '1px solid var(--border)', borderRadius: '8px' }}>
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onConnect={onConnect}
                  connectionMode={ConnectionMode.Loose}
                  fitView
                >
                  <Background />
                  <Controls />
                  <MiniMap />
                </ReactFlow>
              </div>
            </>
          )}

          <div className="wizard-actions" style={{ marginTop: '1rem' }}>
            <button className="button button-secondary" onClick={() => setStep('features')}>
              Back
            </button>
            <button className="button" onClick={() => setStep('stories')} disabled={!architecture || nodes.length === 0}>
              Next: Story Agent
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Story Agent */}
      {step === 'stories' && !loading && (
        <div className="card">
          <h2 style={{ marginBottom: '0.5rem' }}>Story Agent</h2>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            Review and modify the Gherkin-style user stories. You can add, edit, or delete stories.
          </p>

          <div className="wizard-actions" style={{ marginBottom: '1rem' }}>
            <button className="button" onClick={handleGenerateStories}>
              Generate Stories
            </button>
            <button className="button button-secondary" onClick={handleAddStory}>
              Add Story
            </button>
          </div>

          <div className="stories-list">
            {stories.map((story, idx) => (
              <div key={idx} className="item-card">
                {editingStory === idx ? (
                  <div>
                    <input
                      type="text"
                      className="input"
                      value={story.title}
                      onChange={(e) => handleUpdateStory(idx, 'title', e.target.value)}
                      placeholder="Story Title"
                    />
                    <textarea
                      className="textarea"
                      value={story.description}
                      onChange={(e) => handleUpdateStory(idx, 'description', e.target.value)}
                      placeholder="Description"
                      rows={2}
                    />
                    <textarea
                      className="textarea"
                      value={story.gherkin_acceptance_criteria}
                      onChange={(e) => handleUpdateStory(idx, 'gherkin_acceptance_criteria', e.target.value)}
                      placeholder="Gherkin Acceptance Criteria (Given... When... Then...)"
                      rows={5}
                    />
                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                      <button className="button" onClick={() => setEditingStory(null)}>
                        Save
                      </button>
                      <button className="button button-secondary" onClick={() => handleDeleteStory(idx)}>
                        Delete
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                      <div style={{ flex: 1 }}>
                        <h4>{story.title || `Story ${idx + 1}`}</h4>
                        <p>{story.description}</p>
                        {story.persona && <p><strong>Persona:</strong> {story.persona}</p>}
                        {story.gherkin_acceptance_criteria && (
                          <div className="gherkin-section">
                            <strong>Acceptance Criteria:</strong>
                            <pre className="code-block-small">{story.gherkin_acceptance_criteria}</pre>
                          </div>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button className="button button-secondary" onClick={() => setEditingStory(idx)}>
                          Edit
                        </button>
                        <button className="button button-secondary" onClick={() => handleDeleteStory(idx)}>
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="wizard-actions" style={{ marginTop: '1rem' }}>
            <button className="button button-secondary" onClick={() => setStep('architecture')}>
              Back
            </button>
            <button className="button" onClick={() => setStep('developer')} disabled={stories.length === 0}>
              Next: Developer Agent
            </button>
          </div>
        </div>
      )}

      {/* Step 5: Developer Agent */}
      {step === 'developer' && !loading && (
        <div className="card">
          <h2 style={{ marginBottom: '0.5rem' }}>Developer Agent</h2>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            Select a story to generate code implementation.
          </p>

          <div style={{ marginBottom: '1.5rem' }}>
            <h3>Select a Story</h3>
            <div className="stories-list">
              {stories.map((story, idx) => (
                <div
                  key={idx}
                  className="item-card"
                  style={{
                    cursor: 'pointer',
                    border: selectedStory?.title === story.title ? '2px solid #0070f3' : '1px solid var(--card-border)'
                  }}
                  onClick={() => setSelectedStory(story)}
                >
                  <h4>{story.title}</h4>
                  <p>{story.description}</p>
                </div>
              ))}
            </div>
          </div>

          {selectedStory && (
            <div className="wizard-actions" style={{ marginBottom: '1rem' }}>
              <button className="button" onClick={handleGenerateCode}>
                Generate Code
              </button>
            </div>
          )}

          {codeImplementation && (
            <div className="implementation-section">
              <h3>Generated Code</h3>
              {codeImplementation.files && codeImplementation.files.length > 0 ? (
                codeImplementation.files.map((file: any, idx: number) => (
                  <div key={idx} className="implementation-item">
                    <h4>{file.path}</h4>
                    <pre className="code-block">{file.content}</pre>
                  </div>
                ))
              ) : (
                <pre className="code-block">{JSON.stringify(codeImplementation, null, 2)}</pre>
              )}
            </div>
          )}

          <div className="wizard-actions" style={{ marginTop: '1rem' }}>
            <button className="button button-secondary" onClick={() => setStep('stories')}>
              Back
            </button>
            <button className="button" onClick={() => setStep('testing')} disabled={!codeImplementation}>
              Next: Testing Agent
            </button>
          </div>
        </div>
      )}

      {/* Step 6: Testing Agent */}
      {step === 'testing' && !loading && (
        <div className="card">
          <h2 style={{ marginBottom: '0.5rem' }}>Testing Agent</h2>
          <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem' }}>
            Generate tests for the implemented stories.
          </p>

          <div className="wizard-actions" style={{ marginBottom: '1rem' }}>
            <button className="button" onClick={handleGenerateTests}>
              Generate Tests
            </button>
          </div>

          {tests && (
            <div className="implementation-section">
              <h3>Generated Tests</h3>
              {tests.unit_tests && tests.unit_tests.length > 0 && (
                <div className="implementation-item">
                  <h4>Unit Tests</h4>
                  {tests.unit_tests.map((test: any, idx: number) => (
                    <div key={idx} style={{ marginBottom: '1rem' }}>
                      <h5>{test.path}</h5>
                      <pre className="code-block">{test.content}</pre>
                    </div>
                  ))}
                </div>
              )}
              {tests.integration_tests && tests.integration_tests.length > 0 && (
                <div className="implementation-item">
                  <h4>Integration Tests</h4>
                  {tests.integration_tests.map((test: any, idx: number) => (
                    <div key={idx} style={{ marginBottom: '1rem' }}>
                      <h5>{test.path}</h5>
                      <pre className="code-block">{test.content}</pre>
                    </div>
                  ))}
                </div>
              )}
              {!tests.unit_tests && !tests.integration_tests && (
                <pre className="code-block">{JSON.stringify(tests, null, 2)}</pre>
              )}
            </div>
          )}

          <div className="wizard-actions" style={{ marginTop: '1rem' }}>
            <button className="button button-secondary" onClick={() => setStep('developer')}>
              Back
            </button>
          </div>
        </div>
      )}
    </main>
  )
}
