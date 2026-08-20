'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import {
  ConfirmDialog,
  RelativeTime,
  ResourceErrorState,
  StatusBadge,
  type Column,
  type FilterDef,
} from '@/components/managed/shared'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedDelete, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { parseCredentialGroupResponse } from '@/lib/managed/credential-group-response-parsers'
import { toastOperationError } from '@/lib/managed/errors'
import { filterByCreatedTime, createCreatedTimeFilter, matchesSearch } from '@/lib/managed/filters'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import { toastError } from '@/lib/utils/toast'
import { parseCredentialGroupId } from '@/types/entity-id'
import type { CredentialGroup } from '@/types/managed'

import { CredentialIdentity } from './credential-identity'
import { CredentialListPanel } from './credential-list-panel'

interface CredentialGroupActionVariables {
  credentialGroup: CredentialGroup
  runId: number
  scope: string
  requestScope: ManagedRequestScope
}

export interface McpCredentialGroupListState {
  searchQuery: string
  createdFilter: string
  showArchived: boolean
  pageSize: number
}

const DEFAULT_MCP_LIST_STATE: McpCredentialGroupListState = {
  searchQuery: '',
  createdFilter: 'all',
  showArchived: false,
  pageSize: 10,
}

export function McpCredentialGroupList({
  onCreate,
  state,
  onStateChange,
}: {
  onCreate: () => void
  state?: McpCredentialGroupListState
  onStateChange?: (state: McpCredentialGroupListState) => void
}) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [localState, setLocalState] = useState(DEFAULT_MCP_LIST_STATE)
  const listState = state ?? localState
  const updateListState = (patch: Partial<McpCredentialGroupListState>) => {
    const next = { ...listState, ...patch }
    if (state && onStateChange) onStateChange(next)
    else setLocalState(next)
  }
  const { showArchived, searchQuery, createdFilter } = listState
  const setShowArchived = (value: boolean) => updateListState({ showArchived: value })
  const setSearchQuery = (value: string) => updateListState({ searchQuery: value })
  const setCreatedFilter = (value: string) => updateListState({ createdFilter: value })
  const [archiveTarget, setArchiveTarget] = useState<CredentialGroup | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<CredentialGroup | null>(null)
  const {
    scopeRef: managedScopeRef,
    scope: managedScope,
    readOnly,
    beginAction,
    isCurrentAction,
    scopeIsActive,
    bumpRun,
  } = useScopedActions({
    onReset: () => {
      setArchiveTarget(null)
      setDeleteTarget(null)
    },
  })

  const currentCredentialGroupIsActive = (_credentialGroup: CredentialGroup, scope: string) =>
    scopeIsActive(scope) && currentProjectAllowsWrite()

  const openArchiveDialog = (credentialGroup: CredentialGroup) => {
    if (!currentCredentialGroupIsActive(credentialGroup, managedScopeRef.current)) {
      toastError(t('managed.vaults.actionUnavailable'))
      return
    }
    bumpRun()
    setArchiveTarget(credentialGroup)
  }
  const closeArchiveDialog = () => {
    bumpRun()
    setArchiveTarget(null)
  }
  const openDeleteDialog = (credentialGroup: CredentialGroup) => {
    if (!currentCredentialGroupIsActive(credentialGroup, managedScopeRef.current)) {
      toastError(t('managed.vaults.actionUnavailable'))
      return
    }
    bumpRun()
    setDeleteTarget(credentialGroup)
  }
  const closeDeleteDialog = () => {
    bumpRun()
    setDeleteTarget(null)
  }

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
  } = usePaginatedList<CredentialGroup>({
    queryKey: 'credential-groups',
    path: '/credential-groups',
    includeArchived: showArchived,
    pageSize: listState.pageSize,
    onPageSizeChange: (pageSize) => updateListState({ pageSize }),
    parseItem: parseCredentialGroupResponse,
    parseCursor: parseCredentialGroupId,
  })

  const archiveMutation = useMutation({
    mutationFn: ({
      credentialGroup,
      runId,
      scope,
      requestScope,
    }: CredentialGroupActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale credential group archive ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project credential group archive ignored')
      }
      return managedPost(
        apiResourcePath('credential-groups', credentialGroup.id, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_d, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scope] })
      setArchiveTarget(null)
    },
    onError: (err, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })
  const deleteMutation = useMutation({
    mutationFn: ({
      credentialGroup,
      runId,
      scope,
      requestScope,
    }: CredentialGroupActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale credential group delete ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project credential group delete ignored')
      }
      return managedDelete(
        apiResourcePath('credential-groups', credentialGroup.id),
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_d, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['credential-groups', scope] })
      setDeleteTarget(null)
    },
    onError: (err, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, err, 'common.operationFailed')
    },
  })

  const credentialGroups = data.filter(
    (v) =>
      (showArchived || !v.archived_at) &&
      filterByCreatedTime(v.created_at, createdFilter) &&
      matchesSearch(searchQuery, [v.id, v.name, v.archived_at ? 'archived' : 'active']),
  )
  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t, ['7d', '30d', '90d']),
      value: createdFilter,
      onChange: (value) => {
        setCreatedFilter(value)
        goToPage(1)
      },
    },
  ]

  useEffect(() => {
    const activeById = new Map(data.filter((v) => !v.archived_at).map((v) => [v.id, v]))
    setArchiveTarget((target) => {
      if (!target) return null
      const current = activeById.get(target.id) ?? null
      if (!current) bumpRun()
      return current
    })
    setDeleteTarget((target) => {
      if (!target) return null
      const current = activeById.get(target.id) ?? null
      if (!current) bumpRun()
      return current
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const columns: Column<CredentialGroup>[] = [
    {
      key: 'identity',
      header: t('managed.credentials.tabs.mcp'),
      render: (v) => (
        <CredentialIdentity
          name={v.name}
          publicId={v.id}
          badges={v.archived_at ? <StatusBadge status="archived" /> : undefined}
        />
      ),
      width: '65%',
      truncate: false,
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (v) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={v.created_at} />
        </span>
      ),
    },
  ]

  if (isError)
    return (
      <ResourceErrorState
        error={error}
        resource="vault"
        onRetry={() =>
          queryClient.invalidateQueries({ queryKey: ['credential-groups', managedScope.key] })
        }
      />
    )

  return (
    <div>
      <CredentialListPanel
        searchPlaceholder={t('managed.credentials.searchMcpCredentialGroups')}
        searchValue={searchQuery}
        onSearchChange={(value) => {
          setSearchQuery(value)
          goToPage(1)
        }}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={(value) => {
          setShowArchived(value)
          goToPage(1)
        }}
        createAction={
          readOnly
            ? undefined
            : {
                label: t('managed.credentials.newMcpCredentialGroup'),
                onClick: () => {
                  if (!currentProjectAllowsWrite() || !scopeIsActive()) return
                  onCreate()
                },
              }
        }
        emptyState={{
          title: t('managed.credentials.emptyMcpTitle'),
          description: t('managed.credentials.emptyMcpDescription'),
        }}
        noResultsState={{
          title: t('managed.credentials.noMcpResultsTitle'),
          description: t('managed.credentials.noResultsDescription'),
        }}
        onClearFilters={() => {
          updateListState({ searchQuery: '', createdFilter: 'all', showArchived: false })
          goToPage(1)
        }}
        columns={columns}
        data={credentialGroups}
        loading={isLoading}
        fetching={isFetching}
        onRowClick={(v) => router.push(`/managed/credentials/mcp/${v.id}`)}
        actionMenu={(v) =>
          readOnly || v.archived_at
            ? []
            : [
                { label: t('managed.vaults.archiveVault'), onClick: () => openArchiveDialog(v) },
                {
                  label: t('common.delete'),
                  destructive: true,
                  icon: <Trash2 className="size-3.5" />,
                  onClick: () => openDeleteDialog(v),
                },
              ]
        }
        mobileCard={(v) => (
          <div className="flex flex-col gap-3">
            <CredentialIdentity
              name={v.name}
              publicId={v.id}
              badges={v.archived_at ? <StatusBadge status="archived" /> : undefined}
            />
            <div className="text-xs">
              <div className="text-muted-foreground">{t('managed.table.created')}</div>
              <div className="mt-1 text-foreground">
                <RelativeTime date={v.created_at} />
              </div>
            </div>
          </div>
        )}
        pagination={{
          hasNext,
          hasPrev,
          page,
          pageSize,
          pageSizeOptions,
          onNext: goNext,
          onPrev: goPrev,
          onPageChange: goToPage,
          onPageSizeChange: setPageSize,
        }}
      />
      <ConfirmDialog
        open={!readOnly && !!archiveTarget}
        title={t('managed.vaults.archiveTitle')}
        description={t('managed.vaults.archiveDescription', { name: archiveTarget?.name })}
        confirmLabel={t('common.archive')}
        destructive
        onConfirm={() => {
          if (!currentProjectAllowsWrite()) {
            closeArchiveDialog()
            return
          }
          if (archiveTarget) {
            if (!currentCredentialGroupIsActive(archiveTarget, managedScopeRef.current)) {
              closeArchiveDialog()
              return
            }
            const action = beginAction()
            if (!action) {
              closeArchiveDialog()
              return
            }
            archiveMutation.mutate({
              credentialGroup: archiveTarget,
              runId: action.runId,
              scope: action.scope,
              requestScope: action.requestScope,
            })
          }
        }}
        onCancel={closeArchiveDialog}
      />
      <ConfirmDialog
        open={!readOnly && !!deleteTarget}
        title={t('managed.vaults.deleteTitle')}
        description={t('managed.vaults.deleteDescription', { name: deleteTarget?.name })}
        confirmLabel={t('common.delete')}
        destructive
        onConfirm={() => {
          if (!currentProjectAllowsWrite()) {
            closeDeleteDialog()
            return
          }
          if (deleteTarget) {
            if (!currentCredentialGroupIsActive(deleteTarget, managedScopeRef.current)) {
              closeDeleteDialog()
              return
            }
            const action = beginAction()
            if (!action) {
              closeDeleteDialog()
              return
            }
            deleteMutation.mutate({
              credentialGroup: deleteTarget,
              runId: action.runId,
              scope: action.scope,
              requestScope: action.requestScope,
            })
          }
        }}
        onCancel={closeDeleteDialog}
      />
    </div>
  )
}
