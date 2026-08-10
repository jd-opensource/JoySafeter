'use client'

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Archive,
  Trash2,
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileText,
  Eye,
  Code2,
  Pencil,
  MoreHorizontal,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
  type ManagedRequestScope,
} from '@/lib/managed/request-scope'
import { apiResourceId, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import {
  parseMemoryListResponse,
  parseMemoryStoreResponse,
  type MemoryRecord,
} from '@/lib/managed/memory-response-parsers'
import { isEntityId, parseMemoryStoreId, type MemoryId, type MemoryStoreId } from '@/types/entity-id'
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  PageHeader,
  StatusBadge,
  MonoId,
  RelativeTime,
  ConfirmDialog,
  ResourceErrorState,
} from '@/components/managed/shared'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Memory = MemoryRecord

interface TreeNode {
  name: string
  path: string
  isDir: boolean
  size?: number
  memory?: Memory
  children: TreeNode[]
}

type ViewMode = 'view' | 'code' | 'edit'

interface MemoryStoreActionVariables {
  storeId: MemoryStoreId
  rawId: string
  memId?: MemoryId
  runId: number
  scope: string
  scopeKey: string
  requestScope: ManagedRequestScope
}

// ---------------------------------------------------------------------------
// Tree builder
// ---------------------------------------------------------------------------

function buildTree(memories: Memory[]): TreeNode[] {
  const root: TreeNode[] = []

  for (const mem of memories) {
    const rawPath = mem.path.startsWith('/') ? mem.path.slice(1) : mem.path
    const parts = rawPath.split('/')
    let current = root

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      const isLast = i === parts.length - 1
      const fullPath = '/' + parts.slice(0, i + 1).join('/')

      if (isLast) {
        current.push({
          name: part,
          path: fullPath,
          isDir: false,
          size: mem.content_size_bytes,
          memory: mem,
          children: [],
        })
      } else {
        let dir = current.find((n) => n.isDir && n.name === part)
        if (!dir) {
          dir = { name: part, path: fullPath, isDir: true, children: [] }
          current.push(dir)
        }
        current = dir.children
      }
    }
  }

  // Sort: dirs first, then files; alphabetical within each group
  const sortNodes = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    for (const n of nodes) {
      if (n.isDir) sortNodes(n.children)
    }
  }
  sortNodes(root)
  return root
}

