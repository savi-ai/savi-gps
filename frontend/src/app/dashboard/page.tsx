'use client'

import { useAuth } from '@/contexts/AuthContext'
import { useRouter } from 'next/navigation'
import { useProjects } from '@/hooks/queries/useProjects'
import { usePortfolioSummary } from '@/hooks/queries/usePortfolio'
import { useNextActions } from '@/hooks/queries/useIntelligence'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Plus,
  Activity,
  CheckCircle2,
  TrendingUp,
  Wrench,
  FolderKanban,
  ArrowRight,
  GitBranch,
  RefreshCw,
  BarChart3,
  Search,
  AlertCircle,
  LayoutGrid,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface Project {
  id: string
  name: string
  current_step: string
  created_at: string
  updated_at: string
}

interface PortfolioSummary {
  repositories_total: number
  repositories_ready: number
  wiki_coverage_pct: number
  health_score: number
  top_language: string | null
  next_actions?: NextAction[]
}

interface NextAction {
  id: string
  priority: 'high' | 'medium' | 'low' | string
  title: string
  description: string
  href: string
  pillar: string
}

const ROLE_LABELS: Record<string, string> = {
  product_manager: 'Product Manager',
  architect: 'Architect',
  developer: 'Developer',
  qa: 'QA',
  admin: 'Administrator',
}

const ROLE_DESCRIPTIONS: Record<string, string> = {
  product_manager: 'Create projects, manage ideas, generate features and stories',
  architect: 'Design system architecture and drive ideas',
  developer: 'Implement code and run tests',
  qa: 'Test applications and ensure quality',
  admin: 'Full platform access and governance',
}

interface PillarCardProps {
  title: string
  description: string
  accentClass: string
  visible: boolean
  loading?: boolean
  children: React.ReactNode
}

function PillarCard({ title, description, accentClass, visible, loading, children }: PillarCardProps) {
  if (!visible) return null
  return (
    <Card className={cn('border-l-4 shadow-sm', accentClass)}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? <Skeleton className="h-9 w-32" /> : children}
      </CardContent>
    </Card>
  )
}

