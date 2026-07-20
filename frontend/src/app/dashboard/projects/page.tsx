'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { useProjects } from '@/hooks/queries/useProjects'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Plus, FolderKanban, ExternalLink } from 'lucide-react'

const PILLAR_LABELS: Record<string, string> = {
  build: 'Build',
  modernize: 'Modernize',
}

const STEP_LABELS: Record<string, string> = {
  idea: 'Idea',
  features: 'Requirements',
  architecture: 'Architecture',
  stories: 'Stories',
  developer: 'Implementation',
  testing: 'Testing',
}

const STEP_ORDER = ['idea', 'features', 'architecture', 'stories', 'developer', 'testing']

function getStepProgress(step: string): number {
  const idx = STEP_ORDER.indexOf(step)
  return idx >= 0 ? Math.round(((idx + 1) / STEP_ORDER.length) * 100) : 0
}

export default function ProjectsPage() {
  const router = useRouter()
  const { hasPermission } = useAuth()
  const [pillarFilter, setPillarFilter] = useState<'all' | 'build' | 'modernize'>('all')
  const { data: projects = [], isLoading: loading, error: queryError } = useProjects(
    pillarFilter === 'all' ? undefined : pillarFilter
  )
  const error = queryError ? (queryError as Error).message : null

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Projects</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage and track your AI-guided delivery workflows
          </p>
        </div>
        {hasPermission('can_create_project') && (
          <Button onClick={() => router.push('/dashboard/projects/new')}>
            <Plus className="h-4 w-4" />
            Create Project
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>All Projects</CardTitle>
              <CardDescription>
                {loading ? 'Loading...' : `${projects.length} project${projects.length !== 1 ? 's' : ''}`}
              </CardDescription>
            </div>
            <select
              value={pillarFilter}
              onChange={(e) => setPillarFilter(e.target.value as 'all' | 'build' | 'modernize')}
              className="h-9 rounded-md border bg-background px-3 text-sm"
              disabled={loading}
            >
              <option value="all">All pillars</option>
              <option value="build">Build</option>
              <option value="modernize">Modernize</option>
            </select>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : error ? (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
              {error}
            </div>
          ) : projects.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-muted">
                <FolderKanban className="h-7 w-7 text-muted-foreground" />
              </div>
              <h3 className="text-base font-semibold">No projects yet</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Create your first project to begin the Build workflow.
              </p>
              {hasPermission('can_create_project') && (
                <Button className="mt-4" onClick={() => router.push('/dashboard/projects/new')}>
                  <Plus className="h-4 w-4" />
                  Create Project
                </Button>
              )}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Project Name</TableHead>
                  <TableHead>Pillar</TableHead>
                  <TableHead>Current Step</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Last Updated</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {projects.map((project) => {
                  const progress = getStepProgress(project.current_step)
                  return (
                    <TableRow
                      key={project.id}
                      className="cursor-pointer"
                      onClick={() => router.push(`/dashboard/projects/${project.id}`)}
                    >
                      <TableCell className="font-medium">
                        <div>{project.name}</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {project.source_application_name && (
                            <span className="text-xs text-muted-foreground">
                              {project.source_application_name}
                            </span>
                          )}
                          {project.source_plan_id && (
                            <Badge variant="secondary" className="text-xs">
                              From modernization plan
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={project.pillar === 'modernize' ? 'secondary' : 'outline'}>
                          {PILLAR_LABELS[project.pillar || 'build'] || project.pillar || 'Build'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="info">
                          {STEP_LABELS[project.current_step] || project.current_step}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full rounded-full bg-primary transition-all"
                              style={{ width: `${progress}%` }}
                            />
                          </div>
                          <span className="text-xs text-muted-foreground">{progress}%</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {new Date(project.updated_at).toLocaleDateString('en-US', {
                          month: 'short',
                          day: 'numeric',
                          year: 'numeric',
                        })}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            router.push(`/dashboard/projects/${project.id}`)
                          }}
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
