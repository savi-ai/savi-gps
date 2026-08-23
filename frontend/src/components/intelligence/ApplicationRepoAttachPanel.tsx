'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { GitBranch, Loader2, Plus, Trash2 } from 'lucide-react'

export const REPO_ATTACH_ROLES = [
  'unknown',
  'backend',
  'frontend',
  'api',
  'worker',
  'infra',
  'library',
  'other',
] as const

export interface RepoOption {
  id: string
  name: string
  github_full_name?: string
  status: string
  application?: { id: string; name: string } | null
}

export interface NewRepoRow {
  id: string
  name: string
  url: string
  default_branch: string
}

export interface RepoAttachPayload {
  selectedRepoIds: string[]
  newRepoRows: NewRepoRow[]
  role: string
  autoIndex: boolean
}

export function emptyRepoRow(): NewRepoRow {
  return {
    id: Math.random().toString(36).slice(2),
    name: '',
    url: '',
    default_branch: 'main',
  }
}

export async function attachRepositoriesToApplication(
  applicationId: string,
  payload: RepoAttachPayload
): Promise<{ attached: number; created: number }> {
  const { selectedRepoIds, newRepoRows, role, autoIndex } = payload
  let attached = 0
  let created = 0

  for (const repoId of selectedRepoIds) {
    await apiClient.post(`/api/v1/intelligence/applications/${applicationId}/repositories`, {
      repository_id: repoId,
      role,
    })
    attached += 1
  }

  for (const row of newRepoRows.filter((r) => r.url.trim())) {
    const repoRes = await apiClient.post('/api/v1/intelligence/repos', {
      name: row.name.trim() || row.url.trim(),
      url: row.url.trim(),
      default_branch: row.default_branch.trim() || 'main',
      provider: 'github',
      application_id: applicationId,
    })
    created += 1
    const newId = repoRes.data?.id as string | undefined
    if (newId && role) {
      await apiClient
        .post(`/api/v1/intelligence/applications/${applicationId}/repositories`, {
          repository_id: newId,
          role,
        })
        .catch(() => null)
    }
    if (autoIndex && newId) {
      await apiClient.post(`/api/v1/intelligence/repos/${newId}/index`).catch(() => null)
    }
  }

  return { attached, created }
}

function extractError(err: unknown): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
    if (detail) return detail
  }
  return 'Failed to attach repositories'
}

interface ApplicationRepoAttachPanelProps {
  /** Unassigned repos not already on this application */
  availableRepos: RepoOption[]
  /** When set, panel can submit attaches and links wizard to this app */
  applicationId?: string
  /** Standalone: own submit button. Embedded: fields only (e.g. create-application form). */
  variant?: 'standalone' | 'embedded'
  /** Called after successful attach in standalone mode */
  onAttached?: () => void
  /** Embedded mode: controlled state */
  value?: RepoAttachPayload
  onChange?: (value: RepoAttachPayload) => void
  disabled?: boolean
}

