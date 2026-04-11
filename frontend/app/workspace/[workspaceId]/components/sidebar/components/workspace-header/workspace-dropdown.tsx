'use client'

import {
  Check,
  Copy,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState, useCallback, useMemo, useRef, useEffect } from 'react'

import { InlineRenameInput } from '@/components/ui/inline-rename-input'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { SidebarContextMenu, type MenuItemConfig } from '../sidebar-context-menu'

interface Workspace {
  id: string
  name: string
  ownerId?: string
  role?: string
  type?: string
}

interface WorkspaceDropdownProps {
  workspaceId: string
  workspaces: Workspace[]
  isWorkspacesLoading: boolean
  isCreatingWorkspace: boolean
  onWorkspaceSwitch?: (workspace: Workspace) => void
  onCreateWorkspace?: () => Promise<void>
  onClose: () => void
  getWorkspaceDisplayName: (workspace: Workspace) => string
  onStartRenameWithClose: (workspace: Workspace) => void
  onDeleteWorkspace: (wsId: string) => void
  onDuplicateWorkspace: (wsId: string) => void
  editingWorkspaceId: string | null
  editName: string
  setEditName: (name: string) => void
  onSaveWorkspaceRename: (wsId: string) => void
  onCancelWorkspaceRename: () => void
  onRenameKeyDown: (e: React.KeyboardEvent, wsId: string, isHeader?: boolean) => void
}

