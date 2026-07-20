import type { BuildProject } from '@/lib/api/types'
import type { LucideIcon } from 'lucide-react'
import {
  Lightbulb,
  ClipboardList,
  Building2,
  BookOpen,
  Code2,
  FlaskConical,
} from 'lucide-react'

export type Project = BuildProject

export interface StepContentProps {
  project: Project
  canEdit: boolean
  onUpdate: () => void
  onStepChange?: (step: string) => void
}

export const WORKFLOW_STEPS: Array<{
  id: string
  label: string
  icon: LucideIcon
  description: string
}> = [
  { id: 'idea', label: 'Idea Agent', icon: Lightbulb, description: 'Refine your idea' },
  { id: 'features', label: 'Requirements', icon: ClipboardList, description: 'Generate features' },
  { id: 'architecture', label: 'Architecture', icon: Building2, description: 'Design architecture' },
  { id: 'stories', label: 'Stories', icon: BookOpen, description: 'Create user stories' },
  { id: 'developer', label: 'Implementation', icon: Code2, description: 'Generate code' },
  { id: 'testing', label: 'Testing', icon: FlaskConical, description: 'Create tests' },
]

export const STEP_ORDER = ['idea', 'features', 'architecture', 'stories', 'developer', 'testing'] as const
