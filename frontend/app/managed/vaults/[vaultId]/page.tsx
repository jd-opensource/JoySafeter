'use client'

import React, { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Archive, Trash2 } from 'lucide-react'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import {
  parseVaultCredentialListResponse,
  parseVaultResponse,
} from '@/lib/managed/vault-response-parsers'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
  type ManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { Vault, VaultCredential } from '@/types/managed'
import { isEntityId, parseVaultId, type CredentialId, type VaultId } from '@/types/entity-id'
import { Button } from '@/components/ui/button'
import {
  PageHeader,
  ResourceErrorState,
  StatusBadge,
  MonoId,
  RelativeTime,
  DataTable,
  type Column,
  ConfirmDialog,
  FilterBar,
} from '@/components/managed/shared'
import { CreateCredentialDialog } from '../components/create-credential-dialog'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

interface VaultDetailActionVariables {
  vaultId: VaultId
  id: VaultId
  credId?: CredentialId
  runId: number
  scope: string
  scopeKey: string
  requestScope: ManagedRequestScope
}

export default function VaultDetailPage({ params }: { params: Promise<{ vaultId: string }> }) {
  const { vaultId: rawVaultId } = React.use(params)
  if (!isEntityId(rawVaultId, 'vault')) {
    return (
      <ResourceErrorState
        resource="vault"
        error={{ status: 404 }}
        onBack={() => window.history.back()}
      />
    )
  }
  return <VaultDetailPageInner params={params} />
}

