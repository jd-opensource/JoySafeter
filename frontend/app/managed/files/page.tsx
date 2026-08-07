'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { Upload, Trash2 } from 'lucide-react'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { FileRecord } from '@/types/managed'
import { managedUpload, managedDelete } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { parseFileResponse } from '@/lib/managed/file-response-parsers'
import { apiResourcePath } from '@/lib/managed/api-paths'
import {
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { Button } from '@/components/ui/button'
import {
  PageHeader,
  FilterBar,
  type FilterDef,
  DataTable,
  type Column,
  MonoId,
  RelativeTime,
  ResourceErrorState,
} from '@/components/managed/shared'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function FileListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadRunRef = useRef(0)
  const actionRunRef = useRef(0)
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef(managedScope)
  const [uploading, setUploading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')

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
  } = usePaginatedList<FileRecord>({
    queryKey: 'files',
    path: '/files',
    parseItem: parseFileResponse,
  })

  const files = data.filter(
    (f) =>
      filterByCreatedTime(f.created_at, createdFilter) &&
      matchesSearch(searchQuery, [f.id, f.filename, f.content_type]),
  )

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]

  useEffect(() => {
    if (managedScopeRef.current !== managedScope.key) {
      uploadRunRef.current += 1
      actionRunRef.current += 1
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
  }, [managedScope.key])

  useEffect(
    () => () => {
      uploadRunRef.current += 1
      actionRunRef.current += 1
    },
    [],
  )

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const isCurrentUpload = (runId: number, scope: string) =>
    uploadRunRef.current === runId &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const getCurrentManagedScope = () => {
    const { currentOrgId, currentProjectId } = useProjectStore.getState()
    return managedScopeKey(currentOrgId, currentProjectId)
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    managedScopeRef.current === scope && getCurrentManagedScope() === scope

  useEffect(() => {
    if (!projectReadOnly) return
    uploadRunRef.current += 1
    actionRunRef.current += 1
    setUploading(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [projectReadOnly])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    if (!currentProjectAllowsWrite()) {
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    const runId = uploadRunRef.current + 1
    uploadRunRef.current = runId
    const uploadScope = managedScopeRef.current
    const requestScope = managedRequestScopeRef.current
    if (!currentManagedScopeIsActive(uploadScope)) {
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        if (!currentProjectAllowsWrite()) break
        if (!isCurrentUpload(runId, uploadScope)) break
        const formData = new FormData()
        formData.append('file', file)
        const response = await managedUpload<unknown>(
          '/files',
          formData,
          managedRequestOptions(requestScope),
        )
        parseFileResponse(response)
      }
      if (isCurrentUpload(runId, uploadScope)) {
        queryClient.invalidateQueries({ queryKey: ['files', uploadScope] })
      }
    } catch (err) {
      if (isCurrentUpload(runId, uploadScope)) {
        toastOperationError(t, err, 'common.operationFailed')
      }
    } finally {
      if (uploadRunRef.current === runId && currentManagedScopeIsActive(uploadScope)) {
        setUploading(false)
        if (fileInputRef.current) fileInputRef.current.value = ''
      }
    }
  }

  const columns: Column<FileRecord>[] = [
    {
      key: 'id',
      header: t('managed.table.id'),
      render: (f) => <MonoId id={f.id} />,
    },
    {
      key: 'filename',
      header: t('managed.table.name'),
      render: (f) => <span className="font-medium text-foreground">{f.filename}</span>,
    },
    {
      key: 'content_type',
      header: t('managed.table.type'),
      render: (f) => <span className="text-muted-foreground">{f.content_type}</span>,
    },
    {
      key: 'size',
      header: t('managed.files.size'),
      render: (f) => <span className="text-muted-foreground">{formatSize(f.size_bytes)}</span>,
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (f) => (
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={f.created_at} />
        </span>
      ),
    },
  ]

  const handleDelete = async (file: FileRecord) => {
    if (!currentProjectAllowsWrite()) return
    const actionScope = managedScopeRef.current
    const requestScope = managedRequestScopeRef.current
    if (!currentManagedScopeIsActive(actionScope)) return
    const fileStillCurrent = queryClient
      .getQueriesData<{ data?: FileRecord[] }>({ queryKey: ['files', actionScope, '/files'] })
      .some(([, page]) => page?.data?.some((currentFile) => currentFile.id === file.id))
    if (!fileStillCurrent) return

    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    if (!currentManagedScopeIsActive(actionScope)) return
    try {
      await managedDelete(apiResourcePath('files', file.id), managedRequestOptions(requestScope))
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['files', actionScope] })
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="file"
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['files', managedScope.key] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.files.title')}
        subtitle={t('managed.files.subtitle')}
        action={
          projectReadOnly ? null : (
            <>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={handleUpload}
              />
              <Button size="sm" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
                <Upload className="mr-1 h-4 w-4" />
                {uploading ? t('common.loading') : t('managed.files.upload')}
              </Button>
            </>
          )
        }
      />
      <FilterBar
        searchPlaceholder={t('managed.search.files')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
      />
      <DataTable
        columns={columns}
        data={files}
        loading={isLoading}
        fetching={isFetching}
        actionMenu={(f) =>
          projectReadOnly
            ? []
            : [
                {
                  label: t('common.delete'),
                  destructive: true,
                  onClick: () => handleDelete(f),
                },
              ]
        }
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
        emptyMessage={t('managed.files.empty')}
      />
    </div>
  )
}