export function WorkspaceDropdown({
  workspaceId,
  workspaces,
  isWorkspacesLoading,
  isCreatingWorkspace,
  onWorkspaceSwitch,
  onCreateWorkspace,
  onClose,
  getWorkspaceDisplayName,
  onStartRenameWithClose,
  onDeleteWorkspace,
  onDuplicateWorkspace,
  editingWorkspaceId,
  editName,
  setEditName,
  onSaveWorkspaceRename,
  onCancelWorkspaceRename,
  onRenameKeyDown,
}: WorkspaceDropdownProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const [searchQuery, setSearchQuery] = useState('')
  const [showWorkspaceMenu, setShowWorkspaceMenu] = useState<string | null>(null)
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const menuButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  useEffect(() => {
    if (searchInputRef.current) {
      setTimeout(() => searchInputRef.current?.focus(), 100)
    }
  }, [])

  const filteredWorkspaces = useMemo(() => {
    if (!searchQuery.trim()) return workspaces
    const query = searchQuery.toLowerCase()
    return workspaces.filter((ws) => ws.name.toLowerCase().includes(query))
  }, [workspaces, searchQuery])

  useEffect(() => {
    if (showWorkspaceMenu) {
      const handleClickOutside = (e: MouseEvent) => {
        const target = e.target as HTMLElement
        if (
          !target.closest('[data-workspace-menu]') &&
          !target.closest('[data-workspace-menu-button]')
        ) {
          setShowWorkspaceMenu(null)
          setMenuPosition(null)
        }
      }

      document.addEventListener('mousedown', handleClickOutside)
      return () => {
        document.removeEventListener('mousedown', handleClickOutside)
      }
    }
  }, [showWorkspaceMenu])

  const handleCloseDropdown = useCallback(() => {
    onClose()
    setSearchQuery('')
  }, [onClose])

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={handleCloseDropdown} />
      <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-50 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-[4px] shadow-lg">
        <div className="flex items-center justify-between px-2 py-1">
          <span className="text-sm font-medium text-[var(--text-tertiary)]">
            {t('workspace.workspaces')}
          </span>
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="rounded-sm p-0.5 transition-colors hover:bg-[var(--surface-5)]"
                  onClick={async () => {
                    if (onCreateWorkspace) {
                      await onCreateWorkspace()
                    }
                  }}
                  disabled={isCreatingWorkspace}
                >
                  <Plus className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
                </button>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                sideOffset={4}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-sm font-medium text-[var(--text-primary)] shadow-lg"
              >
                {t('workspace.createWorkspace')}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <div className="mx-[4px] mb-[8px] mt-[4px]">
          <div className="flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-[5px]">
            <Search className="h-3 w-3 flex-shrink-0 text-[var(--text-tertiary)]" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('workspace.searchWorkspaces')}
              className="flex-1 bg-transparent text-sm font-medium text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)]"
            />
            {searchQuery && (
              <button
                type="button"
                className="rounded-xs p-px transition-colors hover:bg-[var(--surface-5)]"
                onClick={() => setSearchQuery('')}
                aria-label={t('workspace.clearSearch', { defaultValue: 'Clear search' })}
              >
                <X className="h-[10px] w-[10px] text-[var(--text-tertiary)]" />
              </button>
            )}
          </div>
        </div>

        <div className="max-h-[240px] overflow-y-auto">
          {isWorkspacesLoading ? (
            <div className="px-2 py-1.5 text-sm text-[var(--text-tertiary)]">
              {t('workspace.loadingAgents')}
            </div>
          ) : filteredWorkspaces.length === 0 ? (
            <div className="px-2 py-1.5 text-sm text-[var(--text-tertiary)]">
              {searchQuery ? t('workspace.noWorkspacesFound') : t('workspace.noWorkspaces')}
            </div>
          ) : (
            filteredWorkspaces.map((workspace) => (
              <div
                key={workspace.id}
                className={cn(
                  'group relative grid grid-cols-[1fr_auto_auto] items-center gap-1 rounded-md transition-colors',
                  workspace.id === workspaceId
                    ? 'bg-[var(--surface-muted)]'
                    : 'hover:bg-[var(--surface-5)]',
                )}
              >
                {editingWorkspaceId === workspace.id ? (
                  <div className="flex flex-1 items-center gap-1 px-2 py-1.5">
                    <InlineRenameInput
                      value={editName}
                      onChange={(v) => setEditName(v)}
                      onSave={() => onSaveWorkspaceRename(workspace.id)}
                      onCancel={onCancelWorkspaceRename}
                      size="sm"
                    />
                  </div>
                ) : (
                  <>
                    <TooltipProvider delayDuration={400}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className={cn(
                              'flex min-w-0 items-center px-2 py-1.5 text-left text-sm font-medium',
                              workspace.id === workspaceId
                                ? 'text-[var(--text-primary)]'
                                : 'text-[var(--text-secondary)]',
                            )}
                            onClick={() => {
                              if (onWorkspaceSwitch) {
                                onWorkspaceSwitch(workspace)
                              }
                              handleCloseDropdown()
                            }}
                          >
                            <span className="truncate">
                              {getWorkspaceDisplayName(workspace)}
                            </span>
                          </button>
                        </TooltipTrigger>
                        <TooltipContent
                          side="right"
                          sideOffset={8}
                          className="max-w-[280px] break-words rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-2.5 py-1.5 text-sm font-medium text-[var(--text-primary)] shadow-lg"
                        >
                          {getWorkspaceDisplayName(workspace)}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>

                    <div className="flex w-[44px] shrink-0 justify-center">
                      {workspace.type === 'personal' ? (
                        <span className="w-[36px] rounded-sm bg-[var(--brand-100)] px-[4px] py-[1px] text-center text-xs font-medium text-[var(--brand-600)]">
                          {t('workspace.personal')}
                        </span>
                      ) : workspace.type === 'team' ? (
                        <span className="w-[36px] rounded-sm bg-[var(--brand-100)] px-[4px] py-[1px] text-center text-xs font-medium text-[var(--brand-600)] dark:bg-[var(--brand-100)] dark:text-[var(--brand-400)]">
                          {t('workspace.team')}
                        </span>
                      ) : null}
                    </div>

                    <div className="mr-[4px] flex w-5 justify-end">
                      {workspace.type !== 'personal' && (
                        <button
                          ref={(el) => {
                            menuButtonRefs.current[workspace.id] = el
                          }}
                          data-workspace-menu-button
                          type="button"
                          className="rounded-sm p-[4px] opacity-0 transition-opacity hover:bg-[var(--surface-muted)] group-hover:opacity-100"
                          aria-label={t('workspace.moreOptions', { defaultValue: 'More options' })}
                          onClick={(e) => {
                            e.stopPropagation()
                            const button = menuButtonRefs.current[workspace.id]
                            if (button) {
                              const rect = button.getBoundingClientRect()
                              setMenuPosition({
                                x: rect.right - 120,
                                y: rect.bottom + 4,
                              })
                            }
                            setShowWorkspaceMenu(
                              showWorkspaceMenu === workspace.id ? null : workspace.id,
                            )
                          }}
                        >
                          <MoreHorizontal className="h-3 w-3 text-[var(--text-tertiary)]" />
                        </button>
                      )}
                    </div>
                  </>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {showWorkspaceMenu && menuPosition && (() => {
        const workspace = workspaces.find((w) => w.id === showWorkspaceMenu)
        if (!workspace || workspace.type === 'personal') return null

        const closeMenu = () => {
          setShowWorkspaceMenu(null)
          setMenuPosition(null)
        }

        const items: MenuItemConfig[] = []
        if (workspace.role === 'owner' || workspace.role === 'admin') {
          items.push({
            label: t('workspace.membersManagement'),
            icon: <Users className="h-3 w-3" />,
            onClick: () => router.push(`/workspace/${workspace.id}/settings/members`),
          })
        }
        items.push({
          label: t('workspace.rename'),
          icon: <Pencil className="h-3 w-3" />,
          onClick: () => onStartRenameWithClose(workspace),
          separator: items.length > 0,
        })
        items.push({
          label: t('workspace.duplicate'),
          icon: <Copy className="h-3 w-3" />,
          onClick: () => onDuplicateWorkspace(workspace.id),
        })
        items.push({
          label: t('workspace.delete'),
          icon: <Trash2 className="h-3 w-3" />,
          onClick: () => onDeleteWorkspace(workspace.id),
          variant: 'destructive',
          separator: true,
        })

        return (
          <SidebarContextMenu
            items={items}
            onClose={closeMenu}
            position={menuPosition}
          />
        )
      })()}
    </>
  )
}
