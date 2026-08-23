'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Archive, RotateCcw, Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useEffect, useRef, useState } from 'react'

import { CreateMcpMemberDialog } from './create-mcp-member-dialog'
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
import { Button } from '@/components/ui/button'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import {
  parseCredentialGroupCredentialListResponse,
  parseCredentialGroupResponse,
} from '@/lib/managed/credential-group-response-parsers'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
  type ManagedRequestScope,
} from '@/lib/managed/request-scope'
import { useProjectStore } from '@/stores/managed/project-store'
import type { CredentialId, CredentialGroupId } from '@/types/entity-id'
import type { CredentialGroup, CredentialGroupCredential } from '@/types/managed'

interface CredentialGroupDetailActionVariables {
  credentialGroupId: CredentialGroupId
  id: CredentialGroupId
  credId?: CredentialId
  runId: number
  scope: string
  scopeKey: string
  requestScope: ManagedRequestScope
}

export function McpCredentialGroupDetail({
  credentialGroupId,
  autoOpenAddCredential = false,
}: {
  credentialGroupId: CredentialGroupId
  autoOpenAddCredential?: boolean
}) {
  const id = credentialGroupId
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const operationScope = `${managedScope.key}:${id ?? ''}`
  const actionRunRef = useRef(0)
  const operationScopeInitializedRef = useRef(false)
  const operationScopeRef = useRef(operationScope)
  const managedRequestScopeRef = useRef(managedScope)
  const [showArchivedCredentials, setShowArchivedCredentials] = useState(false)
  const [createCredOpen, setCreateCredOpen] = useState(autoOpenAddCredential)
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

  managedRequestScopeRef.current = managedScope

  useEffect(() => {
    if (!operationScopeInitializedRef.current) {
      operationScopeInitializedRef.current = true
      return
    }
    actionRunRef.current += 1
    operationScopeRef.current = operationScope
    setCreateCredOpen(false)
    setConfirmDialog({
      open: false,
      title: '',
      description: '',
      confirmLabel: '',
      destructive: false,
      onConfirm: () => {},
    })
  }, [operationScope])

  useEffect(
    () => () => {
      actionRunRef.current += 1
    },
    [],
  )

  const {
    data: credentialGroup,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['credential-group', managedScope.key, id],
    queryFn: () =>
      managedGet<unknown>(
        apiResourcePath('credential-groups', credentialGroupId),
        managedRequestOptions(managedScope),
      ).then(parseCredentialGroupResponse),
    enabled: !!id && hasManagedRequestScope(managedScope),
    retry: shouldRetryManagedResourceError,
  })

  const {
    data: credsRes,
    isLoading: credsLoading,
    isFetching: credsFetching,
  } = useQuery({
    queryKey: ['credential-group-members', managedScope.key, id, showArchivedCredentials],
    queryFn: () =>
      managedGet<{ data: unknown[]; has_more: boolean }>(
        apiResourceSubpath('credential-groups', credentialGroupId, ['members'], {
          limit: 100,
          include_archived: showArchivedCredentials,
        }),
        managedRequestOptions(managedScope),
      ).then((response) => ({
        ...response,
        data: parseCredentialGroupCredentialListResponse(response.data),
      })),
    enabled: !!id && hasManagedRequestScope(managedScope),
  })

  useEffect(() => {
    if (!projectReadOnly && !credentialGroup?.archived_at) return
    actionRunRef.current += 1
    setCreateCredOpen(false)
    setConfirmDialog({
      open: false,
      title: '',
      description: '',
      confirmLabel: '',
      destructive: false,
      onConfirm: () => {},
    })
  }, [projectReadOnly, credentialGroup?.archived_at])

  const credentials = (credsRes?.data || []).filter(
    (c) => showArchivedCredentials || !c.archived_at,
  )
  const credentialsRef = useRef(credentials)
  credentialsRef.current = credentials

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

  const archiveCredentialGroupMutation = useMutation({
    mutationFn: ({
      credentialGroupId,
      requestScope,
      runId,
      scope,
    }: CredentialGroupDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale credential group detail archive ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project credential group detail archive ignored')
      }
      return managedPost(
        apiResourcePath('credential-groups', credentialGroupId, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { id, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-group', scopeKey, id] })
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scopeKey] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const restoreCredentialGroupMutation = useMutation({
    mutationFn: ({
      credentialGroupId,
      requestScope,
      runId,
      scope,
    }: CredentialGroupDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale credential group detail restore ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project credential group detail restore ignored')
      }
      return managedPost(
        apiResourcePath('credential-groups', credentialGroupId, 'restore'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { id, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-group', scopeKey, id] })
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scopeKey] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteCredentialGroupMutation = useMutation({
    mutationFn: ({
      credentialGroupId,
      requestScope,
      runId,
      scope,
    }: CredentialGroupDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale credential group detail delete ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project credential group detail delete ignored')
      }
      return managedDelete(
        apiResourcePath('credential-groups', credentialGroupId),
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scopeKey] })
      router.push('/managed/credentials?tab=mcp')
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const archiveCredMutation = useMutation({
    mutationFn: ({
      credentialGroupId,
      credId,
      requestScope,
      runId,
      scope,
    }: CredentialGroupDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale credential group member archive ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project credential group member archive ignored')
      }
      return managedPost(
        apiResourcePath('credential-groups', credentialGroupId, 'members', credId!, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { id, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-group-members', scopeKey, id] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const restoreCredMutation = useMutation({
    mutationFn: ({ credId, requestScope, runId, scope }: CredentialGroupDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale credential group member restore ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project credential group member restore ignored')
      }
      return managedPost(
        apiResourcePath('credentials', credId!, 'restore'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { id, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-group-members', scopeKey, id] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteCredMutation = useMutation({
    mutationFn: ({
      credentialGroupId,
      credId,
      requestScope,
      runId,
      scope,
    }: CredentialGroupDetailActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale credential group member delete ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project credential group member delete ignored')
      }
      return managedDelete(
        apiResourcePath('credential-groups', credentialGroupId, 'members', credId!),
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { id, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-group-members', scopeKey, id] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const actionVariables = (extra?: Pick<CredentialGroupDetailActionVariables, 'credId'>) => {
    if (!currentOperationScopeIsActive()) return null
    if (!currentProjectAllowsWrite()) return null
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    return {
      credentialGroupId,
      id,
      runId,
      scope: operationScopeRef.current,
      scopeKey: managedRequestScopeRef.current.key,
      requestScope: managedRequestScopeRef.current,
      ...extra,
    }
  }

  const currentCredentialGroupMatchesState = (archived: boolean) => {
    if (!currentProjectAllowsWrite()) return false
    if (!currentOperationScopeIsActive()) return false
    const currentCredentialGroup = queryClient.getQueryData<CredentialGroup>([
      'credential-group',
      managedScope.key,
      id,
    ])
    return (
      !!currentCredentialGroup &&
      currentCredentialGroup.id === credentialGroup?.id &&
      Boolean(currentCredentialGroup.archived_at) === archived
    )
  }

  const currentCredentialGroupExists = () => {
    if (!currentProjectAllowsWrite() || !currentOperationScopeIsActive()) return false
    const currentCredentialGroup = queryClient.getQueryData<CredentialGroup>([
      'credential-group',
      managedScope.key,
      id,
    ])
    return !!currentCredentialGroup && currentCredentialGroup.id === credentialGroup?.id
  }

  const currentCredentialMatchesState = (credId: CredentialId, archived: boolean) =>
    currentOperationScopeIsActive() &&
    currentProjectAllowsWrite() &&
    credentialsRef.current.some(
      (credential) => credential.id === credId && Boolean(credential.archived_at) === archived,
    )

  const currentCredentialExists = (credId: CredentialId) =>
    currentOperationScopeIsActive() &&
    currentProjectAllowsWrite() &&
    credentialsRef.current.some((credential) => credential.id === credId)

  const handleArchiveCredentialGroup = () => {
    if (!currentCredentialGroupMatchesState(false)) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.credentials.groups.archiveTitle'),
      description: t('managed.credentials.groups.archiveDescription', {
        name: credentialGroup?.name,
      }),
      confirmLabel: t('common.archive'),
      destructive: true,
      onConfirm: () => {
        if (!currentCredentialGroupMatchesState(false)) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables()
        if (action) archiveCredentialGroupMutation.mutate(action)
      },
    })
  }

  const handleRestoreCredentialGroup = () => {
    if (!currentCredentialGroupMatchesState(true)) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.credentials.groups.restoreTitle'),
      description: t('managed.credentials.groups.restoreDescription', {
        name: credentialGroup?.name,
      }),
      confirmLabel: t('common.restore'),
      destructive: false,
      onConfirm: () => {
        if (!currentCredentialGroupMatchesState(true)) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables()
        if (action) restoreCredentialGroupMutation.mutate(action)
      },
    })
  }

  const handleDeleteCredentialGroup = () => {
    if (!currentCredentialGroupExists()) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.credentials.groups.deleteTitle'),
      description: t('managed.credentials.groups.deleteDescription', {
        name: credentialGroup?.name,
      }),
      confirmLabel: t('common.delete'),
      destructive: true,
      onConfirm: () => {
        if (!currentCredentialGroupExists()) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables()
        if (action) deleteCredentialGroupMutation.mutate(action)
      },
    })
  }

  const handleArchiveCred = (cred: CredentialGroupCredential) => {
    if (
      !currentCredentialGroupMatchesState(false) ||
      !currentCredentialMatchesState(cred.id, false)
    )
      return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.credentials.groups.credArchiveTitle'),
      description: t('managed.credentials.groups.credArchiveDescription', { name: cred.name }),
      confirmLabel: t('common.archive'),
      destructive: true,
      onConfirm: () => {
        if (
          !currentCredentialGroupMatchesState(false) ||
          !currentCredentialMatchesState(cred.id, false)
        ) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables({ credId: cred.id })
        if (action) archiveCredMutation.mutate(action)
      },
    })
  }

  const handleRestoreCred = (cred: CredentialGroupCredential) => {
    if (!currentCredentialGroupMatchesState(false) || !currentCredentialMatchesState(cred.id, true))
      return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.credentials.groups.credRestoreTitle'),
      description: t('managed.credentials.groups.credRestoreDescription', { name: cred.name }),
      confirmLabel: t('common.restore'),
      destructive: false,
      onConfirm: () => {
        if (
          !currentCredentialGroupMatchesState(false) ||
          !currentCredentialMatchesState(cred.id, true)
        ) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables({ credId: cred.id })
        if (action) restoreCredMutation.mutate(action)
      },
    })
  }

  const handleDeleteCred = (cred: CredentialGroupCredential) => {
    if (!currentCredentialGroupMatchesState(false) || !currentCredentialExists(cred.id)) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.credentials.groups.credDeleteTitle'),
      description: t('managed.credentials.groups.credDeleteDescription', { name: cred.name }),
      confirmLabel: t('common.delete'),
      destructive: true,
      onConfirm: () => {
        if (!currentCredentialGroupMatchesState(false) || !currentCredentialExists(cred.id)) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables({ credId: cred.id })
        if (action) deleteCredMutation.mutate(action)
      },
    })
  }

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="vault"
        backLabel={t('managed.credentials.groups.backToCredentialGroups')}
        onBack={() => router.push('/managed/credentials?tab=mcp')}
      />
    )
  }

  if (isLoading || !credentialGroup) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const isArchived = !!credentialGroup.archived_at
  const canMutateCredentialGroup = !projectReadOnly
  const canWriteCredentialGroup = canMutateCredentialGroup && !isArchived

  const credColumns: Column<CredentialGroupCredential>[] = [
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
      header: t('managed.credentials.groups.members.type'),
      render: () => <span className="text-sm">Bearer</span>,
    },
    {
      key: 'mcp_server_url',
      header: t('managed.credentials.groups.members.mcpServerUrl'),
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
        title={credentialGroup.name}
        titleExtra={<StatusBadge status={isArchived ? 'archived' : 'active'} />}
        breadcrumb={[
          { label: t('managed.credentials.groups.title'), to: '/managed/credentials?tab=mcp' },
          { label: credentialGroup.name },
        ]}
        action={
          canMutateCredentialGroup ? (
            <div className="flex items-center gap-2">
              {isArchived ? (
                <Button variant="outline" size="sm" onClick={handleRestoreCredentialGroup}>
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                  {t('common.restore')}
                </Button>
              ) : (
                <Button variant="outline" size="sm" onClick={handleArchiveCredentialGroup}>
                  <Archive className="mr-1.5 h-3.5 w-3.5" />
                  {t('common.archive')}
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={handleDeleteCredentialGroup}>
                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                {t('common.delete')}
              </Button>
            </div>
          ) : null
        }
      />

      <div className="mb-6 flex items-center gap-1.5 text-sm text-muted-foreground">
        <MonoId id={credentialGroup.id} truncate={false} />
        <span>·</span>
        <RelativeTime date={credentialGroup.created_at} />
      </div>

      {/* Credentials section */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('managed.credentials.groups.credentials')}</h2>
        {canWriteCredentialGroup && (
          <Button
            size="sm"
            onClick={() => {
              if (!currentOperationScopeIsActive() || !currentProjectAllowsWrite()) return
              setCreateCredOpen(true)
            }}
          >
            <Plus className="h-4 w-4" />
            {t('managed.credentials.groups.addCredential')}
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
          !canWriteCredentialGroup
            ? []
            : [
                c.archived_at
                  ? {
                      label: t('common.restore'),
                      onClick: () => handleRestoreCred(c),
                    }
                  : {
                      label: t('managed.credentials.groups.credArchiveTitle'),
                      onClick: () => handleArchiveCred(c),
                    },
                {
                  label: t('common.delete'),
                  destructive: true,
                  onClick: () => handleDeleteCred(c),
                },
              ]
        }
        emptyMessage={t('managed.credentials.groups.noCredentials')}
      />

      {canWriteCredentialGroup && createCredOpen ? (
        <CreateMcpMemberDialog
          key={`${managedScope.key}:${credentialGroupId}`}
          open
          onOpenChange={(open) => {
            if (open && (!currentOperationScopeIsActive() || !currentProjectAllowsWrite())) return
            setCreateCredOpen(open)
          }}
          credentialGroupId={credentialGroupId}
          queryKey={['credential-group-members', managedScope.key, id]}
          canSubmit={() => currentCredentialGroupMatchesState(false)}
        />
      ) : null}

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
