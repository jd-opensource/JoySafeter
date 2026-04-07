'use client'

import {
  ChevronRight,
  ChevronDown,
  Copy,
  Folder,
  FolderOpen,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'

import type { Folder as FolderType } from '@/app/workspace/[workspaceId]/components/sidebar/sidebar'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useInlineRename } from '../inline-rename-input'
import { useDropZone } from '../../hooks/use-drop-zone'
import { SidebarContextMenu } from '../sidebar-context-menu'
import { useAgentListActions } from './agent-list-context'
import { AgentItem } from './agent-item'

export interface FolderItemProps {
  folder: FolderType
  activeAgentId?: string
  depth?: number
  maxDepth: number
  isDragActive?: boolean
}

export function FolderItem({
  folder,
  activeAgentId,
  depth = 0,
  maxDepth,
  isDragActive = false,
}: FolderItemProps) {
  const { t } = useTranslation()
  const {
    onToggleFolder, onRenameFolder, onDeleteFolder, onCreateSubfolder,
    onDuplicateFolder, onMoveAgentToFolder, onDragAgentStart, onDragAgentEnd,
    onRenameAgent, onDeleteAgent, onDuplicateAgent,
    getAgentsInFolder, getSubfolders, canEdit,
  } = useAgentListActions()

  const agents = getAgentsInFolder(folder.id)
  const subfolders = getSubfolders(folder.id)
  const canCreateSubfolder = depth < maxDepth - 1
  const [showMenu, setShowMenu] = useState(false)

  const { isEditing, editName, setEditName, inputRef, startEditing, handleSave: handleSaveRename, handleKeyDown } = useInlineRename(
    folder.name,
    (newName) => onRenameFolder(folder.id, newName),
  )
  const { isDragOver, handleDragOver, handleDragLeave, handleDrop } = useDropZone(
    (agentId) => onMoveAgentToFolder(agentId, folder.id),
  )

  const indentPadding = depth * 12

  return (
    <div className="space-y-[2px]">
      {/* Folder Header */}
      <div
        className={cn(
          'group flex items-center rounded-md py-[5px] pr-1.5 text-[var(--text-secondary)] transition-all',
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
        <button
          type="button"
          className="flex flex-1 items-center gap-1.5"
          onClick={() => onToggleFolder(folder.id)}
        >
          {folder.isExpanded ? (
            <ChevronDown className="h-3 w-3 flex-shrink-0 text-[var(--text-muted)]" />
          ) : (
            <ChevronRight className="h-3 w-3 flex-shrink-0 text-[var(--text-muted)]" />
          )}
          {folder.isExpanded ? (
            <FolderOpen className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)]" />
          ) : (
            <Folder className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)]" />
          )}

          {isEditing ? (
            <div className="flex items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
              <input
                ref={inputRef}
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onBlur={handleSaveRename}
                onKeyDown={handleKeyDown}
                className="h-5 flex-1 rounded-sm border border-[var(--border)] bg-[var(--surface-elevated)] px-1 text-small outline-none focus:border-primary"
              />
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
        {canEdit && (
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
              <SidebarContextMenu
                items={[
                  ...(canCreateSubfolder
                    ? [{ label: t('workspace.newSubfolder'), icon: <FolderPlus className="h-3 w-3" />, onClick: () => onCreateSubfolder(folder.id) }]
                    : []),
                  { label: t('workspace.duplicate'), icon: <Copy className="h-3 w-3" />, onClick: () => onDuplicateFolder(folder.id) },
                  { label: t('workspace.rename'), icon: <Pencil className="h-3 w-3" />, onClick: () => startEditing(), separator: true },
                  { label: t('workspace.delete'), icon: <Trash2 className="h-3 w-3" />, onClick: () => onDeleteFolder(folder.id), variant: 'destructive' as const },
                ]}
                onClose={() => setShowMenu(false)}
                className="right-0 top-[24px] min-w-[140px]"
              />
            )}
          </div>
        )}
      </div>

      {/* Folder Contents (expanded) */}
      {folder.isExpanded && (
        <div className="space-y-[2px]">
          {depth < maxDepth - 1 &&
            subfolders.map((subfolder) => (
              <FolderItem
                key={subfolder.id}
                folder={subfolder}
                activeAgentId={activeAgentId}
                depth={depth + 1}
                maxDepth={maxDepth}
                isDragActive={isDragActive}
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
                  ? 'border border-dashed border-primary bg-primary/5 text-center text-primary'
                  : 'text-center text-[var(--text-muted)]',
              )}
              style={{ paddingLeft: `${20 + indentPadding}px` }}
            >
              {isDragOver ? t('workspace.dropHere') : t('workspace.emptyFolder')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
