'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { compatibleCredentialsScopePrefix } from '@/hooks/managed/use-compatible-credentials'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { useTranslation } from '@/lib/i18n'

import type { CredentialKindChoice } from './credential-kind-chooser'
import { CreateCredentialGroupDialog } from './create-credential-group-dialog'
import { CreateStandaloneCredentialDialog } from './create-standalone-credential-dialog'
import {
  McpCredentialGroupList,
  type McpCredentialGroupListState,
} from './mcp-credential-group-list'
import { ModelConnectionList, type ModelConnectionListState } from './model-connection-list'
import { ServiceCredentialList, type ServiceCredentialListState } from './service-credential-list'

type CredentialTab = 'models' | 'services' | 'mcp'
const TABS: CredentialTab[] = ['models', 'services', 'mcp']
const KIND_TO_TAB: Record<CredentialKindChoice, CredentialTab> = {
  model: 'models',
  service: 'services',
  'credential-group': 'mcp',
}

function normalizeTab(raw: string | null): CredentialTab {
  return TABS.includes(raw as CredentialTab) ? (raw as CredentialTab) : 'models'
}

function parseCreateKind(raw: string | null): CredentialKindChoice | null {
  if (raw === 'model' || raw === 'service' || raw === 'credential-group') return raw
  return null
}

export function CredentialManagementShell() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const {
    scope: managedScope,
    readOnly: projectReadOnly,
    scopeIsActive,
  } = useScopedActions({
    onReset: () => {
      setSecretDialog((state) => ({ ...state, open: false }))
      setCredentialGroupDialogOpen(false)
    },
  })

  const rawTab = searchParams.get('tab')
  const tab = normalizeTab(rawTab)
  const consumedCreateRequestRef = useRef<string | null>(null)

  const [secretDialog, setSecretDialog] = useState<{ open: boolean; kind: 'llm' | 'generic' }>({
    open: false,
    kind: 'llm',
  })
  const [credentialGroupDialogOpen, setCredentialGroupDialogOpen] = useState(false)
  const [modelListState, setModelListState] = useState<ModelConnectionListState>({
    searchQuery: '',
    createdFilter: 'all',
    showArchived: false,
    pageSize: 10,
  })
  const [serviceListState, setServiceListState] = useState<ServiceCredentialListState>({
    searchQuery: '',
    createdFilter: 'all',
    showArchived: false,
    pageSize: 10,
  })
  const [mcpListState, setMcpListState] = useState<McpCredentialGroupListState>({
    searchQuery: '',
    createdFilter: 'all',
    showArchived: false,
    pageSize: 10,
  })

  // Normalize illegal ?tab= to models (replace, no history).
  useEffect(() => {
    if (rawTab !== null && !TABS.includes(rawTab as CredentialTab)) {
      const next = new URLSearchParams(searchParams.toString())
      next.set('tab', 'models')
      router.replace(`/managed/credentials?${next.toString()}`)
    }
  }, [rawTab, router, searchParams])

  const goToTab = useCallback(
    (next: CredentialTab) => {
      if (next === tab) return
      const params = new URLSearchParams(searchParams.toString())
      params.set('tab', next)
      router.push(`/managed/credentials?${params.toString()}`)
    },
    [router, searchParams, tab],
  )

  const openForKind = useCallback(
    (kind: CredentialKindChoice) => {
      if (!scopeIsActive() || !currentProjectAllowsWrite()) {
        return
      }
      goToTab(KIND_TO_TAB[kind])
      if (kind === 'model') setSecretDialog({ open: true, kind: 'llm' })
      else if (kind === 'service') setSecretDialog({ open: true, kind: 'generic' })
      else setCredentialGroupDialogOpen(true)
    },
    [goToTab, scopeIsActive, setSecretDialog, setCredentialGroupDialogOpen],
  )

  // Consume create=* once: permission-gate, open the flow, normalize tab, strip create.
  useEffect(() => {
    const create = searchParams.get('create')
    if (!create) {
      consumedCreateRequestRef.current = null
      return
    }
    const createRequest = searchParams.toString()
    if (consumedCreateRequestRef.current === createRequest) return
    consumedCreateRequestRef.current = createRequest

    const kind = parseCreateKind(create)
    const next = new URLSearchParams(searchParams.toString())
    next.delete('create')
    if (kind && !projectReadOnly && currentProjectAllowsWrite()) {
      next.set('tab', KIND_TO_TAB[kind])
      if (kind === 'model') setSecretDialog({ open: true, kind: 'llm' })
      else if (kind === 'service') setSecretDialog({ open: true, kind: 'generic' })
      else setCredentialGroupDialogOpen(true)
    }
    router.replace(`/managed/credentials?${next.toString()}`)
  }, [searchParams, router, projectReadOnly])

  const perTabAdd = useCallback(() => {
    openForKind(tab === 'models' ? 'model' : tab === 'services' ? 'service' : 'credential-group')
  }, [tab, openForKind])

  const onSecretCreated = useCallback(() => {
    if (!scopeIsActive() || !currentProjectAllowsWrite()) return
    queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
    if (secretDialog.kind === 'llm')
      queryClient.invalidateQueries({
        queryKey: compatibleCredentialsScopePrefix(managedScope.key),
      })
    goToTab(secretDialog.kind === 'llm' ? 'models' : 'services')
    setSecretDialog((s) => ({ ...s, open: false }))
  }, [queryClient, managedScope.key, secretDialog.kind, goToTab, scopeIsActive, setSecretDialog])

  return (
    <div>
      <div className="mb-4 overflow-x-auto">
        <Tabs value={tab} onValueChange={(v) => goToTab(v as CredentialTab)}>
          <TabsList>
            <TabsTrigger value="models">{t('managed.credentials.tabs.models')}</TabsTrigger>
            <TabsTrigger value="services">{t('managed.credentials.tabs.services')}</TabsTrigger>
            <TabsTrigger value="mcp">{t('managed.credentials.tabs.mcp')}</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {tab === 'models' ? (
        <ModelConnectionList
          onCreate={perTabAdd}
          state={modelListState}
          onStateChange={setModelListState}
        />
      ) : null}
      {tab === 'services' ? (
        <ServiceCredentialList
          onCreate={perTabAdd}
          state={serviceListState}
          onStateChange={setServiceListState}
        />
      ) : null}
      {tab === 'mcp' ? (
        <McpCredentialGroupList
          onCreate={perTabAdd}
          state={mcpListState}
          onStateChange={setMcpListState}
        />
      ) : null}

      <CreateStandaloneCredentialDialog
        open={secretDialog.open}
        initialKind={secretDialog.kind}
        lockKind
        onOpenChange={(open) => {
          if (open && (!scopeIsActive() || !currentProjectAllowsWrite())) return
          setSecretDialog((state) => ({ ...state, open }))
        }}
        onCreated={onSecretCreated}
      />

      <CreateCredentialGroupDialog
        open={credentialGroupDialogOpen}
        onOpenChange={(open) => {
          if (open && (!scopeIsActive() || !currentProjectAllowsWrite())) return
          setCredentialGroupDialogOpen(open)
        }}
        onCreated={(credentialGroup) => {
          if (!scopeIsActive() || !currentProjectAllowsWrite()) return
          setCredentialGroupDialogOpen(false)
          router.push(`/managed/credentials/mcp/${credentialGroup.id}?add=1`)
        }}
      />
    </div>
  )
}
