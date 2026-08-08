/** Shared API types — grouped by pillar. Expand as OpenAPI codegen lands. */

export interface LinkedRepository {
  id: string
  name: string
  github_full_name?: string
  link_type?: string
}

export interface BuildProject {
  id: string
  name: string
  pillar?: string
  mode?: string | null
  description?: string
  business_value?: string
  domain?: string
  priority?: string
  target_audience?: string
  default_execution_mode?: string
  github_repo_url?: string
  conversation_history?: Array<{ role: string; content: string }>
  linked_repositories?: LinkedRepository[]
  source_application_id?: string | null
  target_application_id?: string | null
  source_application?: { id: string; name: string } | null
  target_application?: { id: string; name: string } | null
  source_plan_id?: string | null
  source_application_name?: string | null
  target_application_name?: string | null
  vision?: string
  features?: unknown
  architecture?: unknown
  stories?: unknown
  code_implementation?: unknown
  tests?: unknown
  current_step: string
  step_status?: string
  feature_generation_status?: string
  created_at: string
  updated_at: string
}

export interface ApplicationSummary {
  id: string
  name: string
  description?: string | null
  domain?: string | null
  origin?: string | null
  repository_count: number
}

export interface RepositorySummary {
  id: string
  name: string
  url: string
  provider: string
  github_full_name?: string
  status: string
  default_branch: string
  last_indexed_at: string | null
  application?: { id: string; name: string } | null
}

export interface ModernizationPlanSummary {
  id: string
  title: string
  state: string
  repository_id: string
  repository_name?: string
  spawned_project_id?: string | null
  updated_at?: string
}

export interface RepositoryConnectionsResponse {
  repository_id: string
  applications: Array<{ id: string; name: string; role?: string | null }>
  modernization_plans: Array<{
    id: string
    title: string
    state: string
    spawned_project_id?: string | null
  }>
  build_projects: Array<{
    id: string
    name: string
    current_step: string
    pillar: string
    source_plan_id?: string | null
    link_type?: string
  }>
}

export interface ContextPreviewResponse {
  repositories: Array<{
    id: string
    name: string
    status: string
    overview_excerpt?: string
    tech_stack_preview?: string
    wiki_page_count: number
    indexed_chunk_count: number
    symbol_count: number
    spec_count: number
  }>
  totals: { wiki_sections: number; symbols: number; specs: number }
  resolved_repository_ids?: string[]
}