function VaultDetailPageInner({ params }: { params: Promise<{ vaultId: string }> }) {
  const { vaultId: rawVaultId } = React.use(params)
  const vaultId = parseVaultId(rawVaultId)
  const id = vaultId
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const operationScope = `${managedScope.key}:${id ?? ''}`
  const actionRunRef = useRef(0)
  const operationScopeRef = useRef(operationScope)
  const managedRequestScopeRef = useRef(managedScope)
  const [showArchivedCredentials, setShowArchivedCredentials] = useState(false)
  const [createCredOpen, setCreateCredOpen] = useState(false)
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean
    title: string
    description: string
    confirmLabel: string
    destructive: boolean
    onConfirm: () => void
  }>({
    open: false,
    title: '',
    description: '',
    confirmLabel: '',
    destructive: false,
    onConfirm: () => {},
  })

  useEffect(() => {
    actionRunRef.current += 1
    operationScopeRef.current = operationScope
    managedRequestScopeRef.current = managedScope
    setCreateCredOpen(false)
    setConfirmDialog({
      open: false,
      title: '',
      description: '',
      confirmLabel: '',
      destructive: false,
      onConfirm: () => {},
    })
  }, [operationScope, managedScope])

  useEffect(
    () => () => {
      actionRunRef.current += 1
    },
    [],
  )

  const {
    data: vault,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['vault', managedScope.key, id],
    queryFn: () =>
      managedGet<unknown>(
        apiResourcePath('vaults', vaultId),
        managedRequestOptions(managedScope),
      ).then(parseVaultResponse),
    enabled: !!id && hasManagedRequestScope(managedScope),
    retry: shouldRetryManagedResourceError,
  })

  const {
    data: credsRes,
    isLoading: credsLoading,
    isFetching: credsFetching,
  } = useQuery({
    queryKey: ['vault-credentials', managedScope.key, id, showArchivedCredentials],
    queryFn: () =>
      managedGet<{ data: unknown[]; has_more: boolean }>(
        apiResourceSubpath('vaults', vaultId, ['credentials'], {
          limit: 100,
          include_archived: showArchivedCredentials,
        }),
        managedRequestOptions(managedScope),
      ).then((response) => ({
        ...response,
        data: parseVaultCredentialListResponse(response.data),
      })),
    enabled: !!id && hasManagedRequestScope(managedScope),
  })

  const credentials = (credsRes?.data || []).filter(
    (c) => showArchivedCredentials || !c.archived_at,
  )

  const getCurrentOperationScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${managedScopeKey(orgId, projectId)}:${id ?? ''}`
  }

  const currentOperationScopeIsActive = (scope = operationScopeRef.current) =>
    operationScopeRef.current === scope && getCurrentOperationScope() === scope

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId &&
    currentOperationScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const closeConfirmDialog = () => {
    actionRunRef.current += 1
    setConfirmDialog((prev) => ({ ...prev, open: false }))
  }

  const archiveVaultMutation = useMutation({
    mutationFn: ({ vaultId, requestScope, runId, scope }: VaultDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale vault detail archive ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project vault detail archive ignored')
      }
      return managedPost(
        apiResourcePath('vaults', vaultId, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { id, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['vault', scopeKey, id] })
      queryClient.invalidateQueries({ queryKey: ['vaults', scopeKey] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteVaultMutation = useMutation({
    mutationFn: ({ vaultId, requestScope, runId, scope }: VaultDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale vault detail delete ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project vault detail delete ignored')
      }
      return managedDelete(apiResourcePath('vaults', vaultId), managedRequestOptions(requestScope))
    },
    onSuccess: (_data, { runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['vaults', scopeKey] })
      router.push('/managed/vaults')
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const archiveCredMutation = useMutation({
    mutationFn: ({ vaultId, credId, requestScope, runId, scope }: VaultDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale vault credential archive ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project vault credential archive ignored')
      }
      return managedPost(
        apiResourcePath('vaults', vaultId, 'credentials', credId!, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { id, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['vault-credentials', scopeKey, id] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const actionVariables = (extra?: Pick<VaultDetailActionVariables, 'credId'>) => {
    if (!currentOperationScopeIsActive()) return null
    if (!currentProjectAllowsWrite()) return null
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    return {
      vaultId,
      id,
      runId,
      scope: operationScopeRef.current,
      scopeKey: managedRequestScopeRef.current.key,
      requestScope: managedRequestScopeRef.current,
      ...extra,
    }
  }

  const currentVaultIsActive = () => {
    if (!currentProjectAllowsWrite()) return false
    if (!currentOperationScopeIsActive()) return false
    const currentVault = queryClient.getQueryData<Vault>(['vault', managedScope.key, id])
    return !!currentVault && currentVault.id === vault?.id && !currentVault.archived_at
  }

  const findCurrentCredential = (credId: CredentialId) =>
    currentOperationScopeIsActive() &&
    currentProjectAllowsWrite() &&
    queryClient
      .getQueriesData<{ data?: VaultCredential[] }>({
        queryKey: ['vault-credentials', managedScope.key, id],
      })
      .some(([, page]) => page?.data?.some((credential) => credential.id === credId))

  const handleArchiveVault = () => {
    if (!currentVaultIsActive()) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.vaults.archiveTitle'),
      description: t('managed.vaults.archiveDescription', { name: vault?.name }),
      confirmLabel: t('common.archive'),
      destructive: true,
      onConfirm: () => {
        if (!currentVaultIsActive()) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables()
        if (action) archiveVaultMutation.mutate(action)
      },
    })
  }

  const handleDeleteVault = () => {
    if (!currentVaultIsActive()) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.vaults.deleteTitle'),
      description: t('managed.vaults.deleteDescription', { name: vault?.name }),
      confirmLabel: t('common.delete'),
      destructive: true,
      onConfirm: () => {
        if (!currentVaultIsActive()) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables()
        if (action) deleteVaultMutation.mutate(action)
      },
    })
  }

  const handleArchiveCred = (cred: VaultCredential) => {
    if (!currentVaultIsActive() || !findCurrentCredential(cred.id)) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.vaults.credArchiveTitle'),
      description: t('managed.vaults.credArchiveDescription', { name: cred.name }),
      confirmLabel: t('common.archive'),
      destructive: true,
      onConfirm: () => {
        if (!currentVaultIsActive() || !findCurrentCredential(cred.id)) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables({ credId: cred.id })
        if (action) archiveCredMutation.mutate(action)
      },
    })
  }

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="vault"
        backLabel={t('managed.vaults.backToVaults')}
        onBack={() => router.push('/managed/vaults')}
      />
    )
  }

  if (isLoading || !vault) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const isArchived = !!vault.archived_at
  const canWriteVault = !projectReadOnly && !isArchived

  function formatCredentialType(type: string): string {
    switch (type) {
      case 'static_bearer':
        return 'Bearer'
      case 'mcp_oauth':
        return 'OAuth'
      default:
        return type
    }
  }

  const credColumns: Column<VaultCredential>[] = [
    {
      key: 'id',
      header: t('managed.table.id'),
      render: (c) => <MonoId id={c.id} />,
    },
    {
      key: 'name',
      header: t('managed.table.name'),
      render: (c) => <span className="font-medium text-foreground">{c.name}</span>,
    },
    {
      key: 'type',
      header: t('managed.vaults.cred.type'),
      render: (c) => <span className="text-sm">{formatCredentialType(c.credential_type)}</span>,
    },
    {
      key: 'mcp_server_url',
      header: t('managed.vaults.cred.mcpServerUrl'),
      render: (c) => (
        <span className="block max-w-[300px] truncate font-mono text-sm text-muted-foreground">
          {c.mcp_server_url || '—'}
        </span>
      ),
    },
    {
      key: 'status',
      header: t('managed.table.status'),
      render: (c) => <StatusBadge status={c.archived_at ? 'archived' : 'active'} />,
    },
  ]

  return (
    <div>
      <PageHeader
        title={vault.name}
        titleExtra={<StatusBadge status={isArchived ? 'archived' : 'active'} />}
        breadcrumb={[
          { label: t('managed.vaults.title'), to: '/managed/vaults' },
          { label: vault.name },
        ]}
        action={
          canWriteVault ? (
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={handleArchiveVault}>
                <Archive className="mr-1.5 h-3.5 w-3.5" />
                {t('common.archive')}
              </Button>
              <Button variant="outline" size="sm" onClick={handleDeleteVault}>
                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                {t('common.delete')}
              </Button>
            </div>
          ) : null
        }
      />

      <div className="mb-6 flex items-center gap-1.5 text-sm text-muted-foreground">
        <MonoId id={vault.id} truncate={false} />
        <span>·</span>
        <RelativeTime date={vault.created_at} />
      </div>

      {/* Credentials section */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('managed.vaults.credentials')}</h2>
        {canWriteVault && (
          <Button
            size="sm"
            onClick={() => {
              if (!currentOperationScopeIsActive() || !currentProjectAllowsWrite()) return
              setCreateCredOpen(true)
            }}
          >
            <Plus className="h-4 w-4" />
            {t('managed.vaults.addCredential')}
          </Button>
        )}
      </div>

      <FilterBar
        showArchived={showArchivedCredentials}
        onArchivedChange={setShowArchivedCredentials}
      />

      <DataTable
        columns={credColumns}
        data={credentials}
        loading={credsLoading}
        fetching={credsFetching}
        actionMenu={(c) =>
          projectReadOnly || c.archived_at
            ? []
            : [
                {
                  label: t('managed.vaults.credArchiveTitle'),
                  onClick: () => handleArchiveCred(c),
                },
              ]
        }
        emptyMessage={t('managed.vaults.noCredentials')}
      />

      <CreateCredentialDialog
        open={canWriteVault && createCredOpen}
        onOpenChange={(open) => {
          if (open && (!currentOperationScopeIsActive() || !currentProjectAllowsWrite())) return
          setCreateCredOpen(open)
        }}
        vaultId={vaultId}
        queryKey={['vault-credentials', managedScope.key, id]}
        canSubmit={currentVaultIsActive}
      />

      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.title}
        description={confirmDialog.description}
        confirmLabel={confirmDialog.confirmLabel}
        destructive={confirmDialog.destructive}
        onConfirm={confirmDialog.onConfirm}
        onCancel={closeConfirmDialog}
      />
    </div>
  )
}
