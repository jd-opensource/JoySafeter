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

import type {
  Folder as FolderType,
  AgentMetadata,
} from '@/app/workspace/[workspaceId]/components/sidebar/sidebar'
import { InlineRenameInput } from '@/components/ui/inline-rename-input'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useInlineRename } from '../inline-rename-input'
import { useDropZone } from '../../hooks/use-drop-zone'
import { SidebarContextMenu } from '../sidebar-context-menu'
import { AgentItem } from './agent-item'
import { useAgentListContext } from './agent-list-context'

export interface FolderItemProps {
  folder: FolderType
  agents: AgentMetadata[]
  subfolders: FolderType[]
  depth?: number
  onToggle: () => void
  onRename: (newName: string) => void
  onDelete: () => void
  onCreateSubfolder?: () => void
  onDuplicate?: () => void
  onDropAgent?: (agentId: string) => void
}

export function FolderItem({
  folder,
  agents,
  subfolders,
  depth = 0,
  onToggle,
  onRename,
  onDelete,
  onCreateSubfolder,
  onDuplicate,
  onDropAgent,
}: FolderItemProps) {
  const {
    activeAgentId,
    maxDepth,
    isDragActive,
    canEdit,
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
    onDragAgentStart,
    onDragAgentEnd,
  } = useAgentListContext()
  const { t } = useTranslation()
  const canCreateSubfolder = depth < maxDepth - 1
  const [showMenu, setShowMenu] = useState(false)

  const { isEditing, editName, setEditName, startEditing, handleSave: handleSaveRename, handleCancel: handleCancelRename } = useInlineRename(folder.name, onRename)
  const { isDragOver, handleDragOver, handleDragLeave, handleDrop } = useDropZone(onDropAgent)

  const indentPadding = depth * 12

  return (
    <div className="space-y-[2px]">
      {/* Folder Header */}
      <div
        className={cn(
          'group flex items-center rounded-md py-[5px] pr-[6px] text-[var(--text-secondary)] transition-all',
          isDragOver
            ? 'bg-[var(--brand-500)] ring-2 ring-[var(--brand-500)]'
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
            <InlineRenameInput
              value={editName}
              onChange={setEditName}
              onSave={handleSaveRename}
              onCancel={handleCancelRename}
              size="sm"
            />
          ) : (
            <TooltipProvider delayDuration={400}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="truncate text-base font-medium">{folder.name}</span>
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
            <SidebarContextMenu
              items={[
                ...(canCreateSubfolder
                  ? [{ label: t('workspace.newSubfolder'), icon: <FolderPlus className="h-3 w-3" />, onClick: () => onCreateSubfolder?.() }]
                  : []),
                { label: t('workspace.duplicate'), icon: <Copy className="h-3 w-3" />, onClick: () => onDuplicate?.() },
                { label: t('workspace.rename'), icon: <Pencil className="h-3 w-3" />, onClick: () => startEditing(), separator: true },
                { label: t('workspace.delete'), icon: <Trash2 className="h-3 w-3" />, onClick: onDelete, variant: 'destructive' as const },
              ]}
              onClose={() => setShowMenu(false)}
              className="right-0 top-[24px] min-w-[140px]"
            />
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
                depth={depth + 1}
                onToggle={() => onToggleFolder(subfolder.id)}
                onRename={(newName) => onRenameFolder(subfolder.id, newName)}
                onDelete={() => onDeleteFolder(subfolder.id)}
                onCreateSubfolder={() => onCreateSubfolderFor(subfolder.id)}
                onDuplicate={() => onDuplicateFolder(subfolder.id)}
                onDropAgent={(aId) => onMoveAgentToFolder(aId, subfolder.id)}
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
                'rounded-md py-2 text-sm font-normal',
                isDragOver
                  ? 'bg-[var(--brand-500)] text-[var(--text-secondary)]'
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
