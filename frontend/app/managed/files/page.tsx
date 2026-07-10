'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { Upload, Trash2 } from 'lucide-react'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { FileRecord } from '@/types/managed'
import { managedUpload, managedDelete } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function FileListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const currentOrgId = useProjectStore((state) => state.currentOrgId)
  const currentProjectId = useProjectStore((state) => state.currentProjectId)
  const managedScope = `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadRunRef = useRef(0)
  const actionRunRef = useRef(0)
  const managedScopeRef = useRef(managedScope)
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
  } = usePaginatedList<FileRecord>({ queryKey: 'files', path: '/files' })

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
    if (managedScopeRef.current !== managedScope) {
      uploadRunRef.current += 1
      actionRunRef.current += 1
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
    managedScopeRef.current = managedScope
  }, [managedScope])

  useEffect(
    () => () => {
      uploadRunRef.current += 1
      actionRunRef.current += 1
    },
    [],
  )

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId && currentManagedScopeIsActive(scope)

  const getCurrentManagedScope = () => {
    const { currentOrgId, currentProjectId } = useProjectStore.getState()
    return `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    managedScopeRef.current === scope && getCurrentManagedScope() === scope

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const runId = uploadRunRef.current + 1
    uploadRunRef.current = runId
    const uploadScope = managedScopeRef.current
    if (!currentManagedScopeIsActive(uploadScope)) {
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        if (uploadRunRef.current !== runId || !currentManagedScopeIsActive(uploadScope)) break
        const formData = new FormData()
        formData.append('file', file)
        await managedUpload('/files', formData)
      }
      if (uploadRunRef.current === runId && currentManagedScopeIsActive(uploadScope)) {
        queryClient.invalidateQueries({ queryKey: ['files'] })
      }
    } catch (err) {
      if (uploadRunRef.current === runId && currentManagedScopeIsActive(uploadScope)) {
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
    const actionScope = managedScopeRef.current
    if (!currentManagedScopeIsActive(actionScope)) return
    const fileStillCurrent = queryClient
      .getQueriesData<{ data?: FileRecord[] }>({ queryKey: ['files', actionScope, '/files'] })
      .some(([, page]) => page?.data?.some((currentFile) => currentFile.id === file.id))
    if (!fileStillCurrent) return

    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    if (!currentManagedScopeIsActive(actionScope)) return
    try {
      await managedDelete(`/files/${file.id}`)
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['files'] })
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
        onRetry={() => queryClient.invalidateQueries({ queryKey: ['files'] })}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.files.title')}
        subtitle={t('managed.files.subtitle')}
        action={
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
        actionMenu={(f) => [
          {
            label: t('common.delete'),
            destructive: true,
            onClick: () => handleDelete(f),
          },
        ]}
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
