'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

import { CreateSecretDialog } from '@/app/managed/secrets/components/create-secret-dialog'
import { CreateVaultDialog } from '@/app/managed/vaults/components/create-vault-dialog'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCurrentProjectReadOnly } from '@/hooks/managed/use-current-project-read-only'
import { useTranslation } from '@/lib/i18n'
import { useManagedRequestScope } from '@/lib/managed/request-scope'

import { CredentialKindChooser, type CredentialKindChoice } from './credential-kind-chooser'
import { McpVaultList } from './mcp-vault-list'
import { ModelConnectionList } from './model-connection-list'
import { ServiceCredentialList } from './service-credential-list'

type CredentialTab = 'models' | 'services' | 'mcp'
const TABS: CredentialTab[] = ['models', 'services', 'mcp']
const KIND_TO_TAB: Record<CredentialKindChoice, CredentialTab> = { model: 'models', service: 'services', vault: 'mcp' }

function normalizeTab(raw: string | null): CredentialTab {
  return TABS.includes(raw as CredentialTab) ? (raw as CredentialTab) : 'models'
}

export function CredentialManagementShell() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()

  const rawTab = searchParams.get('tab')
  const tab = normalizeTab(rawTab)

  const [chooserOpen, setChooserOpen] = useState(false)
  const [secretDialog, setSecretDialog] = useState<{ open: boolean; kind: 'llm' | 'generic' }>({ open: false, kind: 'llm' })
  const [vaultDialogOpen, setVaultDialogOpen] = useState(false)

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
      goToTab(KIND_TO_TAB[kind])
      if (kind === 'model') setSecretDialog({ open: true, kind: 'llm' })
      else if (kind === 'service') setSecretDialog({ open: true, kind: 'generic' })
      else setVaultDialogOpen(true)
    },
    [goToTab],
  )

  // Consume create=* once: permission-gate, open the flow, normalize tab, strip create.
  useEffect(() => {
    const create = searchParams.get('create')
    if (!create) return
    const kind: CredentialKindChoice | null =
      create === 'model' ? 'model' : create === 'service' ? 'service' : create === 'vault' ? 'vault' : null
    const next = new URLSearchParams(searchParams.toString())
    next.delete('create')
    if (kind && !projectReadOnly) {
      next.set('tab', KIND_TO_TAB[kind])
      if (kind === 'model') setSecretDialog({ open: true, kind: 'llm' })
      else if (kind === 'service') setSecretDialog({ open: true, kind: 'generic' })
      else setVaultDialogOpen(true)
    }
    router.replace(`/managed/credentials?${next.toString()}`)
  }, [searchParams, router, projectReadOnly])

  const perTabAdd = useCallback(() => {
    openForKind(tab === 'models' ? 'model' : tab === 'services' ? 'service' : 'vault')
  }, [tab, openForKind])

  const onSecretCreated = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['credentials', managedScope.key] })
    if (secretDialog.kind === 'llm') queryClient.invalidateQueries({ queryKey: ['compatible-secrets', managedScope.key] })
    goToTab(secretDialog.kind === 'llm' ? 'models' : 'services')
    setSecretDialog((s) => ({ ...s, open: false }))
  }, [queryClient, managedScope.key, secretDialog.kind, goToTab])

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="overflow-x-auto">
          <Tabs value={tab} onValueChange={(v) => goToTab(v as CredentialTab)}>
            <TabsList>
              <TabsTrigger value="models">{t('managed.credentials.tabs.models')}</TabsTrigger>
              <TabsTrigger value="services">{t('managed.credentials.tabs.services')}</TabsTrigger>
              <TabsTrigger value="mcp">{t('managed.credentials.tabs.mcp')}</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
        {projectReadOnly ? null : (
          <Button size="sm" onClick={() => setChooserOpen(true)}>
            <Plus className="h-4 w-4" />
            {t('managed.credentials.new')}
          </Button>
        )}
      </div>

      {tab === 'models' ? <ModelConnectionList onCreate={perTabAdd} /> : null}
      {tab === 'services' ? <ServiceCredentialList onCreate={perTabAdd} /> : null}
      {tab === 'mcp' ? <McpVaultList onCreate={perTabAdd} /> : null}

      <CredentialKindChooser open={chooserOpen} onOpenChange={setChooserOpen} onChoose={openForKind} />

      <CreateSecretDialog
        open={secretDialog.open}
        initialKind={secretDialog.kind}
        lockKind
        onOpenChange={(open) => setSecretDialog((s) => ({ ...s, open }))}
        onCreated={onSecretCreated}
      />

      <CreateVaultDialog
        open={vaultDialogOpen}
        onOpenChange={setVaultDialogOpen}
        onCreated={(vault) => {
          setVaultDialogOpen(false)
          router.push(`/managed/credentials/mcp/${vault.id}?add=1`)
        }}
      />
    </div>
  )
}
