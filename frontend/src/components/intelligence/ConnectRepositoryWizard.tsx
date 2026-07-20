'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  GitBranch,
  Key,
  Loader2,
  Search,
  User,
} from 'lucide-react'

const PERSONAL_KEY = '_personal'

type WizardStep = 'auth' | 'orgs' | 'repos' | 'manual' | 'review'

interface GitHubOrg {
  login: string
  description?: string
}

interface GitHubRepo {
  id?: number
  owner: string
  name: string
  full_name: string
  org: string
  default_branch: string
  html_url: string
  private?: boolean
  description?: string
}

interface OrgGroup {
  org: string
  org_display_name: string
  repos: GitHubRepo[]
  error?: string
}

interface SavedCredential {
  id: string
  label: string
  github_login: string
}

function repoKey(r: GitHubRepo) {
  return r.full_name || `${r.owner}/${r.name}`
}

export default function ConnectRepositoryWizard() {
  const router = useRouter()
  const [step, setStep] = useState<WizardStep>('auth')
  const [token, setToken] = useState('')
  const [credentialId, setCredentialId] = useState<string | null>(null)
  const [saveCredential, setSaveCredential] = useState(false)
  const [credentialLabel, setCredentialLabel] = useState('GitHub PAT')
  const [githubUser, setGithubUser] = useState<{ login: string; name?: string } | null>(null)
  const [orgs, setOrgs] = useState<GitHubOrg[]>([])
  const [savedCredentials, setSavedCredentials] = useState<SavedCredential[]>([])
  const [selectedOrgs, setSelectedOrgs] = useState<Set<string>>(new Set())
  const [includePersonal, setIncludePersonal] = useState(true)
  const [repoGroups, setRepoGroups] = useState<OrgGroup[]>([])
  const [selectedRepos, setSelectedRepos] = useState<Set<string>>(new Set())
  const [repoSearch, setRepoSearch] = useState('')
  const [autoIndex, setAutoIndex] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [applications, setApplications] = useState<{ id: string; name: string }[]>([])
  const [appGroupMode, setAppGroupMode] = useState<'none' | 'existing' | 'new'>('none')
  const [applicationId, setApplicationId] = useState('')
  const [applicationName, setApplicationName] = useState('')

  // Manual single-URL path
  const [manualForm, setManualForm] = useState({ name: '', url: '', default_branch: 'main' })

  useEffect(() => {
    apiClient
      .get('/api/v1/intelligence/github/credentials')
      .then((res) => setSavedCredentials(res.data?.credentials || []))
      .catch(() => setSavedCredentials([]))
  }, [])

  useEffect(() => {
    if (step !== 'review') return
    apiClient
      .get('/api/v1/intelligence/applications')
      .then((res) => setApplications(res.data?.applications || []))
      .catch(() => setApplications([]))
  }, [step])

  const authPayload = useCallback(() => {
    if (credentialId) return { credential_id: credentialId }
    return { token }
  }, [credentialId, token])

  const validateToken = async () => {
    if (credentialId) {
      await useSavedCredential(credentialId)
      return
    }
    if (token.length < 10) {
      setError('Enter a valid GitHub Personal Access Token')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v1/intelligence/github/validate-token', { token })
      setGithubUser(res.data.user)
      const orgList: GitHubOrg[] = res.data.orgs || []
      setOrgs(orgList)
      setSelectedOrgs(new Set(orgList.map((o) => o.login)))
      setStep('orgs')
    } catch (err: unknown) {
      setError(extractError(err))
    } finally {
      setLoading(false)
    }
  }

  const useSavedCredential = async (id: string) => {
    setCredentialId(id)
    setToken('')
    setLoading(true)
    setError(null)
    try {
      const orgRes = await apiClient.get(`/api/v1/intelligence/github/credentials/${id}/orgs`)
      setOrgs(orgRes.data.orgs || [])
      setGithubUser({
        login: savedCredentials.find((c) => c.id === id)?.github_login || 'GitHub',
      })
      setSelectedOrgs(new Set(orgRes.data.orgs?.map((o: GitHubOrg) => o.login) || []))
      setStep('orgs')
    } catch (err: unknown) {
      setError(extractError(err))
    } finally {
      setLoading(false)
    }
  }

  const discoverRepos = async () => {
    if (selectedOrgs.size === 0 && !includePersonal) {
      setError('Select at least one organization or include personal repositories')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v1/intelligence/github/discover', {
        ...authPayload(),
        orgs: Array.from(selectedOrgs),
        include_personal: includePersonal,
      })
      setRepoGroups(res.data.groups || [])
      setSelectedRepos(new Set())
      setStep('repos')
    } catch (err: unknown) {
      setError(extractError(err))
    } finally {
      setLoading(false)
    }
  }

  const filteredGroups = useMemo(() => {
    if (!repoSearch.trim()) return repoGroups
    const q = repoSearch.toLowerCase()
    return repoGroups
      .map((g) => ({
        ...g,
        repos: g.repos.filter(
          (r) =>
            r.full_name.toLowerCase().includes(q) ||
            (r.description || '').toLowerCase().includes(q)
        ),
      }))
      .filter((g) => g.repos.length > 0)
  }, [repoGroups, repoSearch])

  const selectedRepoObjects = useMemo(() => {
    const all: GitHubRepo[] = []
    for (const g of repoGroups) {
      for (const r of g.repos) {
        if (selectedRepos.has(repoKey(r))) all.push(r)
      }
    }
    return all
  }, [repoGroups, selectedRepos])

  const toggleOrgRepos = (group: OrgGroup, selectAll: boolean) => {
    setSelectedRepos((prev) => {
      const next = new Set(prev)
      for (const r of group.repos) {
        const key = repoKey(r)
        if (selectAll) next.add(key)
        else next.delete(key)
      }
      return next
    })
  }

  const importSelected = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v1/intelligence/github/import', {
        ...authPayload(),
        save_credential: saveCredential && !credentialId,
        credential_label: credentialLabel,
        credential_id: credentialId || undefined,
        auto_index: autoIndex,
        application_id: appGroupMode === 'existing' ? applicationId || undefined : undefined,
        application_name: appGroupMode === 'new' ? applicationName.trim() || undefined : undefined,
        repos: selectedRepoObjects.map((r) => ({
          owner: r.owner,
          name: r.name,
          full_name: r.full_name,
          org: r.org,
          default_branch: r.default_branch,
          html_url: r.html_url,
        })),
      })
      router.push(
        `/dashboard/intelligence/repositories?imported=${res.data.created_count || 0}`
      )
    } catch (err: unknown) {
      setError(extractError(err))
      setLoading(false)
    }
  }

  const connectManual = async () => {
    if (!manualForm.name.trim() || !manualForm.url.trim()) {
      setError('Name and URL are required')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.post('/api/v1/intelligence/repos', {
        name: manualForm.name.trim(),
        url: manualForm.url.trim(),
        default_branch: manualForm.default_branch.trim() || 'main',
        provider: 'github',
      })
      if (autoIndex) {
        await apiClient.post(`/api/v1/intelligence/repos/${res.data.id}/index`)
      }
      router.push(`/dashboard/intelligence/repositories/${res.data.id}?assign_app=1`)
    } catch (err: unknown) {
      setError(extractError(err))
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Connect GitHub Repositories</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Import one repo, many repos, or select from multiple organizations.
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex flex-wrap gap-2 text-xs">
        {(['auth', 'orgs', 'repos', 'review'] as const).map((s, i) => (
          <Badge
            key={s}
            variant={step === s || (step === 'manual' && s === 'auth') ? 'default' : 'secondary'}
            className="capitalize"
          >
            {i + 1}. {s === 'orgs' ? 'Organizations' : s}
          </Badge>
        ))}
      </div>

      {error && (
        <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      {step === 'auth' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Key className="h-4 w-4" />
              GitHub authentication
            </CardTitle>
            <CardDescription>
              Use a PAT with <code className="text-xs">repo</code> and{' '}
              <code className="text-xs">read:org</code> scopes for org discovery.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {savedCredentials.length > 0 && (
              <div className="space-y-2">
                <Label>Saved credentials</Label>
                <div className="flex flex-wrap gap-2">
                  {savedCredentials.map((c) => (
                    <Button
                      key={c.id}
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={loading}
                      onClick={() => useSavedCredential(c.id)}
                    >
                      {c.label} ({c.github_login})
                    </Button>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="github-token">Personal Access Token</Label>
              <Input
                id="github-token"
                type="password"
                value={token}
                onChange={(e) => {
                  setToken(e.target.value)
                  setCredentialId(null)
                }}
                placeholder="ghp_…"
                disabled={loading}
                autoComplete="off"
              />
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={saveCredential}
                onChange={(e) => setSaveCredential(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              Save token for this tenant (admin only)
            </label>
            {saveCredential && (
              <Input
                value={credentialLabel}
                onChange={(e) => setCredentialLabel(e.target.value)}
                placeholder="Credential label"
              />
            )}

            <div className="flex flex-wrap gap-2 pt-2">
              <Button onClick={validateToken} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                Continue with GitHub
              </Button>
              <Button type="button" variant="outline" onClick={() => setStep('manual')}>
                Manual URL instead
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => router.push('/dashboard/intelligence/repositories')}
              >
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 'manual' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Single repository URL</CardTitle>
            <CardDescription>Paste a GitHub URL without using the org browser.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                value={manualForm.name}
                onChange={(e) => setManualForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label>Repository URL</Label>
              <Input
                value={manualForm.url}
                onChange={(e) => setManualForm((f) => ({ ...f, url: e.target.value }))}
                placeholder="https://github.com/org/repo"
              />
            </div>
            <div className="space-y-2">
              <Label>Default branch</Label>
              <Input
                value={manualForm.default_branch}
                onChange={(e) => setManualForm((f) => ({ ...f, default_branch: e.target.value }))}
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoIndex}
                onChange={(e) => setAutoIndex(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              Start indexing immediately
            </label>
            <div className="flex gap-2">
              <Button onClick={connectManual} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Connect'}
              </Button>
              <Button variant="outline" onClick={() => setStep('auth')}>
                Back
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 'orgs' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Select organizations
              {githubUser && (
                <span className="ml-2 font-normal text-muted-foreground">
                  — {githubUser.login}
                </span>
              )}
            </CardTitle>
            <CardDescription>
              Choose one or more orgs. Repositories load per org so you can mix selections across
              orgs.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="flex items-center gap-2 rounded-md border p-3 text-sm">
              <input
                type="checkbox"
                checked={includePersonal}
                onChange={(e) => setIncludePersonal(e.target.checked)}
                className="h-4 w-4"
              />
              <User className="h-4 w-4 text-muted-foreground" />
              Include personal repositories
            </label>

            <div className="space-y-2">
              {orgs.length === 0 ? (
                <p className="text-sm text-muted-foreground">No organizations found for this token.</p>
              ) : (
                orgs.map((org) => (
                  <label
                    key={org.login}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors',
                      selectedOrgs.has(org.login) && 'border-primary bg-primary/5'
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={selectedOrgs.has(org.login)}
                      onChange={(e) => {
                        setSelectedOrgs((prev) => {
                          const next = new Set(prev)
                          if (e.target.checked) next.add(org.login)
                          else next.delete(org.login)
                          return next
                        })
                      }}
                      className="mt-1 h-4 w-4"
                    />
                    <div>
                      <div className="flex items-center gap-2 font-medium">
                        <Building2 className="h-4 w-4" />
                        {org.login}
                      </div>
                      {org.description && (
                        <p className="text-xs text-muted-foreground">{org.description}</p>
                      )}
                    </div>
                  </label>
                ))
              )}
            </div>

            <div className="flex gap-2">
              <Button onClick={discoverRepos} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Load repositories'}
              </Button>
              <Button variant="outline" onClick={() => setStep('auth')}>
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 'repos' && (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative max-w-sm flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Filter repositories…"
                value={repoSearch}
                onChange={(e) => setRepoSearch(e.target.value)}
              />
            </div>
            <Badge variant="secondary">{selectedRepos.size} selected</Badge>
          </div>

          {filteredGroups.map((group) => {
            const allSelected = group.repos.every((r) => selectedRepos.has(repoKey(r)))
            const someSelected = group.repos.some((r) => selectedRepos.has(repoKey(r)))
            return (
              <Card key={group.org}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-base">
                    {group.org === PERSONAL_KEY ? (
                      <span className="flex items-center gap-2">
                        <User className="h-4 w-4" /> Personal
                      </span>
                    ) : (
                      <span className="flex items-center gap-2">
                        <Building2 className="h-4 w-4" /> {group.org_display_name}
                      </span>
                    )}
                    <span className="ml-2 text-sm font-normal text-muted-foreground">
                      ({group.repos.length} repos)
                    </span>
                  </CardTitle>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => toggleOrgRepos(group, !allSelected)}
                    >
                      {allSelected ? 'Deselect all' : 'Select all'}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  {group.error && (
                    <p className="px-6 py-2 text-sm text-destructive">{group.error}</p>
                  )}
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-10" />
                        <TableHead>Repository</TableHead>
                        <TableHead>Branch</TableHead>
                        <TableHead className="hidden md:table-cell">Description</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {group.repos.map((repo) => {
                        const key = repoKey(repo)
                        const checked = selectedRepos.has(key)
                        return (
                          <TableRow
                            key={key}
                            className={cn(checked && 'bg-primary/5')}
                            onClick={() =>
                              setSelectedRepos((prev) => {
                                const next = new Set(prev)
                                if (checked) next.delete(key)
                                else next.add(key)
                                return next
                              })
                            }
                          >
                            <TableCell>
                              <input
                                type="checkbox"
                                checked={checked}
                                readOnly
                                className="h-4 w-4"
                              />
                            </TableCell>
                            <TableCell>
                              <div className="font-medium">{repo.full_name}</div>
                              {repo.private && (
                                <Badge variant="outline" className="mt-1 text-[10px]">
                                  private
                                </Badge>
                              )}
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {repo.default_branch}
                            </TableCell>
                            <TableCell className="hidden max-w-xs truncate text-muted-foreground md:table-cell">
                              {repo.description || '—'}
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            )
          })}

          <div className="flex flex-wrap gap-2">
            <Button
              disabled={selectedRepos.size === 0}
              onClick={() => setStep('review')}
            >
              Review {selectedRepos.size} repos
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button variant="outline" onClick={() => setStep('orgs')}>
              Change orgs
            </Button>
          </div>
        </div>
      )}

      {step === 'review' && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Review import</CardTitle>
            <CardDescription>
              {selectedRepoObjects.length} repositories will be connected
              {autoIndex ? ' and indexed' : ''}.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {selectedRepoObjects.map((r) => (
                <li key={repoKey(r)} className="flex items-center gap-2">
                  <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
                  {r.full_name}
                  <span className="text-muted-foreground">({r.org === PERSONAL_KEY ? 'personal' : r.org})</span>
                </li>
              ))}
            </ul>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoIndex}
                onChange={(e) => setAutoIndex(e.target.checked)}
                className="h-4 w-4"
              />
              Start indexing immediately after import
            </label>

            <div className="space-y-3 rounded-md border p-4">
              <p className="text-sm font-medium">Group as application (optional)</p>
              <div className="flex flex-wrap gap-3 text-sm">
                {(['none', 'existing', 'new'] as const).map((mode) => (
                  <label key={mode} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="appGroupMode"
                      checked={appGroupMode === mode}
                      onChange={() => setAppGroupMode(mode)}
                    />
                    {mode === 'none' && 'Skip'}
                    {mode === 'existing' && 'Existing application'}
                    {mode === 'new' && 'Create new application'}
                  </label>
                ))}
              </div>
              {appGroupMode === 'existing' && (
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={applicationId}
                  onChange={(e) => setApplicationId(e.target.value)}
                >
                  <option value="">Select application</option>
                  {applications.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              )}
              {appGroupMode === 'new' && (
                <Input
                  value={applicationName}
                  onChange={(e) => setApplicationName(e.target.value)}
                  placeholder="Application name, e.g. ITC Academy"
                />
              )}
            </div>

            <div className="flex gap-2">
              <Button onClick={importSelected} disabled={loading || selectedRepoObjects.length === 0}>
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
                Import repositories
              </Button>
              <Button variant="outline" onClick={() => setStep('repos')}>
                Back
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function extractError(err: unknown): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
    if (detail) return detail
  }
  return 'Request failed'
}
