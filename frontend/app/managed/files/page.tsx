'use client'

import { useRef, useState } from 'react'
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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function FileListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
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

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const formData = new FormData()
        formData.append('file', file)
        await managedUpload('/files', formData)
      }
      queryClient.invalidateQueries({ queryKey: ['files'] })
    } catch (err) {
      toastOperationError(t, err, 'common.operationFailed')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
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
            onClick: async () => {
              try {
                await managedDelete(`/files/${f.id}`)
                queryClient.invalidateQueries({ queryKey: ['files'] })
              } catch (e) {
                toastOperationError(t, e, 'common.operationFailed')
              }
            },
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
