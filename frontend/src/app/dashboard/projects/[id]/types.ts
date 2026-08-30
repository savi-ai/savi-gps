import type { BuildProject } from '@/lib/api/types'
import type { LucideIcon } from 'lucide-react'
import {
  Lightbulb,
  ClipboardList,
  Building2,
  BookOpen,
  Code2,
  FlaskConical,
  Upload,
  ListTodo,
  Wrench,
  GitPullRequest,
} from 'lucide-react'

export type Project = BuildProject

export interface StepContentProps {
  project: Project
  canEdit: boolean
  onUpdate: () => void
  onStepChange?: (step: string) => void
}

export const BUILD_WORKFLOW_STEPS: Array<{
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

/** W5 modernize Alpha: Requirements → Tasks → Code → Test → Push */
export const MODERNIZE_WORKFLOW_STEPS: Array<{
  id: string
  label: string
  icon: LucideIcon
  description: string
}> = [
  {
    id: 'features',
    label: 'Requirements',
    icon: ClipboardList,
    description: 'Derive modernization requirements from the plan',
  },
  {
    id: 'stories',
    label: 'Tasks',
    icon: ListTodo,
    description: 'Break requirements into implementable tasks',
  },
  {
    id: 'developer',
    label: 'Code',
    icon: Code2,
    description: 'Implement against linked source / target repo',
  },
  {
    id: 'testing',
    label: 'Test',
    icon: FlaskConical,
    description: 'Generate or run tests before push',
  },
  {
    id: 'push',
    label: 'Push',
    icon: Upload,
    description: 'Push branch to the user-provided GitHub repo',
  },
]

export const BUILD_STEP_ORDER = [
  'idea',
  'features',
  'architecture',
  'stories',
  'developer',
  'testing',
] as const

export const MODERNIZE_STEP_ORDER = [
  'features',
  'stories',
  'developer',
  'testing',
  'push',
] as const

/** W8 fix track: Fix → Code → Test → Push → PR (execution panel drives stages) */
export const FIX_WORKFLOW_STEPS: Array<{
  id: string
  label: string
  icon: LucideIcon
  description: string
}> = [
  { id: 'fix', label: 'Fix', icon: Wrench, description: 'Lock remediation scope from findings' },
  { id: 'code', label: 'Code', icon: Code2, description: 'Apply patches in source/' },
  { id: 'test', label: 'Test', icon: FlaskConical, description: 'Run or add verification' },
  { id: 'push', label: 'Push', icon: Upload, description: 'Push branch to same repo' },
  { id: 'pr', label: 'PR', icon: GitPullRequest, description: 'Open pull request' },
]

export const FIX_STEP_ORDER = ['fix', 'code', 'test', 'push', 'pr'] as const

/** @deprecated Prefer getWorkflowSteps(pillar) */
export const WORKFLOW_STEPS = BUILD_WORKFLOW_STEPS
/** @deprecated Prefer getStepOrder(pillar) */
export const STEP_ORDER = BUILD_STEP_ORDER

export function getWorkflowSteps(pillar?: string | null) {
  if (pillar === 'fix') return FIX_WORKFLOW_STEPS
  if (pillar === 'modernize') return MODERNIZE_WORKFLOW_STEPS
  return BUILD_WORKFLOW_STEPS
}

export function getStepOrder(pillar?: string | null): readonly string[] {
  if (pillar === 'fix') return FIX_STEP_ORDER
  if (pillar === 'modernize') return MODERNIZE_STEP_ORDER
  return BUILD_STEP_ORDER
}
