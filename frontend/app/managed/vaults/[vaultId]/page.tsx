'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Archive, Trash2 } from 'lucide-react'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import type { Vault, VaultCredential } from '@/types/managed'
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

export default function VaultDetailPage({ params }: { params: Promise<{ vaultId: string }> }) {
  const { vaultId: id } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
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

  const vaultId = stripIdPrefix(id || '')

  const {
    data: vault,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['vault', id],
    queryFn: () => managedGet<Vault>(`/vaults/${vaultId}`),
    enabled: !!id,
    retry: shouldRetryManagedResourceError,
  })

  const {
    data: credsRes,
    isLoading: credsLoading,
    isFetching: credsFetching,
  } = useQuery({
    queryKey: ['vault-credentials', id, showArchivedCredentials],
    queryFn: () =>
      managedGet<{ data: VaultCredential[]; has_more: boolean }>(
        `/vaults/${vaultId}/credentials?limit=100&include_archived=${showArchivedCredentials}`,
      ),
    enabled: !!id,
  })

  const credentials = (credsRes?.data || []).filter(
    (c) => showArchivedCredentials || !c.archived_at,
  )

  const archiveVaultMutation = useMutation({
    mutationFn: () => managedPost(`/vaults/${vaultId}/archive`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vault', id] })
      queryClient.invalidateQueries({ queryKey: ['vaults'] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteVaultMutation = useMutation({
    mutationFn: () => managedDelete(`/vaults/${vaultId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vaults'] })
      router.push('/managed/vaults')
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const archiveCredMutation = useMutation({
    mutationFn: (credId: string) =>
      managedPost(`/vaults/${vaultId}/credentials/${stripIdPrefix(credId)}/archive`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vault-credentials', id] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const handleArchiveVault = () => {
    setConfirmDialog({
      open: true,
      title: t('managed.vaults.archiveTitle'),
      description: t('managed.vaults.archiveDescription', { name: vault?.name }),
      confirmLabel: t('common.archive'),
      destructive: true,
      onConfirm: () => archiveVaultMutation.mutate(),
    })
  }

  const handleDeleteVault = () => {
    setConfirmDialog({
      open: true,
      title: t('managed.vaults.deleteTitle'),
      description: t('managed.vaults.deleteDescription', { name: vault?.name }),
      confirmLabel: t('common.delete'),
      destructive: true,
      onConfirm: () => deleteVaultMutation.mutate(),
    })
  }

  const handleArchiveCred = (cred: VaultCredential) => {
    setConfirmDialog({
      open: true,
      title: t('managed.vaults.credArchiveTitle'),
      description: t('managed.vaults.credArchiveDescription', { name: cred.name }),
      confirmLabel: t('common.archive'),
      destructive: true,
      onConfirm: () => archiveCredMutation.mutate(cred.id),
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
          !isArchived ? (
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
        {!isArchived && (
          <Button size="sm" onClick={() => setCreateCredOpen(true)}>
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
          c.archived_at
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
        open={createCredOpen}
        onOpenChange={setCreateCredOpen}
        vaultId={vaultId}
        queryKey={['vault-credentials', id]}
      />

      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.title}
        description={confirmDialog.description}
        confirmLabel={confirmDialog.confirmLabel}
        destructive={confirmDialog.destructive}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog((prev) => ({ ...prev, open: false }))}
      />
    </div>
  )
}
