'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Archive, Trash2 } from 'lucide-react'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import type { MemoryStore } from '@/types/managed'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  PageHeader,
  StatusBadge,
  MonoId,
  RelativeTime,
  DataTable,
  type Column,
  ConfirmDialog,
  ResourceErrorState,
} from '@/components/managed/shared'

interface Memory {
  id: string
  path: string
  content: string
  content_size_bytes: number
  version?: number
  memory_version_id?: string
  metadata: Record<string, string>
  created_at: string
  updated_at: string
}

export default function MemoryStoreDetailPage({
  params,
}: {
  params: Promise<{ storeId: string }>
}) {
  const { storeId: rawId } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [createMemOpen, setCreateMemOpen] = useState(false)
  const [newMemPath, setNewMemPath] = useState('')
  const [newMemContent, setNewMemContent] = useState('')
  const [createMemLoading, setCreateMemLoading] = useState(false)
  const [editMem, setEditMem] = useState<Memory | null>(null)
  const [editContent, setEditContent] = useState('')
  const [editLoading, setEditLoading] = useState(false)
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean
    title: string
    description: string
    confirmLabel: string
    destructive: boolean
    onConfirm: () => void
  }>({ open: false, title: '', description: '', confirmLabel: '', destructive: false, onConfirm: () => {} })

  const storeId = stripIdPrefix(rawId || '')

  const { data: store, isLoading, isError, error } = useQuery({
    queryKey: ['memory-store', rawId],
    queryFn: () => managedGet<MemoryStore>(`/memory_stores/${storeId}`),
    enabled: !!rawId,
    retry: shouldRetryManagedResourceError,
  })

  const { data: memoriesRes, isLoading: memLoading, isFetching: memFetching } = useQuery({
    queryKey: ['memory-store-memories', rawId],
    queryFn: () => managedGet<Memory[]>(`/memory_stores/${storeId}/memories?limit=100&view=full`),
    enabled: !!rawId,
  })

  const memories = Array.isArray(memoriesRes) ? memoriesRes : (memoriesRes as any)?.data || []

  const archiveMutation = useMutation({
    mutationFn: () => managedPost(`/memory_stores/${storeId}/archive`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memory-store', rawId] })
      queryClient.invalidateQueries({ queryKey: ['memory-stores'] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => managedDelete(`/memory_stores/${storeId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memory-stores'] })
      router.push('/managed/memory-stores')
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMemoryMutation = useMutation({
    mutationFn: (memId: string) => managedDelete(`/memory_stores/${storeId}/memories/${stripIdPrefix(memId)}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memory-store-memories', rawId] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const handleArchive = () => {
    setConfirmDialog({
      open: true,
      title: t('managed.memoryStores.archiveStore'),
      description: t('managed.memoryStores.archiveDescription', { name: store?.name }),
      confirmLabel: t('common.archive'),
      destructive: true,
      onConfirm: () => archiveMutation.mutate(),
    })
  }

  const handleDelete = () => {
    setConfirmDialog({
      open: true,
      title: t('managed.memoryStores.deleteStore'),
      description: t('managed.memoryStores.deleteDescription', { name: store?.name }),
      confirmLabel: t('common.delete'),
      destructive: true,
      onConfirm: () => deleteMutation.mutate(),
    })
  }

  const handleDeleteMemory = (mem: Memory) => {
    setTimeout(() => {
      setConfirmDialog({
        open: true,
        title: t('managed.memoryStores.deleteMemory'),
        description: t('managed.memoryStores.deleteMemoryDescription', { path: mem.path }),
        confirmLabel: t('common.delete'),
        destructive: true,
        onConfirm: () => deleteMemoryMutation.mutate(mem.id),
      })
    }, 0)
  }

  const handleCreateMemory = async () => {
    if (!newMemPath.trim() || !newMemContent.trim()) return
    setCreateMemLoading(true)
    try {
      await managedPost(`/memory_stores/${storeId}/memories`, {
        path: newMemPath.trim(),
        content: newMemContent.trim(),
      })
      setNewMemPath('')
      setNewMemContent('')
      setCreateMemOpen(false)
      queryClient.invalidateQueries({ queryKey: ['memory-store-memories', rawId] })
    } catch (error) {
      toastOperationError(t, error, 'managed.memoryStores.saveFailed')
    } finally {
      setCreateMemLoading(false)
    }
  }

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="memoryStore"
        onBack={() => router.push('/managed/memory-stores')}
      />
    )
  }

  if (isLoading || !store) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const isArchived = !!store.archived_at

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const handleEditMemory = (mem: Memory) => {
    setEditMem(mem)
    setEditContent(mem.content || '')
  }

  const handleSaveMemory = async () => {
    if (!editMem || !editContent.trim()) return
    setEditLoading(true)
    try {
      await managedPost(`/memory_stores/${storeId}/memories/${stripIdPrefix(editMem.id)}`, {
        content: editContent,
      })
      setEditMem(null)
      queryClient.invalidateQueries({ queryKey: ['memory-store-memories', rawId] })
    } catch (error) {
      toastOperationError(t, error, 'managed.memoryStores.saveFailed')
    } finally {
      setEditLoading(false)
    }
  }

  const memColumns: Column<Memory>[] = [
    {
      key: 'path',
      header: t('managed.memoryStores.memPath'),
      render: (m) => <span className="font-mono text-sm">{m.path}</span>,
    },
    {
      key: 'version',
      header: t('managed.memoryStores.memVersion'),
      render: (m) => (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-muted text-foreground">
          v{m.version || 1}
        </span>
      ),
    },
    {
      key: 'size',
      header: t('managed.memoryStores.memSize'),
      render: (m) => <span className="text-sm text-muted-foreground">{formatSize(m.content_size_bytes)}</span>,
    },
    {
      key: 'updated_at',
      header: t('managed.memoryStores.memUpdated'),
      render: (m) => (
        <span className="text-sm text-muted-foreground">
          <RelativeTime date={m.updated_at} />
        </span>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title={store.name}
        titleExtra={<StatusBadge status={isArchived ? 'archived' : 'active'} />}
        breadcrumb={[
          { label: t('managed.memoryStores.title'), to: '/managed/memory-stores' },
          { label: store.name },
        ]}
        action={
          !isArchived ? (
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={handleArchive}>
                <Archive className="w-3.5 h-3.5 mr-1.5" />
                {t('common.archive')}
              </Button>
              <Button variant="outline" size="sm" onClick={handleDelete}>
                <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                {t('common.delete')}
              </Button>
            </div>
          ) : null
        }
      />

      <div className="flex items-center gap-1.5 text-sm text-muted-foreground mb-6">
        <MonoId id={store.id} truncate={false} />
        {store.description && (
          <>
            <span>·</span>
            <span>{store.description}</span>
          </>
        )}
        <span>·</span>
        <RelativeTime date={store.created_at} />
      </div>

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">{t('managed.memoryStores.memories')}</h2>
        {!isArchived && (
          <Button size="sm" onClick={() => setCreateMemOpen(true)}>
            <Plus className="w-4 h-4" />
            {t('managed.memoryStores.addMemory')}
          </Button>
        )}
      </div>

      <DataTable
        columns={memColumns}
        data={memories}
        loading={memLoading}
        fetching={memFetching}
        onRowClick={(m) => handleEditMemory(m)}
        actionMenu={(m) => isArchived ? [] : [
          { label: t('common.edit'), onClick: () => handleEditMemory(m) },
          { label: t('common.delete'), onClick: () => handleDeleteMemory(m), destructive: true },
        ]}
        emptyMessage={t('managed.memoryStores.noMemories')}
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

      <Dialog open={createMemOpen} onOpenChange={setCreateMemOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('managed.memoryStores.addMemory')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="text-sm font-medium mb-1 block">{t('managed.memoryStores.memPath')}</label>
              <Input
                placeholder="notes/ideas.md"
                value={newMemPath}
                onChange={(e) => setNewMemPath(e.target.value)}
              />
              <p className="text-xs text-muted-foreground mt-1">{t('managed.memoryStores.pathTip')}</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">{t('managed.memoryStores.memContent')}</label>
              <Textarea
                placeholder={t('managed.memoryStores.memContentPlaceholder')}
                value={newMemContent}
                onChange={(e) => setNewMemContent(e.target.value)}
                className="min-h-[120px] resize-y"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateMemOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleCreateMemory} disabled={createMemLoading || !newMemPath.trim() || !newMemContent.trim()}>
              {createMemLoading ? '...' : t('common.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Memory Dialog */}
      <Dialog open={!!editMem} onOpenChange={(open) => { if (!open) setEditMem(null) }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{editMem?.path}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="min-h-[250px] resize-y font-mono text-sm"
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditMem(null)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleSaveMemory} disabled={editLoading || !editContent.trim()}>
              {editLoading ? t('common.saving') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
