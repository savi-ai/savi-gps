'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import type { Project, StepContentProps } from '../types'
import { CheckCircle2, Lightbulb } from 'lucide-react'

export function IdeaStepContent({ project, canEdit, onUpdate, onStepChange }: StepContentProps & { onStepChange: (step: string) => void }) {
  const { user } = useAuth()
  const conversationHistory = project.conversation_history || []
  const hasConversation = conversationHistory.length > 0
  
  // Pre-fill with project description only if conversation is empty
  const initialMessage = !hasConversation && project.description ? project.description : ''
  
  const [message, setMessage] = useState(initialMessage)
  const [loading, setLoading] = useState(false)
  const [readyForNext, setReadyForNext] = useState(false)
  const [conversation, setConversation] = useState<Array<{ role: string; content: string }>>(
    conversationHistory
  )
  const [lastCitations, setLastCitations] = useState<string[]>([])

  // Update conversation when project changes
  useEffect(() => {
    const updatedHistory = project.conversation_history || []
    setConversation(updatedHistory)
    
    // Pre-fill with project description only if conversation is empty
    if (updatedHistory.length === 0 && project.description) {
      setMessage(project.description)
    } else if (updatedHistory.length > 0) {
      // If conversation exists, clear the message field
      setMessage('')
    }
    
    // Set readyForNext based on step_status
    if (project.current_step === 'idea' && project.step_status === 'ReadyForNext') {
      setReadyForNext(true)
    } else {
      setReadyForNext(false)
    }
  }, [project.conversation_history, project.description, project.current_step, project.step_status])
  
  // Listen for step switch events
  useEffect(() => {
    const handleStepSwitch = (e: CustomEvent) => {
      const step = e.detail
      if (step) {
        // This will be handled by the parent component
        window.dispatchEvent(new CustomEvent('switchStep', { detail: step }))
      }
    }
    
    window.addEventListener('switchStep' as any, handleStepSwitch as EventListener)
    return () => {
      window.removeEventListener('switchStep' as any, handleStepSwitch as EventListener)
    }
  }, [])

  const handleSendMessage = async () => {
    if (!message.trim() || !canEdit) return

    const userMessage = message.trim()
    const currentConversation = conversation // Save current state before updating
    
    // Add user message immediately
    setConversation(prev => [
      ...prev,
      { role: 'user', content: userMessage },
      { role: 'assistant', content: '...' } // Typing indicator
    ])
    
    // Clear input immediately
    setMessage('')
    setLoading(true)

    try {
      const response = await apiClient.post('/api/v1/golden-path/wizard/idea-chat', {
        project_id: project.id,
        message: userMessage,
        conversation_history: currentConversation
      })

      // Replace typing indicator with actual response
      setConversation(prev => {
        const newConversation = [...prev]
        const typingIndex = newConversation.findIndex(
          (msg, idx) => msg.role === 'assistant' && msg.content === '...'
        )
        if (typingIndex !== -1) {
          newConversation[typingIndex] = { role: 'assistant', content: response.data.response }
        } else {
          newConversation.push({ role: 'assistant', content: response.data.response })
        }
        return newConversation
      })

      if (response.data.citations?.length) {
        setLastCitations(response.data.citations)
      }
      
      // onUpdate will refresh project data which includes step_status
      // The step_status will be set to "ReadyForNext" by the backend if ready_for_next is true
      onUpdate()
    } catch (err: any) {
      // Remove typing indicator on error
      setConversation(prev => prev.filter((msg) => !(msg.role === 'assistant' && msg.content === '...')))
      alert(err.response?.data?.detail || 'Failed to send message')
    } finally {
      setLoading(false)
    }
  }

  const handleContinueToRequirements = async () => {
    try {
      setLoading(true)
      await apiClient.patch(`/api/v1/golden-path/projects/${project.id}/step?step=features`)
      onUpdate()
      // Switch to features step
      onStepChange('features')
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to update project step')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="step-panel">
      <div className="step-panel-header">
        <h2>Idea Agent</h2>
        {!canEdit && <span className="read-only-indicator">Read Only</span>}
      </div>
      
      {project.vision && (
        <div className="vision-section">
          <h3>Vision</h3>
          <p>{project.vision}</p>
        </div>
      )}

      <div className="chat-container">
        <div className="chat-messages">
          {conversation.length === 0 ? (
            <div className="empty-chat">
              <p>Start a conversation with the Idea Agent to refine your project idea.</p>
            </div>
          ) : (
            conversation.map((msg, idx) => {
              const isTyping = msg.role === 'assistant' && msg.content === '...'
              return (
                <div key={idx} className={`chat-message ${msg.role} ${isTyping ? 'typing' : ''}`}>
                  {msg.role === 'user' ? (
                    <>
                      <div className="chat-avatar user-avatar">
                        {user?.full_name?.[0]?.toUpperCase() || user?.username?.[0]?.toUpperCase() || 'U'}
                      </div>
                      <div className="chat-bubble">
                        {msg.content}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="chat-avatar agent-avatar">
                        <Lightbulb className="h-4 w-4" />
                      </div>
                      <div className="chat-bubble">
                        {isTyping ? (
                          <div className="typing-indicator">
                            <span></span>
                            <span></span>
                            <span></span>
                          </div>
                        ) : (
                          msg.content
                        )}
                      </div>
                    </>
                  )}
                </div>
              )
            })
          )}
        </div>

        {lastCitations.length > 0 && (
          <div className="idea-citations">
            <span className="idea-citations-label">Sources cited:</span>
            {lastCitations.map((cite) => (
              <code key={cite} className="idea-citation-chip">{cite}</code>
            ))}
          </div>
        )}
        
        {canEdit && (
          <>
            {readyForNext && (
              <div className="continue-to-next">
                <div className="continue-message">
                  <CheckCircle2 className="h-5 w-5" />
                  <span>Idea is ready! You can now proceed to generate requirements.</span>
                </div>
                <button 
                  className="button continue-button"
                  onClick={handleContinueToRequirements}
                  disabled={loading}
                >
                  Continue to Requirements →
                </button>
              </div>
            )}
            <div className="chat-input">
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Type your message..."
                disabled={loading}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSendMessage()
                  }
                }}
              />
              <button 
                className="button" 
                onClick={handleSendMessage}
                disabled={loading || !message.trim()}
              >
                {loading ? 'Sending...' : 'Send'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
