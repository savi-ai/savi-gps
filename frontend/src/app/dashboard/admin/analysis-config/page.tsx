'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import apiClient from '@/lib/axios'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Settings2, Search, Plus } from 'lucide-react'

interface AttributeDefinition {
  id: string
  key: string
  label: string
  category: string
  data_type: string
  extraction_hint?: string
  is_active: boolean
}

interface SearchResult {
  repository_name: string
  repository_full_name?: string
  attribute_key: string
  attribute_label: string
  value_text: string
  source_file?: string
  confidence: string
}

export default function AdminAnalysisConfigPage() {
  const router = useRouter()
  const { hasPermission } = useAuth()
  const [definitions, setDefinitions] = useState<AttributeDefinition[]>([])
  const [searchKey, setSearchKey] = useState('')
  const [searchValue, setSearchValue] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(true)
  const [newKey, setNewKey] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newHint, setNewHint] = useState('')

  const isAdmin = hasPermission('can_manage_tenant_config')

  const loadDefinitions = useCallback(async () => {
    const res = await apiClient.get('/api/v1/intelligence/analysis-config/definitions')
    setDefinitions(res.data?.definitions || [])
  }, [])

  useEffect(() => {
    if (!isAdmin) {
      router.push('/dashboard')
      return
    }
    loadDefinitions().finally(() => setLoading(false))
  }, [isAdmin, router, loadDefinitions])

  const runSearch = async () => {
    const res = await apiClient.get('/api/v1/intelligence/analysis-config/search', {
      params: {
        attribute_key: searchKey || undefined,
        value_contains: searchValue || undefined,
      },
    })
    setResults(res.data?.results || [])
  }

  const addAttribute = async () => {
    if (!newKey || !newLabel) return
    await apiClient.post('/api/v1/intelligence/analysis-config/definitions', {
      key: newKey,
      label: newLabel,
      extraction_hint: newHint || undefined,
      category: 'general',
    })
    setNewKey('')
    setNewLabel('')
    setNewHint('')
    await loadDefinitions()
  }

  const seedDefaults = async () => {
    await apiClient.post('/api/v1/intelligence/analysis-config/definitions/seed-defaults')
    await loadDefinitions()
  }

  if (loading) return <Skeleton className="h-48 w-full" />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Settings2 className="h-6 w-6" />
          Analysis Configuration
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Define what the Wiki Agent extracts from each repository. Values are stored per index run
          and searchable across your estate.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Attribute definitions</CardTitle>
          <CardDescription>
            Wiki Agent uses these during indexing — e.g. golden image, Java version, framework.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={seedDefaults}>
              Seed defaults
            </Button>
          </div>
          <ul className="divide-y rounded-lg border">
            {definitions.map((d) => (
              <li
                key={d.id}
                className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <span className="font-medium">{d.label}</span>
                  <code className="ml-2 text-xs text-muted-foreground">{d.key}</code>
                </div>
                <div className="flex gap-2">
                  <Badge variant="outline">{d.category}</Badge>
                  {!d.is_active && <Badge variant="secondary">inactive</Badge>}
                </div>
              </li>
            ))}
          </ul>
          <div className="grid gap-3 rounded-lg border bg-muted/20 p-4 sm:grid-cols-3">
            <div>
              <Label htmlFor="newKey">Key</Label>
              <Input
                id="newKey"
                placeholder="java_version"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="newLabel">Label</Label>
              <Input
                id="newLabel"
                placeholder="Java Version"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="newHint">Extraction hint</Label>
              <Input
                id="newHint"
                placeholder="FROM line in Dockerfile"
                value={newHint}
                onChange={(e) => setNewHint(e.target.value)}
              />
            </div>
            <Button className="w-fit sm:col-span-3" onClick={addAttribute}>
              <Plus className="h-4 w-4" />
              Add attribute
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Search className="h-4 w-4" />
            Fleet search
          </CardTitle>
          <CardDescription>Find repositories by extracted attribute values.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Input
              placeholder="Attribute key (e.g. java_version)"
              value={searchKey}
              onChange={(e) => setSearchKey(e.target.value)}
              className="max-w-xs"
            />
            <Input
              placeholder="Value contains…"
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              className="max-w-xs"
            />
            <Button onClick={runSearch}>Search</Button>
          </div>
          {results.length > 0 && (
            <ul className="divide-y rounded-lg border text-sm">
              {results.map((r, i) => (
                <li key={i} className="px-4 py-3">
                  <div className="font-medium">{r.repository_full_name || r.repository_name}</div>
                  <div className="text-muted-foreground">
                    {r.attribute_label}: <strong>{r.value_text}</strong>
                    {r.source_file && (
                      <>
                        {' '}
                        — <code>{r.source_file}</code>
                      </>
                    )}
                    <Badge variant="outline" className="ml-2">
                      {r.confidence}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
