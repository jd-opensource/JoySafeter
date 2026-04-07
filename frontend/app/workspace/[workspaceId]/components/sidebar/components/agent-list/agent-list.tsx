'use client'

import {
  Bot,
  Check,
  ChevronRight,
  ChevronDown,
  Copy,
  Folder,
  FolderOpen,
  FolderPlus,
  GripVertical,
  MoreHorizontal,
  Pencil,
  Trash2,
  X,
} from 'lucide-react'
import Link from 'next/link'
import { useParams, usePathname } from 'next/navigation'
import { useCallback, useState, useRef, useEffect, useMemo } from 'react'

import type {
  Folder as FolderType,
  AgentMetadata,
} from '@/app/workspace/[workspaceId]/components/sidebar/sidebar'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

/**
 * Agent item component with drag support and context menu
 */
interface AgentItemProps {
  agent: AgentMetadata
  active: boolean
  indented?: boolean
  indentLevel?: number
  onDragStart?: (agentId: string) => void
  onDragEnd?: () => void
  onRename?: (id: string, newName: string) => void
  onDelete?: (id: string) => void
  onDuplicate?: (id: string) => void
  canEdit?: boolean
}


function AgentItem({
  agent,
  active,
  indented = false,
  indentLevel = 0,
  onDragStart,
  onDragEnd,
  onRename,
  onDelete,
  onDuplicate,
  canEdit: _canEdit = true,
}: AgentItemProps) {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const [isDragging, setIsDragging] = useState(false)
  const [showMenu, setShowMenu] = useState(false)
  const [menuPosition, setMenuPosition] = useState({ x: 0, y: 0 })
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState(agent.name)
  const inputRef = useRef<HTMLInputElement>(null)

  // Focus input when editing starts
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  const handleDragStart = (e: React.DragEvent) => {
    if (isEditing) {
      e.preventDefault()
      return
    }
    e.dataTransfer.setData('agentId', agent.id)
    e.dataTransfer.effectAllowed = 'move'
    setIsDragging(true)
    onDragStart?.(agent.id)
  }

  const handleDragEnd = () => {
    setIsDragging(false)
    onDragEnd?.()
  }

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setMenuPosition({ x: e.clientX, y: e.clientY })
    setShowMenu(true)
  }, [])

  const handleStartRename = useCallback(() => {
    setShowMenu(false)
    setEditName(agent.name)
    setIsEditing(true)
  }, [agent.name])

  const handleSaveRename = useCallback(() => {
    if (editName.trim() && editName !== agent.name && onRename) {
      onRename(agent.id, editName.trim())
    }
    setIsEditing(false)
  }, [editName, agent.id, agent.name, onRename])

  const handleCancelRename = useCallback(() => {
    setEditName(agent.name)
    setIsEditing(false)
  }, [agent.name])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        handleSaveRename()
      } else if (e.key === 'Escape') {
        handleCancelRename()
      }
    },
    [handleSaveRename, handleCancelRename],
  )

  const handleDelete = useCallback(() => {
    setShowMenu(false)
    onDelete?.(agent.id)
  }, [agent.id, onDelete])

  const handleDuplicate = useCallback(() => {
    setShowMenu(false)
    onDuplicate?.(agent.id)
  }, [agent.id, onDuplicate])

  const indentPadding = indented ? (indentLevel > 0 ? indentLevel * 12 : 16) : 0

  return (
    <>
      <div
        draggable={!isEditing}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onContextMenu={handleContextMenu}
        className={cn(
          'group flex items-center rounded-md transition-colors duration-100',
          isDragging && 'opacity-50',
          active
            ? 'bg-[var(--surface-9)] text-[var(--text-primary)]'
            : 'text-[var(--text-secondary)] hover:bg-[var(--surface-5)]',
        )}
        style={{ marginLeft: `${indentPadding}px` }}
      >
        <div className="flex cursor-grab items-center px-[4px] py-[6px] opacity-0 transition-opacity group-hover:opacity-100">
          <GripVertical className="h-[12px] w-[12px] text-[var(--text-tertiary)]" />
        </div>

        {isEditing ? (
          <div className="flex flex-1 items-center gap-[6px] py-[3px] pr-[6px] duration-150 animate-in fade-in">
            <Bot className="ml-[2px] h-[14px] w-[14px] flex-shrink-0 text-[var(--brand-500)]" />
            <div className="relative flex flex-1 items-center">
              <input
                ref={inputRef}
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onBlur={handleSaveRename}
                onKeyDown={handleKeyDown}
                className="border-[var(--brand-primary)] ring-[var(--brand-primary)] focus:ring-[var(--brand-primary)] w-full rounded-md border bg-[var(--surface-1)] px-[8px] py-[4px] text-xs-plus font-medium text-[var(--text-primary)] shadow-sm outline-none ring-2 transition-all placeholder:text-[var(--text-subtle)] focus:border-[var(--brand-primary)]"
                onClick={(e) => e.stopPropagation()}
                placeholder="Enter name..."
              />
            </div>
            <div className="flex items-center gap-[2px]">
              <button
                type="button"
                className="hover:bg-[var(--brand-primary)] flex h-[24px] w-[24px] items-center justify-center rounded-md bg-[var(--brand-primary)] text-white shadow-sm transition-all hover:shadow active:scale-95"
                onClick={handleSaveRename}
                title="Save"
              >
                <Check className="h-[12px] w-[12px]" strokeWidth={2.5} />
              </button>
              <button
                type="button"
                className="flex h-[24px] w-[24px] items-center justify-center rounded-md bg-[var(--surface-5)] text-[var(--text-tertiary)] transition-all hover:bg-[var(--surface-9)] hover:text-[var(--text-secondary)] active:scale-95"
                onClick={handleCancelRename}
                title="Cancel"
              >
                <X className="h-[12px] w-[12px]" strokeWidth={2.5} />
              </button>
            </div>
          </div>
        ) : (
          <TooltipProvider delayDuration={400}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  href={`/workspace/${workspaceId}/${agent.id}`}
                  className="flex min-w-0 flex-1 items-center py-[5px] pr-[6px]"
                  onClick={(e) => isDragging && e.preventDefault()}
                  onDoubleClick={(e) => {
                    e.preventDefault()
                    handleStartRename()
                  }}
                >
                  <Bot className="mr-[6px] h-[14px] w-[14px] flex-shrink-0 text-[var(--brand-500)]" />
                  <span className="truncate text-xs-plus font-medium">{agent.name}</span>
                  {agent.graphMode === 'code' && (
                    <span className="ml-1.5 flex-shrink-0 rounded bg-primary/10 px-1 py-0.5 text-xxs font-semibold uppercase leading-none text-primary">
                      Code
                    </span>
                  )}
                </Link>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                className="max-w-[280px] break-words border border-[var(--border)] bg-[var(--surface-1)] text-[var(--text-primary)] shadow-lg"
              >
                {agent.name}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}

        {/* Menu Button */}
        {!isEditing && (
          <button
            type="button"
            className="mr-[4px] rounded-sm p-[4px] opacity-0 transition-opacity hover:bg-[var(--surface-9)] group-hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation()
              e.preventDefault()
              setMenuPosition({ x: e.clientX, y: e.clientY })
              setShowMenu(!showMenu)
            }}
          >
            <MoreHorizontal className="h-[12px] w-[12px] text-[var(--text-tertiary)]" />
          </button>
        )}
      </div>

      {/* Context Menu */}
      {showMenu && (
        <>
          <div className="fixed inset-0 z-[100]" onClick={() => setShowMenu(false)} />
          <div
            className="fixed z-[101] min-w-[120px] rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-[4px] shadow-lg"
            style={{
              left: `${menuPosition.x}px`,
              top: `${menuPosition.y}px`,
            }}
          >
            {onRename && (
              <button
                type="button"
                className="flex w-full items-center gap-[6px] rounded-md px-[6px] py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
                onClick={handleStartRename}
              >
                <Pencil className="h-[12px] w-[12px]" />
                {t('workspace.rename')}
              </button>
            )}
            {onDuplicate && (
              <button
                type="button"
                className="flex w-full items-center gap-[6px] rounded-md px-[6px] py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
                onClick={handleDuplicate}
              >
                <Copy className="h-[12px] w-[12px]" />
                {t('workspace.duplicate')}
              </button>
            )}
            {onDelete && (
              <>
                <div className="my-[4px] h-[1px] bg-[var(--border)]" />
                <button
                  type="button"
                  className="flex w-full items-center gap-[6px] rounded-md px-[6px] py-[5px] text-xs-plus font-medium text-[var(--status-error)] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={handleDelete}
                >
                  <Trash2 className="h-[12px] w-[12px]" />
                  {t('workspace.delete')}
                </button>
              </>
            )}
          </div>
        </>
      )}
    </>
  )
}