export default function ApplicationRepoAttachPanel({
  availableRepos,
  applicationId,
  variant = 'standalone',
  onAttached,
  value,
  onChange,
  disabled = false,
}: ApplicationRepoAttachPanelProps) {
  const [internal, setInternal] = useState<RepoAttachPayload>({
    selectedRepoIds: [],
    newRepoRows: [emptyRepoRow()],
    role: 'unknown',
    autoIndex: true,
  })
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const state = variant === 'embedded' && value ? value : internal
  const setState = (next: RepoAttachPayload) => {
    if (variant === 'embedded' && onChange) onChange(next)
    else setInternal(next)
  }

  const wizardHref = applicationId
    ? `/dashboard/intelligence/repositories/new?application_id=${applicationId}`
    : '/dashboard/intelligence/repositories/new'

  const hasSelection = useMemo(() => {
    const hasExisting = state.selectedRepoIds.length > 0
    const hasNew = state.newRepoRows.some((r) => r.url.trim())
    return hasExisting || hasNew
  }, [state])

  const toggleRepo = (id: string) => {
    setState({
      ...state,
      selectedRepoIds: state.selectedRepoIds.includes(id)
        ? state.selectedRepoIds.filter((x) => x !== id)
        : [...state.selectedRepoIds, id],
    })
  }

  const updateNewRow = (id: string, patch: Partial<NewRepoRow>) => {
    setState({
      ...state,
      newRepoRows: state.newRepoRows.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    })
  }

  const addNewRow = () => {
    setState({ ...state, newRepoRows: [...state.newRepoRows, emptyRepoRow()] })
  }

  const removeNewRow = (id: string) => {
    if (state.newRepoRows.length <= 1) return
    setState({ ...state, newRepoRows: state.newRepoRows.filter((r) => r.id !== id) })
  }

  const handleSubmit = async () => {
    if (!applicationId || !hasSelection) return
    setSubmitting(true)
    setLocalError(null)
    try {
      await attachRepositoriesToApplication(applicationId, state)
      setState({
        selectedRepoIds: [],
        newRepoRows: [emptyRepoRow()],
        role: state.role,
        autoIndex: state.autoIndex,
      })
      onAttached?.()
    } catch (err: unknown) {
      setLocalError(extractError(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6 rounded-md border bg-muted/20 p-4">
      <div>
        <p className="text-sm font-medium">Add repositories</p>
        <p className="text-xs text-muted-foreground">
          Select multiple existing repos and/or connect new GitHub URLs. You can always add more
          later.
        </p>
      </div>

      {localError && (
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {localError}
        </p>
      )}

      <div className="space-y-3">
        <Label>Existing repositories</Label>
        {availableRepos.length === 0 ? (
          <p className="rounded-md border border-dashed bg-background p-3 text-sm text-muted-foreground">
            No unassigned repositories in your tenant. Connect new ones below or use the{' '}
            <Link href={wizardHref} className="font-medium text-primary hover:underline">
              GitHub import wizard
            </Link>
            .
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              Select one or more repos not already in another application.
            </p>
            <ul className="max-h-52 space-y-2 overflow-y-auto rounded-md border bg-background p-3">
              {availableRepos.map((repo) => (
                <li key={repo.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    id={`attach-${repo.id}`}
                    checked={state.selectedRepoIds.includes(repo.id)}
                    onChange={() => toggleRepo(repo.id)}
                    disabled={disabled || submitting}
                    className="h-4 w-4"
                  />
                  <label
                    htmlFor={`attach-${repo.id}`}
                    className="flex flex-1 cursor-pointer items-center gap-2"
                  >
                    <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>{repo.github_full_name || repo.name}</span>
                    <span className="text-xs capitalize text-muted-foreground">{repo.status}</span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="space-y-3 border-t pt-4">
        <div className="flex items-center justify-between gap-2">
          <Label>Connect new repositories</Label>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addNewRow}
            disabled={disabled || submitting}
          >
            <Plus className="h-4 w-4" />
            Add row
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Creates the repository in Savi and attaches it to this application (
          <code className="text-xs">https://github.com/org/repo</code>).
        </p>
        <div className="space-y-3">
          {state.newRepoRows.map((row) => (
            <div
              key={row.id}
              className="grid gap-2 rounded-md border bg-background p-3 sm:grid-cols-12"
            >
              <div className="sm:col-span-3">
                <Label className="text-xs">Name</Label>
                <Input
                  value={row.name}
                  onChange={(e) => updateNewRow(row.id, { name: e.target.value })}
                  placeholder="repo-name"
                  className="mt-1"
                  disabled={disabled || submitting}
                />
              </div>
              <div className="sm:col-span-6">
                <Label className="text-xs">GitHub URL</Label>
                <Input
                  value={row.url}
                  onChange={(e) => updateNewRow(row.id, { url: e.target.value })}
                  placeholder="https://github.com/org/repo"
                  className="mt-1"
                  disabled={disabled || submitting}
                />
              </div>
              <div className="sm:col-span-2">
                <Label className="text-xs">Branch</Label>
                <Input
                  value={row.default_branch}
                  onChange={(e) => updateNewRow(row.id, { default_branch: e.target.value })}
                  placeholder="main"
                  className="mt-1"
                  disabled={disabled || submitting}
                />
              </div>
              <div className="flex items-end sm:col-span-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => removeNewRow(row.id)}
                  disabled={disabled || submitting || state.newRepoRows.length <= 1}
                  aria-label="Remove row"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-end">
        <div className="space-y-2 sm:w-[160px]">
          <Label htmlFor="attach-role">Default role</Label>
          <select
            id="attach-role"
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm capitalize"
            value={state.role}
            onChange={(e) => setState({ ...state, role: e.target.value })}
            disabled={disabled || submitting}
          >
            {REPO_ATTACH_ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </div>
        <label className="flex flex-1 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={state.autoIndex}
            onChange={(e) => setState({ ...state, autoIndex: e.target.checked })}
            disabled={disabled || submitting}
            className="h-4 w-4"
          />
          Start indexing newly connected repositories
        </label>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted-foreground">
          Import many from GitHub orgs?{' '}
          <Link href={wizardHref} className="text-primary hover:underline">
            Open connect wizard
          </Link>
        </p>
        {variant === 'standalone' && applicationId && (
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={disabled || submitting || !hasSelection}
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Add repositories
          </Button>
        )}
      </div>
    </div>
  )
}
