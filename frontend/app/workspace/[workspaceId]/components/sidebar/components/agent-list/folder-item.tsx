'use client'

import {
  Check,
  ChevronRight,
  ChevronDown,
  Copy,
  Folder,
  FolderOpen,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Trash2,
  X,
} from 'lucide-react'
import { useCallback, useState } from 'react'

import type {
  Folder as FolderType,
  AgentMetadata,
} from '@/app/workspace/[workspaceId]/components/sidebar/sidebar'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { AgentItem } from './agent-item'

export interface FolderItemProps {
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

export function FolderItem({
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
        <button type="button" className="flex flex-1 items-center gap-1.5" onClick={onToggle}>
          {folder.isExpanded ? (
            <ChevronDown className="h-3 w-3 flex-shrink-0 transition-all duration-100" />
          ) : (
            <ChevronRight className="h-3 w-3 flex-shrink-0 transition-all duration-100" />
          )}
          {folder.isExpanded ? (
            <FolderOpen className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-tertiary)]" />
          ) : (
            <Folder className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-tertiary)]" />
          )}
          {isEditing ? (
            <div className="flex flex-1 items-center gap-1 duration-150 animate-in fade-in">
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onBlur={handleSaveRename}
                onKeyDown={handleKeyDown}
                className="border-[var(--brand-primary)] ring-[var(--brand-primary)] focus:ring-[var(--brand-primary)] flex-1 rounded-sm border bg-[var(--surface-1)] px-1.5 py-[2px] text-xs-plus font-medium text-[var(--text-primary)] shadow-sm outline-none ring-2 transition-all focus:border-[var(--brand-primary)]"
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
              <button
                type="button"
                className="hover:bg-[var(--brand-primary)] flex h-5 w-5 items-center justify-center rounded-sm bg-[var(--brand-primary)] text-white shadow-sm transition-all active:scale-95"
                onClick={(e) => {
                  e.stopPropagation()
                  handleSaveRename()
                }}
              >
                <Check className="h-[10px] w-[10px]" strokeWidth={2.5} />
              </button>
              <button
                type="button"
                className="flex h-5 w-5 items-center justify-center rounded-sm bg-[var(--surface-5)] text-[var(--text-tertiary)] transition-all hover:bg-[var(--surface-9)] active:scale-95"
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
            className="rounded-sm p-0.5 opacity-0 transition-opacity group-hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation()
              setShowMenu(!showMenu)
            }}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>

          {showMenu && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowMenu(false)} />
              <div className="absolute right-0 top-[24px] z-50 min-w-[140px] rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-[4px] shadow-lg">
                {canCreateSubfolder && (
                  <button
                    type="button"
                    className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
                    onClick={() => {
                      setShowMenu(false)
                      onCreateSubfolder?.()
                    }}
                  >
                    <FolderPlus className="h-3 w-3" />
                    {t('workspace.newSubfolder')}
                  </button>
                )}
                <button
                  type="button"
                  className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={() => {
                    setShowMenu(false)
                    onDuplicate?.()
                  }}
                >
                  <Copy className="h-3 w-3" />
                  {t('workspace.duplicate')}
                </button>
                <div className="my-[4px] h-[1px] bg-[var(--border)]" />
                <button
                  type="button"
                  className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={() => {
                    setShowMenu(false)
                    setIsEditing(true)
                  }}
                >
                  <Pencil className="h-3 w-3" />
                  {t('workspace.rename')}
                </button>
                <button
                  type="button"
                  className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-[5px] text-xs-plus font-medium text-[var(--status-error)] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={() => {
                    setShowMenu(false)
                    onDelete()
                  }}
                >
                  <Trash2 className="h-3 w-3" />
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

          {agents.length === 0 && subfolders.length === 0 && (
            <div
              className={cn(
                'rounded-md py-2 text-app-xs font-normal',
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