export default function DashboardPage() {
  const { user, hasPermission, hasCapability } = useAuth()
  const router = useRouter()

  const showPortfolio =
    hasCapability('portfolio') && hasPermission('can_view_portfolio')
  const showNextActions = hasCapability('intelligence') || hasCapability('modernize')

  const { data: projects = [], isLoading: loading } = useProjects()
  const { data: portfolioSummary = null, isLoading: portfolioLoading } = usePortfolioSummary(showPortfolio)
  const { data: nextActions = [] } = useNextActions(showNextActions)

  const stats = {
    active: projects.length,
    completed: projects.filter((p) => p.current_step === 'testing').length,
    inProgress: projects.filter((p) => p.current_step && p.current_step !== 'testing').length,
  }

  const recentProjects = projects.slice(0, 5).map((p) => ({
    id: p.id,
    name: p.name,
    step: p.current_step,
    updatedAt: new Date(p.updated_at).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }),
  }))

  const primaryRole = user?.roles[0] || ''

  const showPillarGrid =
    hasCapability('intelligence') ||
    hasCapability('build') ||
    hasCapability('modernize') ||
    hasCapability('portfolio')

  const showModernize =
    hasCapability('modernize') ||
    (hasCapability('build') && hasCapability('intelligence'))

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Welcome back, {user?.full_name || user?.username}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {user?.roles.map((r) => ROLE_LABELS[r] || r).join(' · ')}
          {primaryRole && ` — ${ROLE_DESCRIPTIONS[primaryRole]}`}
        </p>
      </div>

      {showPillarGrid && (
        <div>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Mission Control
          </h2>

          {nextActions.length > 0 && (
            <Card className="mb-4 border-l-4 border-amber-500 shadow-sm">
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <AlertCircle className="h-4 w-4 text-amber-600" />
                  Suggested next steps
                </CardTitle>
                <CardDescription>Cross-pillar actions to keep your estate moving</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {nextActions.map((action) => (
                  <button
                    key={action.id}
                    type="button"
                    onClick={() => router.push(action.href)}
                    className="flex w-full items-start justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2.5 text-left transition-colors hover:bg-muted/60"
                  >
                    <div>
                      <p className="text-sm font-medium">{action.title}</p>
                      <p className="text-xs text-muted-foreground">{action.description}</p>
                    </div>
                    <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  </button>
                ))}
              </CardContent>
            </Card>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <PillarCard
              title="Intelligence"
              description="Understand existing code — wiki, search, and chat"
              accentClass="pillar-accent-intelligence"
              visible={hasCapability('intelligence') && hasPermission('can_use_intelligence')}
            >
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => router.push('/dashboard/intelligence/applications')}>
                  <LayoutGrid className="h-4 w-4" />
                  View applications
                </Button>
                <Button size="sm" variant="outline" onClick={() => router.push('/dashboard/intelligence/repositories/new')}>
                  <GitBranch className="h-4 w-4" />
                  Connect repo
                </Button>
              </div>
            </PillarCard>

            <PillarCard
              title="Build"
              description="AI-guided delivery from idea to deployment"
              accentClass="pillar-accent-build"
              visible={hasCapability('build')}
            >
              {hasPermission('can_create_project') ? (
                <Button size="sm" onClick={() => router.push('/dashboard/projects/new')}>
                  <Plus className="h-4 w-4" />
                  New project
                </Button>
              ) : (
                <Button size="sm" variant="outline" onClick={() => router.push('/dashboard/projects')}>
                  <FolderKanban className="h-4 w-4" />
                  View projects
                </Button>
              )}
            </PillarCard>

            <PillarCard
              title="Modernize"
              description="Assess legacy systems and plan upgrades"
              accentClass="pillar-accent-modernize"
              visible={showModernize && hasPermission('can_manage_modernize')}
            >
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => router.push('/dashboard/modernize/assessments')}>
                  <RefreshCw className="h-4 w-4" />
                  Assessments
                </Button>
                <Button size="sm" variant="outline" onClick={() => router.push('/dashboard/modernize/plans')}>
                  Active plans
                </Button>
              </div>
            </PillarCard>

            <PillarCard
              title="Portfolio"
              description="Estate-wide health and wiki coverage"
              accentClass="pillar-accent-portfolio"
              visible={hasCapability('portfolio') && hasPermission('can_view_portfolio')}
              loading={portfolioLoading}
            >
              <div className="space-y-3">
                {portfolioSummary && (
                  <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <Badge variant="secondary">
                      {portfolioSummary.repositories_ready}/{portfolioSummary.repositories_total} repos ready
                    </Badge>
                    <Badge variant="outline">{portfolioSummary.wiki_coverage_pct}% wiki coverage</Badge>
                    {portfolioSummary.top_language && (
                      <Badge variant="outline">{portfolioSummary.top_language}</Badge>
                    )}
                    <Badge variant="outline">Health {portfolioSummary.health_score}</Badge>
                  </div>
                )}
                <Button size="sm" onClick={() => router.push('/dashboard/portfolio/health')}>
                  <BarChart3 className="h-4 w-4" />
                  View estate health
                </Button>
              </div>
            </PillarCard>
          </div>
        </div>
      )}

      {hasCapability('build') && (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: 'Active Projects', value: stats.active, icon: Activity, color: 'text-blue-600' },
          { label: 'Completed', value: stats.completed, icon: CheckCircle2, color: 'text-emerald-600' },
          { label: 'In Progress', value: stats.inProgress, icon: TrendingUp, color: 'text-violet-600' },
          { label: 'Workflow Stages', value: 6, icon: Wrench, color: 'text-amber-600' },
        ].map((stat) => (
          <Card key={stat.label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {stat.label}
              </CardTitle>
              <stat.icon className={`h-4 w-4 ${stat.color}`} />
            </CardHeader>
            <CardContent>
              {loading ? (
                <Skeleton className="h-8 w-16" />
              ) : (
                <div className="text-3xl font-bold">{stat.value}</div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      )}

      {hasCapability('build') && (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Recent Projects</CardTitle>
            <CardDescription>Your latest AI-guided delivery workflows</CardDescription>
          </div>
          {hasPermission('can_create_project') && (
            <Button size="sm" onClick={() => router.push('/dashboard/projects/new')}>
              <Plus className="h-4 w-4" />
              New Project
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : recentProjects.length > 0 ? (
            <div className="divide-y">
              {recentProjects.map((project) => (
                <button
                  key={project.id}
                  onClick={() => router.push(`/dashboard/projects/${project.id}`)}
                  className="flex w-full items-center justify-between py-3 text-left transition-colors hover:bg-muted/50 first:pt-0 last:pb-0"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10">
                      <FolderKanban className="h-4 w-4 text-primary" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">{project.name}</p>
                      <p className="text-xs text-muted-foreground">Updated {project.updatedAt}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="info" className="capitalize">
                      {project.step?.replace('_', ' ') || 'idea'}
                    </Badge>
                    <ArrowRight className="h-4 w-4 text-muted-foreground" />
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-muted">
                <FolderKanban className="h-7 w-7 text-muted-foreground" />
              </div>
              <h3 className="text-base font-semibold">No projects yet</h3>
              <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                Start your first AI-guided delivery workflow — from idea to deployed application.
              </p>
              {hasPermission('can_create_project') && (
                <Button className="mt-4" onClick={() => router.push('/dashboard/projects/new')}>
                  <Plus className="h-4 w-4" />
                  Create Project
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
      )}

      {hasCapability('intelligence') && !hasCapability('build') && (
        <Card className="border-dashed">
          <CardHeader>
            <CardTitle className="text-base">Get started with Intelligence</CardTitle>
            <CardDescription>
              Group repositories into applications, then explore wiki, search, and chat at product level.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => router.push('/dashboard/intelligence/applications')}>
              <LayoutGrid className="h-4 w-4" />
              View applications
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => router.push('/dashboard/intelligence/repositories/new')}
            >
              <Search className="h-4 w-4" />
              Connect a repository
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