function collectAllDirPaths(nodes: TreeNode[]): Set<string> {
  const result = new Set<string>()
  const walk = (list: TreeNode[]) => {
    for (const n of list) {
      if (n.isDir) {
        result.add(n.path)
        walk(n.children)
      }
    }
  }
  walk(nodes)
  return result
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ---------------------------------------------------------------------------
// File tree item
// ---------------------------------------------------------------------------

function TreeItem({
  node,
  depth,
  expanded,
  selected,
  onToggle,
  onSelect,
  onDelete,
  isArchived,
}: {
  node: TreeNode
  depth: number
  expanded: boolean
  selected: boolean
  onToggle: () => void
  onSelect: () => void
  onDelete?: () => void
  isArchived: boolean
}) {
  if (node.isDir) {
    return (
      <button
        className="group flex w-full items-center gap-1 rounded px-2 py-1 text-left text-sm hover:bg-accent"
        style={{ paddingLeft: depth * 16 + 8 }}
        onClick={onToggle}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
        {expanded ? (
          <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <span className="truncate font-medium">{node.name}</span>
      </button>
    )
  }

  return (
    <div
      className={`group flex w-full cursor-pointer items-center gap-1.5 rounded px-2 py-1 text-sm ${
        selected ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/50'
      }`}
      style={{ paddingLeft: depth * 16 + 8 }}
      onClick={onSelect}
    >
      <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate">{node.name}</span>
      <span className="shrink-0 text-xs text-muted-foreground">
        {node.size != null ? formatSize(node.size) : ''}
      </span>
      {!isArchived && onDelete && (
        <button
          className="ml-1 hidden shrink-0 rounded p-0.5 text-muted-foreground hover:text-destructive group-hover:inline-flex"
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Recursive tree renderer
// ---------------------------------------------------------------------------

function FileTree({
  nodes,
  depth,
  expandedDirs,
  selectedPath,
  onToggleDir,
  onSelectFile,
  onDeleteMemory,
  isArchived,
}: {
  nodes: TreeNode[]
  depth: number
  expandedDirs: Set<string>
  selectedPath: string | null
  onToggleDir: (path: string) => void
  onSelectFile: (mem: Memory) => void
  onDeleteMemory: (mem: Memory) => void
  isArchived: boolean
}) {
  return (
    <>
      {nodes.map((node) => (
        <React.Fragment key={node.path}>
          <TreeItem
            node={node}
            depth={depth}
            expanded={expandedDirs.has(node.path)}
            selected={!node.isDir && selectedPath === node.path}
            onToggle={() => onToggleDir(node.path)}
            onSelect={() => node.memory && onSelectFile(node.memory)}
            onDelete={node.memory ? () => onDeleteMemory(node.memory!) : undefined}
            isArchived={isArchived}
          />
          {node.isDir && expandedDirs.has(node.path) && (
            <FileTree
              nodes={node.children}
              depth={depth + 1}
              expandedDirs={expandedDirs}
              selectedPath={selectedPath}
              onToggleDir={onToggleDir}
              onSelectFile={onSelectFile}
              onDeleteMemory={onDeleteMemory}
              isArchived={isArchived}
            />
          )}
        </React.Fragment>
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// Content pane
// ---------------------------------------------------------------------------

function ContentPane({
  memory,
  viewMode,
  editContent,
  editLoading,
  isArchived,
  onViewModeChange,
  onEditContentChange,
  onSave,
  onCancel,
  t,
  canWrite,
}: {
  memory: Memory | null
  viewMode: ViewMode
  editContent: string
  editLoading: boolean
  isArchived: boolean
  onViewModeChange: (mode: ViewMode) => void
  onEditContentChange: (content: string) => void
  onSave: () => void
  onCancel: () => void
  t: (key: string, params?: Record<string, unknown>) => string
  canWrite: boolean
}) {
  if (!memory) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
        {t('managed.memoryStores.selectMemory') || 'Select a memory file to view its content'}
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-6 py-3">
        <div>
          <div className="font-mono text-sm font-medium">{memory.path}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <MonoId id={memory.id} truncate />
            <span>·</span>
            <span>
              Updated <RelativeTime date={memory.updated_at} />
            </span>
            {memory.version && (
              <>
                <span>·</span>
                <span>v{memory.version}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant={viewMode === 'view' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7 px-2"
            onClick={() => onViewModeChange('view')}
            title="View"
          >
            <Eye className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant={viewMode === 'code' ? 'secondary' : 'ghost'}
            size="sm"
            className="h-7 px-2"
            onClick={() => onViewModeChange('code')}
            title="Code"
          >
            <Code2 className="h-3.5 w-3.5" />
          </Button>
          {canWrite && !isArchived && (
            <Button
              variant={viewMode === 'edit' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-7 px-2"
              onClick={() => onViewModeChange('edit')}
              title="Edit"
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-6">
        {viewMode === 'view' && (
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{memory.content || ''}</ReactMarkdown>
          </div>
        )}
        {viewMode === 'code' && (
          <pre className="whitespace-pre-wrap break-words rounded-lg border bg-muted p-4 font-mono text-sm leading-relaxed">
            {memory.content || ''}
          </pre>
        )}
        {viewMode === 'edit' && (
          <div className="flex h-full flex-col gap-3">
            <Textarea
              value={editContent}
              onChange={(e) => onEditContentChange(e.target.value)}
              className="min-h-[300px] flex-1 resize-y font-mono text-sm"
            />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={onCancel}>
                {t('common.cancel')}
              </Button>
              <Button size="sm" onClick={onSave} disabled={editLoading || !editContent.trim()}>
                {editLoading ? t('common.saving') : t('common.save')}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MemoryStoreDetailPage({
  params,
}: {
  params: Promise<{ storeId: string }>
}) {
  const { storeId: rawId } = React.use(params)
  if (!isEntityId(rawId, 'memoryStore')) {
    return (
      <ResourceErrorState
        resource="memoryStore"
        error={{ status: 404 }}
        onBack={() => window.history.back()}
      />
    )
  }
  return <MemoryStoreDetailPageInner params={params} />
}

function MemoryStoreDetailPageInner({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: rawId } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()

  // UI state
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('view')
  const [editContent, setEditContent] = useState('')
  const [editLoading, setEditLoading] = useState(false)
  const [expandedDirs, setExpandedDirs] = useState<Set<string> | null>(null) // null = not initialized
  const [createMemOpen, setCreateMemOpen] = useState(false)
  const [newMemPath, setNewMemPath] = useState('')
  const [newMemContent, setNewMemContent] = useState('')
  const [createMemLoading, setCreateMemLoading] = useState(false)
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

  const storeId = parseMemoryStoreId(rawId || '')
  const operationScope = `${managedScope.key}:${rawId ?? ''}`
  const actionRunRef = useRef(0)
  const operationScopeRef = useRef(operationScope)
  const managedRequestScopeRef = useRef(managedScope)

  // Fetch store
  const {
    data: store,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['memory-store', managedScope.key, rawId],
    queryFn: () =>
      managedGet<unknown>(
        apiResourcePath('memory_stores', storeId),
        managedRequestOptions(managedScope),
      ).then(parseMemoryStoreResponse),
    enabled: !!rawId && hasManagedRequestScope(managedScope),
    retry: shouldRetryManagedResourceError,
  })

  // Fetch memories
  const { data: memoriesRes, isLoading: memLoading } = useQuery({
    queryKey: ['memory-store-memories', managedScope.key, rawId],
    queryFn: () =>
      managedGet<unknown>(
        apiResourceSubpath('memory_stores', storeId, ['memories'], {
          limit: 100,
          view: 'full',
        }),
        managedRequestOptions(managedScope),
      ).then(parseMemoryListResponse),
    enabled: !!rawId && hasManagedRequestScope(managedScope),
  })

  const memories = memoriesRes ?? []

  // Build file tree
  const tree = useMemo(() => buildTree(memories), [memories])

  useEffect(() => {
    actionRunRef.current += 1
    operationScopeRef.current = operationScope
    managedRequestScopeRef.current = managedScope
    setSelectedMemory(null)
    setViewMode('view')
    setEditContent('')
    setExpandedDirs(null)
    setCreateMemOpen(false)
    setNewMemPath('')
    setNewMemContent('')
    setEditLoading(false)
    setCreateMemLoading(false)
    setConfirmDialog((prev) => ({ ...prev, open: false }))
  }, [operationScope, managedScope])

  useEffect(
    () => () => {
      actionRunRef.current += 1
    },
    [],
  )

  useEffect(() => {
    if (expandedDirs === null && tree.length > 0) {
      setExpandedDirs(collectAllDirPaths(tree))
    }
  }, [expandedDirs, tree])

  useEffect(() => {
    if (!selectedMemory) return

    const currentMemory = memories.find((mem) => mem.id === selectedMemory.id)
    if (!currentMemory) {
      setSelectedMemory(null)
      setViewMode('view')
      setEditContent('')
      return
    }

    if (currentMemory !== selectedMemory) {
      setSelectedMemory(currentMemory)
      if (viewMode !== 'edit') {
        setEditContent(currentMemory.content || '')
      }
    }
  }, [memories, selectedMemory, viewMode])

  const isArchived = !!store?.archived_at
  const canWriteStore = !projectReadOnly && !isArchived

  const getCurrentOperationScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${managedScopeKey(orgId, projectId)}:${rawId ?? ''}`
  }

  const currentOperationScopeIsActive = (scope = operationScopeRef.current) =>
    operationScopeRef.current === scope && getCurrentOperationScope() === scope

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId &&
    currentOperationScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const actionVariables = (
    extra?: Pick<MemoryStoreActionVariables, 'memId'>,
  ): MemoryStoreActionVariables | null => {
    if (!currentOperationScopeIsActive()) return null
    if (!currentProjectAllowsWrite()) return null
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    return {
      storeId,
      rawId,
      runId,
      scope: operationScopeRef.current,
      scopeKey: managedRequestScopeRef.current.key,
      requestScope: managedRequestScopeRef.current,
      ...extra,
    }
  }

  const findCurrentMemory = (memId: MemoryId) =>
    currentOperationScopeIsActive()
      ? queryClient
          .getQueryData<Memory[]>(['memory-store-memories', managedScope.key, rawId])
          ?.find((mem) => mem.id === memId)
      : undefined

  const currentStoreIsActive = () => {
    if (!currentOperationScopeIsActive()) return false
    if (!currentProjectAllowsWrite()) return false
    const currentStore = queryClient.getQueryData<MemoryStore>([
      'memory-store',
      managedScope.key,
      rawId,
    ])
    return !!currentStore && currentStore.id === store?.id && !currentStore.archived_at
  }

  const closeConfirmDialog = () => {
    actionRunRef.current += 1
    setConfirmDialog((prev) => ({ ...prev, open: false }))
  }

  // Mutations
  const archiveMutation = useMutation({
    mutationFn: ({ storeId, requestScope, runId, scope }: MemoryStoreActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale memory store archive ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project memory store archive ignored')
      }
      return managedPost(
        apiResourcePath('memory_stores', storeId, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { rawId, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['memory-store', scopeKey, rawId] })
      queryClient.invalidateQueries({ queryKey: ['memory-stores', scopeKey] })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ storeId, requestScope, runId, scope }: MemoryStoreActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale memory store delete ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project memory store delete ignored')
      }
      return managedDelete(
        apiResourcePath('memory_stores', storeId),
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['memory-stores', scopeKey] })
      router.push('/managed/memory-stores')
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const deleteMemoryMutation = useMutation({
    mutationFn: ({ storeId, memId, requestScope, runId, scope }: MemoryStoreActionVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale memory delete ignored')
      }
      if (!currentProjectAllowsWrite()) {
        throw new Error('Archived project memory delete ignored')
      }
      return managedDelete(
        apiResourcePath('memory_stores', storeId, 'memories', memId!),
        managedRequestOptions(requestScope),
      )
    },
    onSuccess: (_data, { memId, rawId, runId, scope, scopeKey }) => {
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({
        queryKey: ['memory-store-memories', scopeKey, rawId],
      })
      setConfirmDialog((prev) => ({ ...prev, open: false }))
      if (selectedMemory && memId === selectedMemory.id) {
        setSelectedMemory(null)
      }
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  // Handlers
  const handleToggleDir = (path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev || [])
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const handleSelectFile = (mem: Memory) => {
    setSelectedMemory(mem)
    setViewMode('view')
    setEditContent(mem.content || '')
  }

  const handleViewModeChange = (mode: ViewMode) => {
    if (mode === 'edit' && !canWriteStore) return
    if (mode !== viewMode && (mode === 'edit' || viewMode === 'edit')) {
      actionRunRef.current += 1
      if (mode !== 'edit') {
        setEditLoading(false)
      }
    }
    if (mode === 'edit' && selectedMemory) {
      setEditContent(selectedMemory.content || '')
    }
    setViewMode(mode)
  }

  const handleCancelEditMemory = () => {
    actionRunRef.current += 1
    setEditLoading(false)
    if (selectedMemory) {
      setEditContent(selectedMemory.content || '')
    }
    setViewMode('view')
  }

  const handleSaveMemory = async () => {
    if (!selectedMemory || !editContent.trim()) return
    if (!currentStoreIsActive()) {
      setViewMode('view')
      return
    }
    const currentMemory = findCurrentMemory(selectedMemory.id)
    if (!currentMemory) {
      setSelectedMemory(null)
      setViewMode('view')
      setEditContent('')
      return
    }
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    const scope = operationScopeRef.current
    const requestScope = managedRequestScopeRef.current
    if (!currentOperationScopeIsActive(scope)) return
    const memId = currentMemory.id
    const content = editContent
    setEditLoading(true)
    try {
      await managedPost(
        apiResourcePath('memory_stores', storeId, 'memories', memId),
        {
          content,
        },
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({
        queryKey: ['memory-store-memories', requestScope.key, rawId],
      })
      // Update the selected memory content in place
      setSelectedMemory((prev) => (prev && prev.id === memId ? { ...prev, content } : prev))
      setViewMode('view')
    } catch (error) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'managed.memoryStores.saveFailed')
    } finally {
      if (isCurrentAction(runId, scope)) {
        setEditLoading(false)
      }
    }
  }

  const handleDeleteMemory = (mem: Memory) => {
    if (!canWriteStore) return
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    const scope = operationScopeRef.current
    const requestScope = managedRequestScopeRef.current
    if (!currentOperationScopeIsActive(scope)) return
    setTimeout(() => {
      if (!isCurrentAction(runId, scope)) return
      setConfirmDialog({
        open: true,
        title: t('managed.memoryStores.deleteMemory'),
        description: t('managed.memoryStores.deleteMemoryDescription', { path: mem.path }),
        confirmLabel: t('common.delete'),
        destructive: true,
        onConfirm: () => {
          if (!currentStoreIsActive() || !findCurrentMemory(mem.id)) {
            setConfirmDialog((prev) => ({ ...prev, open: false }))
            return
          }
          const action = actionVariables({ memId: mem.id })
          if (action) deleteMemoryMutation.mutate(action)
        },
      })
    }, 0)
  }

  const handleCreateMemory = async () => {
    if (!newMemPath.trim() || !newMemContent.trim()) return
    if (!currentStoreIsActive()) {
      setCreateMemOpen(false)
      return
    }
    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    const scope = operationScopeRef.current
    const requestScope = managedRequestScopeRef.current
    if (!currentOperationScopeIsActive(scope)) return
    const path = newMemPath.trim()
    const content = newMemContent.trim()
    setCreateMemLoading(true)
    try {
      await managedPost(
        apiResourcePath('memory_stores', storeId, 'memories'),
        {
          path,
          content,
        },
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      setNewMemPath('')
      setNewMemContent('')
      setCreateMemOpen(false)
      queryClient.invalidateQueries({
        queryKey: ['memory-store-memories', requestScope.key, rawId],
      })
    } catch (error) {
      if (!isCurrentAction(runId, scope)) return
      toastOperationError(t, error, 'managed.memoryStores.saveFailed')
    } finally {
      if (isCurrentAction(runId, scope)) {
        setCreateMemLoading(false)
      }
    }
  }

  const handleCreateMemoryOpenChange = (open: boolean) => {
    if (open && (!currentOperationScopeIsActive() || !currentProjectAllowsWrite())) return
    actionRunRef.current += 1
    if (!open) {
      setCreateMemLoading(false)
    }
    setCreateMemOpen(open)
  }

  const handleArchive = () => {
    if (!currentStoreIsActive()) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.memoryStores.archiveStore'),
      description: t('managed.memoryStores.archiveDescription', { name: store?.name }),
      confirmLabel: t('common.archive'),
      destructive: true,
      onConfirm: () => {
        if (!currentStoreIsActive()) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables()
        if (action) archiveMutation.mutate(action)
      },
    })
  }

  const handleDelete = () => {
    if (!currentStoreIsActive()) return
    actionRunRef.current += 1
    setConfirmDialog({
      open: true,
      title: t('managed.memoryStores.deleteStore'),
      description: t('managed.memoryStores.deleteDescription', { name: store?.name }),
      confirmLabel: t('common.delete'),
      destructive: true,
      onConfirm: () => {
        if (!currentStoreIsActive()) {
          setConfirmDialog((prev) => ({ ...prev, open: false }))
          return
        }
        const action = actionVariables()
        if (action) deleteMutation.mutate(action)
      },
    })
  }

  // Loading / error states
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

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <PageHeader
        title={store.name}
        titleExtra={<StatusBadge status={isArchived ? 'archived' : 'active'} />}
        breadcrumb={[
          { label: t('managed.memoryStores.title'), to: '/managed/memory-stores' },
          { label: store.name },
        ]}
        action={
          <div className="flex items-center gap-2">
            {canWriteStore && (
              <Button size="sm" onClick={() => handleCreateMemoryOpenChange(true)}>
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                {t('managed.memoryStores.addMemory')}
              </Button>
            )}
            {canWriteStore && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="h-8 w-8 p-0">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={handleArchive}>
                    <Archive className="mr-2 h-4 w-4" />
                    {t('common.archive')}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={handleDelete}
                    className="text-destructive focus:text-destructive"
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    {t('common.delete')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        }
      />

      {/* Store meta */}
      <div className="mb-3 flex items-center gap-1.5 text-sm text-muted-foreground">
        {store.description && <span>{store.description}</span>}
        {store.description && <span>·</span>}
        <MonoId id={store.id} truncate={false} />
        <span>·</span>
        <span>
          Created <RelativeTime date={store.created_at} />
        </span>
      </div>

      {/* Main split layout */}
      <div className="flex flex-1 overflow-hidden rounded-lg border">
        {/* Left: File tree */}
        <div className="w-72 shrink-0 overflow-y-auto border-r bg-muted/30 py-2">
          {memLoading ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              {t('common.loading')}
            </div>
          ) : memories.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              {t('managed.memoryStores.noMemories')}
            </div>
          ) : (
            <FileTree
              nodes={tree}
              depth={0}
              expandedDirs={expandedDirs || new Set()}
              selectedPath={selectedMemory?.path || null}
              onToggleDir={handleToggleDir}
              onSelectFile={handleSelectFile}
              onDeleteMemory={handleDeleteMemory}
              isArchived={!canWriteStore}
            />
          )}
        </div>

        {/* Right: Content pane */}
        <ContentPane
          memory={selectedMemory}
          viewMode={viewMode}
          editContent={editContent}
          editLoading={editLoading}
          isArchived={isArchived}
          canWrite={canWriteStore}
          onViewModeChange={handleViewModeChange}
          onEditContentChange={setEditContent}
          onSave={handleSaveMemory}
          onCancel={handleCancelEditMemory}
          t={t}
        />
      </div>

      {/* Confirm dialog */}
      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.title}
        description={confirmDialog.description}
        confirmLabel={confirmDialog.confirmLabel}
        destructive={confirmDialog.destructive}
        onConfirm={confirmDialog.onConfirm}
        onCancel={closeConfirmDialog}
      />

      {/* Create memory dialog */}
      <Dialog open={canWriteStore && createMemOpen} onOpenChange={handleCreateMemoryOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('managed.memoryStores.addMemory')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="mb-1 block text-sm font-medium">
                {t('managed.memoryStores.memPath')}
              </label>
              <Input
                placeholder="notes/ideas.md"
                value={newMemPath}
                onChange={(e) => setNewMemPath(e.target.value)}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {t('managed.memoryStores.pathTip')}
              </p>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium">
                {t('managed.memoryStores.memContent')}
              </label>
              <Textarea
                placeholder={t('managed.memoryStores.memContentPlaceholder')}
                value={newMemContent}
                onChange={(e) => setNewMemContent(e.target.value)}
                className="min-h-[120px] resize-y"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => handleCreateMemoryOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleCreateMemory}
              disabled={
                !canWriteStore || createMemLoading || !newMemPath.trim() || !newMemContent.trim()
              }
            >
              {createMemLoading ? '...' : t('common.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