/**
 * Folder item component with drop support
 */
interface FolderItemProps {
  folder: FolderType
  agents: AgentMetadata[]
  subfolders: FolderType[]
  allFolders: FolderType[]
  activeAgentId?: string
  depth?: number
  maxDepth: number
  onToggle: () => void
  onRename: (newName: string) => void
  onDelete: () => void
  onCreateSubfolder?: () => void
  onDuplicate?: () => void
  onDropAgent?: (agentId: string) => void
  onDragAgentStart?: (agentId: string) => void
  onDragAgentEnd?: () => void
  isDragActive?: boolean
  getAgentsInFolder: (folderId: string) => AgentMetadata[]
  getSubfolders: (parentId: string) => FolderType[]
  onToggleFolder: (folderId: string) => void
  onRenameFolder: (folderId: string, newName: string) => void
  onDeleteFolder: (folderId: string) => void
  onCreateSubfolderFor: (parentId: string) => void
  onDuplicateFolder: (folderId: string) => void
  onMoveAgentToFolder: (agentId: string, folderId: string) => void
  onRenameAgent?: (id: string, newName: string) => void
  onDeleteAgent?: (id: string) => void
  onDuplicateAgent?: (id: string) => void
  canEdit?: boolean
}

function FolderItem({
  folder,
  agents,
  subfolders,
  allFolders,
  activeAgentId,
  depth = 0,
  maxDepth,
  onToggle,
  onRename,
  onDelete,
  onCreateSubfolder,
  onDuplicate,
  onDropAgent,
  onDragAgentStart,
  onDragAgentEnd,
  isDragActive = false,
  getAgentsInFolder,
  getSubfolders,
  onToggleFolder,
  onRenameFolder,
  onDeleteFolder,
  onCreateSubfolderFor,
  onDuplicateFolder,
  onMoveAgentToFolder,
  onRenameAgent,
  onDeleteAgent,
  onDuplicateAgent,
  canEdit = true,
}: FolderItemProps) {
  const { t } = useTranslation()
  // Check if can create subfolder (depth 0 can create, depth 1+ cannot)
  const canCreateSubfolder = depth < maxDepth - 1
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState(folder.name)
  const [showMenu, setShowMenu] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)

  const handleSaveRename = useCallback(() => {
    if (editName.trim() && editName !== folder.name) {
      onRename(editName.trim())
    } else {
      setEditName(folder.name)
    }
    setIsEditing(false)
  }, [editName, folder.name, onRename])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        handleSaveRename()
      } else if (e.key === 'Escape') {
        setEditName(folder.name)
        setIsEditing(false)
      }
    },
    [handleSaveRename, folder.name],
  )

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setIsDragOver(true)
  }

  const handleDragLeave = () => {
    setIsDragOver(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const agentId = e.dataTransfer.getData('agentId')
    if (agentId) {
      onDropAgent?.(agentId)
    }
  }

  const indentPadding = depth * 12

  return (
    <div className="space-y-[2px]">
      {/* Folder Header */}
      <div
        className={cn(
          'group flex items-center rounded-md py-[5px] pr-[6px] text-[var(--text-secondary)] transition-all',
          isDragOver
            ? 'bg-[var(--brand-primary)] ring-2 ring-[var(--brand-primary)]'
            : 'hover:bg-[var(--surface-5)]',
          isDragActive && !isDragOver && 'ring-dashed ring-1 ring-[var(--border)]',
        )}
        style={{ paddingLeft: `${8 + indentPadding}px` }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <button type="button" className="flex flex-1 items-center gap-[6px]" onClick={onToggle}>
          {folder.isExpanded ? (
            <ChevronDown className="h-[12px] w-[12px] flex-shrink-0 transition-all duration-100" />
          ) : (
            <ChevronRight className="h-[12px] w-[12px] flex-shrink-0 transition-all duration-100" />
          )}
          {folder.isExpanded ? (
            <FolderOpen className="h-[14px] w-[14px] flex-shrink-0 text-[var(--text-tertiary)]" />
          ) : (
            <Folder className="h-[14px] w-[14px] flex-shrink-0 text-[var(--text-tertiary)]" />
          )}
          {isEditing ? (
            <div className="flex flex-1 items-center gap-[4px] duration-150 animate-in fade-in">
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onBlur={handleSaveRename}
                onKeyDown={handleKeyDown}
                className="border-[var(--brand-primary)] ring-[var(--brand-primary)] focus:ring-[var(--brand-primary)] flex-1 rounded-sm border bg-[var(--surface-1)] px-[6px] py-[2px] text-xs-plus font-medium text-[var(--text-primary)] shadow-sm outline-none ring-2 transition-all focus:border-[var(--brand-primary)]"
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
              <button
                type="button"
                className="hover:bg-[var(--brand-primary)] flex h-[20px] w-[20px] items-center justify-center rounded-sm bg-[var(--brand-primary)] text-white shadow-sm transition-all active:scale-95"
                onClick={(e) => {
                  e.stopPropagation()
                  handleSaveRename()
                }}
              >
                <Check className="h-[10px] w-[10px]" strokeWidth={2.5} />
              </button>
              <button
                type="button"
                className="flex h-[20px] w-[20px] items-center justify-center rounded-sm bg-[var(--surface-5)] text-[var(--text-tertiary)] transition-all hover:bg-[var(--surface-9)] active:scale-95"
                onClick={(e) => {
                  e.stopPropagation()
                  setEditName(folder.name)
                  setIsEditing(false)
                }}
              >
                <X className="h-[10px] w-[10px]" strokeWidth={2.5} />
              </button>
            </div>
          ) : (
            <TooltipProvider delayDuration={400}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="truncate text-small font-medium">{folder.name}</span>
                </TooltipTrigger>
                <TooltipContent
                  side="bottom"
                  className="max-w-[280px] break-words border border-[var(--border)] bg-[var(--surface-1)] text-[var(--text-primary)] shadow-lg"
                >
                  {folder.name}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </button>

        {/* Menu */}
        <div className="relative">
          <button
            type="button"
            className="rounded-sm p-[2px] opacity-0 transition-opacity group-hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation()
              setShowMenu(!showMenu)
            }}
          >
            <MoreHorizontal className="h-[14px] w-[14px]" />
          </button>

          {showMenu && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowMenu(false)} />
              <div className="absolute right-0 top-[24px] z-50 min-w-[140px] rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-[4px] shadow-lg">
                {canCreateSubfolder && (
                  <button
                    type="button"
                    className="flex w-full items-center gap-[6px] rounded-md px-[6px] py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
                    onClick={() => {
                      setShowMenu(false)
                      onCreateSubfolder?.()
                    }}
                  >
                    <FolderPlus className="h-[12px] w-[12px]" />
                    {t('workspace.newSubfolder')}
                  </button>
                )}
                <button
                  type="button"
                  className="flex w-full items-center gap-[6px] rounded-md px-[6px] py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={() => {
                    setShowMenu(false)
                    onDuplicate?.()
                  }}
                >
                  <Copy className="h-[12px] w-[12px]" />
                  {t('workspace.duplicate')}
                </button>
                <div className="my-[4px] h-[1px] bg-[var(--border)]" />
                <button
                  type="button"
                  className="flex w-full items-center gap-[6px] rounded-md px-[6px] py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={() => {
                    setShowMenu(false)
                    setIsEditing(true)
                  }}
                >
                  <Pencil className="h-[12px] w-[12px]" />
                  {t('workspace.rename')}
                </button>
                <button
                  type="button"
                  className="flex w-full items-center gap-[6px] rounded-md px-[6px] py-[5px] text-xs-plus font-medium text-[var(--status-error)] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={() => {
                    setShowMenu(false)
                    onDelete()
                  }}
                >
                  <Trash2 className="h-[12px] w-[12px]" />
                  {t('workspace.delete')}
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Folder Contents (expanded) */}
      {folder.isExpanded && (
        <div className="space-y-[2px]">
          {/* Subfolders - only render if not at max depth */}
          {depth < maxDepth - 1 &&
            subfolders.map((subfolder) => (
              <FolderItem
                key={subfolder.id}
                folder={subfolder}
                agents={getAgentsInFolder(subfolder.id)}
                subfolders={getSubfolders(subfolder.id)}
                allFolders={allFolders}
                activeAgentId={activeAgentId}
                depth={depth + 1}
                maxDepth={maxDepth}
                onToggle={() => onToggleFolder(subfolder.id)}
                onRename={(newName) => onRenameFolder(subfolder.id, newName)}
                onDelete={() => onDeleteFolder(subfolder.id)}
                onCreateSubfolder={() => onCreateSubfolderFor(subfolder.id)}
                onDuplicate={() => onDuplicateFolder(subfolder.id)}
                onDropAgent={(aId) => onMoveAgentToFolder(aId, subfolder.id)}
                onDragAgentStart={onDragAgentStart}
                onDragAgentEnd={onDragAgentEnd}
                isDragActive={isDragActive}
                getAgentsInFolder={getAgentsInFolder}
                getSubfolders={getSubfolders}
                onToggleFolder={onToggleFolder}
                onRenameFolder={onRenameFolder}
                onDeleteFolder={onDeleteFolder}
                onCreateSubfolderFor={onCreateSubfolderFor}
                onDuplicateFolder={onDuplicateFolder}
                onMoveAgentToFolder={onMoveAgentToFolder}
                onRenameAgent={onRenameAgent}
                onDeleteAgent={onDeleteAgent}
                onDuplicateAgent={onDuplicateAgent}
                canEdit={canEdit}
              />
            ))}

          {/* Agents in this folder */}
          {agents.map((agent) => (
            <AgentItem
              key={agent.id}
              agent={agent}
              active={agent.id === activeAgentId}
              indented
              indentLevel={depth + 1}
              onDragStart={onDragAgentStart}
              onDragEnd={onDragAgentEnd}
              onRename={onRenameAgent}
              onDelete={onDeleteAgent}
              onDuplicate={onDuplicateAgent}
              canEdit={canEdit}
            />
          ))}

          {/* Empty State */}
          {agents.length === 0 && subfolders.length === 0 && (
            <div
              className={cn(
                'rounded-md py-[8px] text-app-xs font-normal',
                isDragOver
                  ? 'bg-[var(--brand-primary)] text-[var(--text-secondary)]'
                  : 'text-[var(--text-subtle)] opacity-60',
              )}
              style={{ marginLeft: `${24 + indentPadding}px` }}
            >
              {isDragOver ? t('workspace.dropHereToAdd') : t('workspace.dropWorkflowsHere')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Root drop zone for removing from folders
 */
interface RootDropZoneProps {
  children: React.ReactNode
  isDragActive: boolean
  onDropAgent?: (agentId: string) => void
}

function RootDropZone({ children, isDragActive, onDropAgent }: RootDropZoneProps) {
  const { t } = useTranslation()
  const [isDragOver, setIsDragOver] = useState(false)

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setIsDragOver(true)
  }

  const handleDragLeave = () => {
    setIsDragOver(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const agentId = e.dataTransfer.getData('agentId')
    if (agentId) {
      onDropAgent?.(agentId)
    }
  }

  if (!isDragActive) {
    return <>{children}</>
  }

  return (
    <div
      className={cn('rounded-md p-[4px] transition-all', isDragOver && 'bg-[var(--surface-5)]')}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {children}
      {isDragOver && (
        <div className="rounded-md border border-dashed border-[var(--border)] py-[8px] text-center text-app-xs font-medium text-[var(--text-tertiary)]">
          {t('workspace.dropHereToRemoveFromFolder')}
        </div>
      )}
    </div>
  )
}

/**
 * Default maximum folder depth
 */
const DEFAULT_MAX_FOLDER_DEPTH = 2

/**
 * AgentList props
 */
interface AgentListProps {
  regularAgents: AgentMetadata[]
  folders?: FolderType[]
  isLoading?: boolean
  searchQuery?: string
  onToggleFolder?: (folderId: string) => void
  onRenameFolder?: (folderId: string, newName: string) => void
  onDeleteFolder?: (folderId: string) => void
  onMoveAgentToFolder?: (agentId: string, folderId: string | null) => void
  onCreateSubfolder?: (parentId: string) => void
  onDuplicateFolder?: (folderId: string) => void
  maxFolderDepth?: number
  onRenameAgent?: (id: string, newName: string) => void
  onDeleteAgent?: (id: string) => void
  onDuplicateAgent?: (id: string) => void
  canEdit?: boolean
}

/**
 * AgentList component with folders and drag-drop support
 */
export function AgentList({
  regularAgents,
  folders = [],
  isLoading = false,
  searchQuery = '',
  onToggleFolder,
  onRenameFolder,
  onDeleteFolder,
  onMoveAgentToFolder,
  onCreateSubfolder,
  onDuplicateFolder,
  maxFolderDepth = DEFAULT_MAX_FOLDER_DEPTH,
  onRenameAgent,
  onDeleteAgent,
  onDuplicateAgent,
  canEdit = true,
}: AgentListProps) {
  const { t } = useTranslation()
  const pathname = usePathname()
  const params = useParams()
  const agentId = params.agentId as string | undefined
  const [isDragActive, setIsDragActive] = useState(false)

  const isAgentActive = useCallback((id: string) => pathname?.includes(`/${id}`), [pathname])

  // Filter agents by search query
  const filteredAgents = useMemo(() => {
    if (!searchQuery.trim()) {
      return regularAgents
    }
    const query = searchQuery.toLowerCase().trim()
    return regularAgents.filter((agent) => agent.name.toLowerCase().includes(query))
  }, [regularAgents, searchQuery])

  // Filter folders by search query (show folder if it contains matching agents or has matching name)
  const filteredFolders = useMemo(() => {
    if (!searchQuery.trim()) {
      return folders
    }
    const query = searchQuery.toLowerCase().trim()
    return folders.filter((folder) => {
      // Check if folder name matches
      if (folder.name.toLowerCase().includes(query)) {
        return true
      }
      // Check if folder contains matching agents
      const agentsInFolder = filteredAgents.filter((a) => a.folderId === folder.id)
      return agentsInFolder.length > 0
    })
  }, [folders, searchQuery, filteredAgents])

  // Get agents in each folder
  const getAgentsInFolder = useCallback(
    (folderId: string) => filteredAgents.filter((a) => a.folderId === folderId),
    [filteredAgents],
  )

  // Get subfolders of a folder
  const getSubfolders = useCallback(
    (parentId: string) => filteredFolders.filter((f) => f.parentId === parentId),
    [filteredFolders],
  )

  // Get root folders (no parent)
  const rootFolders = filteredFolders.filter((f) => !f.parentId)

  // Get root agents (not in any folder)
  const rootAgents = filteredAgents.filter((a) => !a.folderId)

  const handleDragStart = useCallback(() => {
    setIsDragActive(true)
  }, [])

  const handleDragEnd = useCallback(() => {
    setIsDragActive(false)
  }, [])

  if (isLoading) {
    return (
      <div className="space-y-[4px]">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={`skeleton-${i}`}
            className="flex items-center gap-[6px] rounded-md px-[6px] py-[5px]"
          >
            <Skeleton className="h-[12px] w-[12px] rounded-xs" />
            <Skeleton className="h-[14px] w-[80px]" />
          </div>
        ))}
      </div>
    )
  }

  const hasNoContent = rootFolders.length === 0 && regularAgents.length === 0

  if (hasNoContent) {
    return (
      <div className="px-[8px] py-[12px] text-center text-small font-medium text-[var(--text-tertiary)]">
        {t('workspace.noAgentsYet')}
      </div>
    )
  }

  return (
    <div className="space-y-[4px]">
      {/* Root Folders */}
      {rootFolders.map((folder) => (
        <FolderItem
          key={folder.id}
          folder={folder}
          agents={getAgentsInFolder(folder.id)}
          subfolders={getSubfolders(folder.id)}
          allFolders={folders}
          activeAgentId={agentId}
          depth={0}
          maxDepth={maxFolderDepth}
          onToggle={() => onToggleFolder?.(folder.id)}
          onRename={(newName) => onRenameFolder?.(folder.id, newName)}
          onDelete={() => onDeleteFolder?.(folder.id)}
          onCreateSubfolder={() => onCreateSubfolder?.(folder.id)}
          onDuplicate={() => onDuplicateFolder?.(folder.id)}
          onDropAgent={(aId) => onMoveAgentToFolder?.(aId, folder.id)}
          onDragAgentStart={handleDragStart}
          onDragAgentEnd={handleDragEnd}
          isDragActive={isDragActive}
          getAgentsInFolder={getAgentsInFolder}
          getSubfolders={getSubfolders}
          onToggleFolder={(id) => onToggleFolder?.(id)}
          onRenameFolder={(id, name) => onRenameFolder?.(id, name)}
          onDeleteFolder={(id) => onDeleteFolder?.(id)}
          onCreateSubfolderFor={(id) => onCreateSubfolder?.(id)}
          onDuplicateFolder={(id) => onDuplicateFolder?.(id)}
          onMoveAgentToFolder={(aId, fId) => onMoveAgentToFolder?.(aId, fId)}
          onRenameAgent={onRenameAgent}
          onDeleteAgent={onDeleteAgent}
          onDuplicateAgent={onDuplicateAgent}
          canEdit={canEdit}
        />
      ))}

      {/* Root Agents (not in any folder) */}
      {rootAgents.length > 0 && (
        <RootDropZone
          isDragActive={isDragActive && rootFolders.length > 0}
          onDropAgent={(aId) => onMoveAgentToFolder?.(aId, null)}
        >
          <div className="space-y-[2px]">
            {rootFolders.length > 0 && (
              <div className="px-[8px] py-[4px] text-app-xs font-medium text-[var(--text-tertiary)]">
                {t('workspace.ungrouped')}
              </div>
            )}
            {rootAgents.map((agent) => (
              <AgentItem
                key={agent.id}
                agent={agent}
                active={isAgentActive(agent.id)}
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
                onRename={onRenameAgent}
                onDelete={onDeleteAgent}
                onDuplicate={onDuplicateAgent}
                canEdit={canEdit}
              />
            ))}
          </div>
        </RootDropZone>
      )}

      {/* Empty root drop zone when all agents are in folders */}
      {rootAgents.length === 0 && rootFolders.length > 0 && isDragActive && (
        <RootDropZone isDragActive={true} onDropAgent={(aId) => onMoveAgentToFolder?.(aId, null)}>
          <div className="rounded-md border border-dashed border-[var(--border)] py-[12px] text-center text-app-xs font-medium text-[var(--text-tertiary)]">
            {t('workspace.dropHereToRemoveFromFolder')}
          </div>
        </RootDropZone>
      )}
    </div>
  )
}
