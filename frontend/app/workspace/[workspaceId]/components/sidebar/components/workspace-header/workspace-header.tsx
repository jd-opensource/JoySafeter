'use client'

import { ChevronDown, PanelLeft, Pencil } from 'lucide-react'
import { useState, useCallback } from 'react'

import { InlineRenameInput } from '@/components/ui/inline-rename-input'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useInlineRename } from '../inline-rename-input'
import { useWorkspaceRename } from './use-workspace-rename'
import { WorkspaceDialogs } from './workspace-dialogs'
import { WorkspaceDropdown } from './workspace-dropdown'

interface Workspace {
  id: string
  name: string
  ownerId?: string
  role?: string
  type?: string
}

interface WorkspaceHeaderProps {
  activeWorkspace?: { id?: string; name: string; type?: string } | null
  workspaceId: string
  workspaces?: Workspace[]
  isWorkspacesLoading?: boolean
  isCreatingWorkspace?: boolean
  onWorkspaceSwitch?: (workspace: Workspace) => void
  onCreateWorkspace?: () => Promise<void>
  onToggleCollapse?: () => void
  isCollapsed?: boolean
  onRenameWorkspace?: (workspaceId: string, newName: string) => void
  onDeleteWorkspace?: (workspaceId: string) => void
  onDuplicateWorkspace?: (workspaceId: string) => void
  showCollapseButton?: boolean
}

export function WorkspaceHeader({
  activeWorkspace,
  workspaceId,
  workspaces = [],
  isWorkspacesLoading = false,
  isCreatingWorkspace = false,
  onWorkspaceSwitch,
  onCreateWorkspace,
  onToggleCollapse,
  isCollapsed = false,
  onRenameWorkspace,
  onDeleteWorkspace,
  onDuplicateWorkspace,
  showCollapseButton = true,
}: WorkspaceHeaderProps) {
  const { t } = useTranslation()
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)

  const handleHeaderRename = useCallback((newName: string) => {
    if (activeWorkspace?.type === 'personal') return
    onRenameWorkspace?.(workspaceId, newName)
  }, [activeWorkspace?.type, workspaceId, onRenameWorkspace])

  const {
    isEditing: isRenaming, editName, setEditName,
    startEditing: handleStartHeaderRename, handleSave: handleSaveHeaderRename,
    handleCancel: handleCancelHeaderRename,
  } = useInlineRename(activeWorkspace?.name || '', handleHeaderRename)

  const {
    editingWorkspaceId, setEditingWorkspaceId,
    editName: dropdownEditName, setEditName: setDropdownEditName,
    deleteConfirmOpen, setDeleteConfirmOpen,
    workspaceToDelete, setWorkspaceToDelete,
    handleSaveWorkspaceRename, handleCancelWorkspaceRename,
    handleDeleteWorkspace, handleConfirmDelete, handleDuplicateWorkspace,
    handleStartWorkspaceRenameWithClose, handleRenameKeyDown,
  } = useWorkspaceRename(activeWorkspace, workspaceId, workspaces, onRenameWorkspace, onDeleteWorkspace, onDuplicateWorkspace)

  const getWorkspaceDisplayName = useCallback(
    (workspace: Workspace | { id?: string; name: string; type?: string }): string => {
      if (workspace.type === 'personal' && (workspace.name === '个人空间' || workspace.name === 'Personal Space')) {
        return t('workspace.personalSpace')
      }
      return workspace.name
    },
    [t],
  )

  return (
    <div className="relative flex min-w-0 items-center justify-between gap-1.5">
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        {isRenaming ? (
          <InlineRenameInput
            value={editName}
            onChange={setEditName}
            onSave={handleSaveHeaderRename}
            onCancel={handleCancelHeaderRename}
            size="sm"
          />
        ) : (
          <div className="group flex min-w-0 flex-1 items-center gap-1">
            <div className="flex min-w-0 items-center gap-1">
              <TooltipProvider delayDuration={100}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <h2 className="flex-1 truncate text-small font-medium text-[var(--text-primary)]">
                      {activeWorkspace ? getWorkspaceDisplayName(activeWorkspace) : t('workspace.workspace')}
                    </h2>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" sideOffset={4} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs-plus font-medium text-[var(--text-primary)] shadow-lg">
                    {activeWorkspace ? getWorkspaceDisplayName(activeWorkspace) : t('workspace.workspace')}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              {activeWorkspace?.type === 'personal' ? (
                <span className="w-[32px] shrink-0 rounded-sm bg-[var(--brand-100)] px-[3px] py-[1px] text-center text-micro font-medium text-[var(--brand-600)]">
                  {t('workspace.personal')}
                </span>
              ) : activeWorkspace?.type === 'team' ? (
                <span className="w-[32px] shrink-0 rounded-sm bg-purple-100 px-[3px] py-[1px] text-center text-micro font-medium text-purple-600 dark:bg-purple-900/30 dark:text-purple-400">
                  {t('workspace.team')}
                </span>
              ) : null}
            </div>
            {onRenameWorkspace && activeWorkspace?.type !== 'personal' && (
              <TooltipProvider delayDuration={100}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="rounded-sm p-0.5 opacity-0 transition-opacity hover:bg-[var(--surface-5)] group-hover:opacity-100"
                      onClick={handleStartHeaderRename}
                    >
                      <Pencil className="h-3 w-3 text-[var(--text-tertiary)]" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" sideOffset={4} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs-plus font-medium text-[var(--text-primary)] shadow-lg">
                    {t('workspace.renameWorkspace')}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <TooltipProvider delayDuration={100}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="flex items-center justify-center rounded-sm p-[4px] transition-colors hover:bg-[var(--surface-5)]"
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              >
                <ChevronDown className={cn('h-[11px] w-[11px] text-[var(--text-secondary)] transition-transform duration-100', isDropdownOpen && 'rotate-180')} />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" sideOffset={4} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs-plus font-medium text-[var(--text-primary)] shadow-lg">
              {t('workspace.switchWorkspace')}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {showCollapseButton && (
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="flex items-center justify-center rounded-sm p-[4px] transition-colors hover:bg-[var(--surface-5)]"
                  onClick={onToggleCollapse}
                >
                  <PanelLeft className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" sideOffset={4} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs-plus font-medium text-[var(--text-primary)] shadow-lg">
                {isCollapsed ? t('workspace.expandSidebar') : t('workspace.collapseSidebar')}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>

      {isDropdownOpen && (
        <WorkspaceDropdown
          workspaceId={workspaceId}
          workspaces={workspaces}
          isWorkspacesLoading={isWorkspacesLoading}
          isCreatingWorkspace={isCreatingWorkspace}
          onWorkspaceSwitch={onWorkspaceSwitch}
          onCreateWorkspace={onCreateWorkspace}
          onClose={() => { setIsDropdownOpen(false); setEditingWorkspaceId(null) }}
          getWorkspaceDisplayName={getWorkspaceDisplayName}
          onStartRenameWithClose={handleStartWorkspaceRenameWithClose}
          onDeleteWorkspace={handleDeleteWorkspace}
          onDuplicateWorkspace={handleDuplicateWorkspace}
          editingWorkspaceId={editingWorkspaceId}
          editName={dropdownEditName}
          setEditName={setDropdownEditName}
          onSaveWorkspaceRename={handleSaveWorkspaceRename}
          onCancelWorkspaceRename={handleCancelWorkspaceRename}
          onRenameKeyDown={handleRenameKeyDown}
        />
      )}

      <WorkspaceDialogs
        deleteConfirmOpen={deleteConfirmOpen}
        setDeleteConfirmOpen={setDeleteConfirmOpen}
        workspaceToDelete={workspaceToDelete}
        setWorkspaceToDelete={setWorkspaceToDelete}
        onConfirmDelete={handleConfirmDelete}
      />
    </div>
  )
}
