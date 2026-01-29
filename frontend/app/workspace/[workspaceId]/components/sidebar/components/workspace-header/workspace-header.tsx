'use client'

import { Check, ChevronDown, Copy, MoreHorizontal, PanelLeft, Pencil, Plus, Search, Settings, Trash2, X, Users } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState, useCallback, useMemo, useRef, useEffect } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'



interface Workspace {
  id: string
  name: string
  ownerId?: string
  role?: string
  type?: string  // 'personal' | 'team'
}

interface WorkspaceHeaderProps {
  /**
   * The active workspace object
   */
  activeWorkspace?: { id?: string; name: string; type?: string } | null
  /**
   * Current workspace ID
   */
  workspaceId: string
  /**
   * List of available workspaces
   */
  workspaces?: Workspace[]
  /**
   * Whether workspaces are loading
   */
  isWorkspacesLoading?: boolean
  /**
   * Whether workspace creation is in progress
   */
  isCreatingWorkspace?: boolean
  /**
   * Callback when workspace is switched
   */
  onWorkspaceSwitch?: (workspace: Workspace) => void
  /**
   * Callback when create workspace is clicked
   */
  onCreateWorkspace?: () => Promise<void>
  /**
   * Callback when toggle collapse is clicked
   */
  onToggleCollapse?: () => void
  /**
   * Whether the sidebar is collapsed
   */
  isCollapsed?: boolean
  /**
   * Callback to rename the workspace
   */
  onRenameWorkspace?: (workspaceId: string, newName: string) => void
  /**
   * Callback to delete the workspace
   */
  onDeleteWorkspace?: (workspaceId: string) => void
  /**
   * Callback to duplicate the workspace
   */
  onDuplicateWorkspace?: (workspaceId: string) => void
  /**
   * Whether to show the collapse button
   */
  showCollapseButton?: boolean
}

/**
 * Workspace header component with search and rename support
 */
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
  const router = useRouter()
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [isRenaming, setIsRenaming] = useState(false)
  const [editingWorkspaceId, setEditingWorkspaceId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [showWorkspaceMenu, setShowWorkspaceMenu] = useState<string | null>(null)
  const [menuPosition, setMenuPosition] = useState<{ x: number; y: number } | null>(null)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [workspaceToDelete, setWorkspaceToDelete] = useState<{ id: string; name: string } | null>(null)
  const menuButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  
  const searchInputRef = useRef<HTMLInputElement>(null)
  const renameInputRef = useRef<HTMLInputElement>(null)

  /**
   * Get display name for workspace
   * If it's a personal workspace with default name, show translated name
   */
  const getWorkspaceDisplayName = useCallback((workspace: Workspace | { id?: string; name: string; type?: string }): string => {
    if (workspace.type === 'personal' && (workspace.name === '个人空间' || workspace.name === 'Personal Space')) {
      return t('workspace.personalSpace')
    }
    return workspace.name
  }, [t])

  useEffect(() => {
    if (isDropdownOpen && searchInputRef.current) {
      setTimeout(() => searchInputRef.current?.focus(), 100)
    }
  }, [isDropdownOpen])

  useEffect(() => {
    if (editingWorkspaceId && renameInputRef.current) {
      renameInputRef.current.focus()
      renameInputRef.current.select()
    }
  }, [editingWorkspaceId])
  const filteredWorkspaces = useMemo(() => {
    if (!searchQuery.trim()) return workspaces
    const query = searchQuery.toLowerCase()
    return workspaces.filter((ws) => ws.name.toLowerCase().includes(query))
  }, [workspaces, searchQuery])

  /**
   * Handle start renaming current workspace name in header
   */
  const handleStartHeaderRename = useCallback(() => {
    if (activeWorkspace?.type === 'personal') {
      return
    }
    const originalName = activeWorkspace?.name || ''
    setIsRenaming(true)
    setEditName(originalName)
  }, [activeWorkspace?.name, activeWorkspace?.type])

  /**
   * Handle save header rename
   */
  const handleSaveHeaderRename = useCallback(() => {
    if (activeWorkspace?.type === 'personal') {
      setIsRenaming(false)
      setEditName('')
      return
    }
    
    const trimmedName = editName.trim()
    const currentName = activeWorkspace?.name || ''
    const isDifferent = trimmedName !== currentName
    
    setIsRenaming(false)
    setEditName('')
    
    if (!trimmedName || !isDifferent || !onRenameWorkspace) {
      return
    }
    
    onRenameWorkspace(workspaceId, trimmedName)
  }, [editName, activeWorkspace?.name, activeWorkspace?.type, workspaceId, onRenameWorkspace])

  /**
   * Handle cancel header rename
   */
  const handleCancelHeaderRename = useCallback(() => {
    setIsRenaming(false)
    setEditName('')
  }, [])

  /**
   * Handle start renaming a workspace in dropdown
   */
  const handleStartWorkspaceRename = useCallback((workspace: Workspace) => {
    if (workspace.type === 'personal') {
      return
    }
    setEditingWorkspaceId(workspace.id)
    setEditName(workspace.name)
  }, [])

  /**
   * Handle save workspace rename in dropdown
   */
  const handleSaveWorkspaceRename = useCallback((wsId: string) => {
    const workspace = workspaces.find((w) => w.id === wsId)
    if (workspace?.type === 'personal') {
      setEditingWorkspaceId(null)
      setEditName('')
      return
    }
    const trimmedName = editName.trim()
    const currentName = workspace?.name || ''
    const isDifferent = trimmedName !== currentName
    
    setEditingWorkspaceId(null)
    setEditName('')
    
    if (!trimmedName || !isDifferent || !onRenameWorkspace) {
      return
    }
    
    onRenameWorkspace(wsId, trimmedName)
  }, [editName, onRenameWorkspace, workspaces])

  /**
   * Handle cancel workspace rename
   */
  const handleCancelWorkspaceRename = useCallback(() => {
    setEditingWorkspaceId(null)
    setEditName('')
  }, [])

  /**
   * Handle delete workspace - opens confirmation dialog
   */
  const handleDeleteWorkspace = useCallback((wsId: string) => {
    const workspace = workspaces.find((w) => w.id === wsId)
    if (workspace?.type === 'personal') {
      setShowWorkspaceMenu(null)
      setMenuPosition(null)
      return
    }
    
    setShowWorkspaceMenu(null)
    setMenuPosition(null)
    
    if (workspace) {
      setWorkspaceToDelete({ id: wsId, name: workspace.name })
      setDeleteConfirmOpen(true)
    }
  }, [workspaces])

  /**
   * Confirm delete workspace
   */
  const handleConfirmDelete = useCallback(() => {
    if (!workspaceToDelete || !onDeleteWorkspace) {
      setDeleteConfirmOpen(false)
      setWorkspaceToDelete(null)
      return
    }
    
    try {
      onDeleteWorkspace(workspaceToDelete.id)
      setDeleteConfirmOpen(false)
      setWorkspaceToDelete(null)
    } catch (error) {
      setDeleteConfirmOpen(false)
      setWorkspaceToDelete(null)
    }
  }, [workspaceToDelete, onDeleteWorkspace])

  /**
   * Handle duplicate workspace
   */
  const handleDuplicateWorkspace = useCallback((wsId: string) => {
    const workspace = workspaces.find((w) => w.id === wsId)
    if (workspace?.type === 'personal') {
      setShowWorkspaceMenu(null)
      setMenuPosition(null)
      return
    }
    
    setShowWorkspaceMenu(null)
    setMenuPosition(null)
    
    if (!onDuplicateWorkspace) {
      return
    }
    
    onDuplicateWorkspace(wsId)
  }, [onDuplicateWorkspace, workspaces])

  /**
   * Handle start workspace rename - also closes menu
   */
  const handleStartWorkspaceRenameWithClose = useCallback((workspace: Workspace) => {
    handleStartWorkspaceRename(workspace)
    setShowWorkspaceMenu(null)
    setMenuPosition(null)
  }, [handleStartWorkspaceRename])

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

  /**
   * Handle keyboard events for rename input
   */
  const handleRenameKeyDown = useCallback((e: React.KeyboardEvent, wsId: string, isHeader = false) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      e.stopPropagation()
      if (isHeader) {
        handleSaveHeaderRename()
      } else {
        handleSaveWorkspaceRename(wsId)
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      if (isHeader) {
        handleCancelHeaderRename()
      } else {
        handleCancelWorkspaceRename()
      }
    }
  }, [handleSaveHeaderRename, handleCancelHeaderRename, handleSaveWorkspaceRename, handleCancelWorkspaceRename])

  /**
   * Close dropdown and reset state
   */
  const handleCloseDropdown = useCallback(() => {
    setIsDropdownOpen(false)
    setSearchQuery('')
    setEditingWorkspaceId(null)
    setShowWorkspaceMenu(null)
  }, [])

  return (
    <div className='relative flex min-w-0 items-center justify-between gap-[6px]'>
      {/* Workspace Name */}
      <div className='flex min-w-0 flex-1 items-center gap-[6px]'>
        {isRenaming ? (
          <div className='flex flex-1 items-center gap-[4px]'>
            <input
              type='text'
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              onBlur={(e) => {
                setTimeout(() => {
                  handleSaveHeaderRename()
                }, 200)
              }}
              onKeyDown={(e) => handleRenameKeyDown(e, workspaceId, true)}
              className='flex-1 rounded-[4px] border border-[var(--brand-primary)] bg-transparent px-[5px] py-[2px] font-medium text-[13px] text-[var(--text-primary)] outline-none'
              autoFocus
              onClick={(e) => e.stopPropagation()}
            />
            <button
              type='button'
              className='rounded-[4px] p-[2px] text-[var(--brand-primary)] transition-colors hover:bg-[var(--surface-5)]'
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                handleSaveHeaderRename()
              }}
            >
              <Check className='h-[14px] w-[14px]' />
            </button>
            <button
              type='button'
              className='rounded-[4px] p-[2px] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-5)]'
              onClick={handleCancelHeaderRename}
            >
              <X className='h-[14px] w-[14px]' />
            </button>
          </div>
        ) : (
          <div className='group flex min-w-0 flex-1 items-center gap-[4px]'>
            <div className='flex min-w-0 items-center gap-[4px]'>
              <TooltipProvider delayDuration={100}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <h2 className='flex-1 truncate font-medium text-[13px] text-[var(--text-primary)]'>
                      {activeWorkspace ? getWorkspaceDisplayName(activeWorkspace) : t('workspace.workspace')}
                    </h2>
                  </TooltipTrigger>
                  <TooltipContent 
                    side='bottom' 
                    sideOffset={4}
                    className='rounded-[8px] border border-[var(--border)] bg-white px-[8px] py-[4px] text-[12px] font-medium text-black shadow-lg'
                  >
                    {activeWorkspace ? getWorkspaceDisplayName(activeWorkspace) : t('workspace.workspace')}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              {activeWorkspace?.type === 'personal' ? (
                <span className='shrink-0 w-[32px] text-center rounded-[4px] bg-blue-100 dark:bg-blue-900/30 px-[3px] py-[1px] text-[9px] font-medium text-blue-600 dark:text-blue-400'>
                  {t('workspace.personal')}
                </span>
              ) : activeWorkspace?.type === 'team' ? (
                <span className='shrink-0 w-[32px] text-center rounded-[4px] bg-purple-100 dark:bg-purple-900/30 px-[3px] py-[1px] text-[9px] font-medium text-purple-600 dark:text-purple-400'>
                  {t('workspace.team')}
                </span>
              ) : null}
            </div>
            {onRenameWorkspace && activeWorkspace?.type !== 'personal' && (
              <TooltipProvider delayDuration={100}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type='button'
                      className='rounded-[4px] p-[2px] opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[var(--surface-5)]'
                      onClick={handleStartHeaderRename}
                    >
                      <Pencil className='h-[12px] w-[12px] text-[var(--text-tertiary)]' />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent 
                    side='bottom' 
                    sideOffset={4}
                    className='rounded-[8px] border border-[var(--border)] bg-white px-[8px] py-[4px] text-[12px] font-medium text-black shadow-lg'
                  >
                    {t('workspace.renameWorkspace')}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        )}
      </div>

      {/* Workspace Actions */}
      <div className='flex items-center gap-[6px]'>
        {/* Workspace Switcher */}
        <TooltipProvider delayDuration={100}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type='button'
                className='flex items-center justify-center rounded-[4px] p-[4px] transition-colors hover:bg-[var(--surface-5)]'
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              >
                <ChevronDown
                  className={cn(
                    'h-[11px] w-[11px] text-[var(--text-secondary)] transition-transform duration-100',
                    isDropdownOpen && 'rotate-180'
                  )}
                />
              </button>
            </TooltipTrigger>
            <TooltipContent 
              side='bottom' 
              sideOffset={4}
              className='rounded-[8px] border border-[var(--border)] bg-white px-[8px] py-[4px] text-[12px] font-medium text-black shadow-lg'
            >
              {t('workspace.switchWorkspace')}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {/* Sidebar Collapse Toggle */}
        {showCollapseButton && (
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type='button'
                  className='flex items-center justify-center rounded-[4px] p-[4px] transition-colors hover:bg-[var(--surface-5)]'
                  onClick={onToggleCollapse}
                >
                  <PanelLeft className='h-[14px] w-[14px] text-[var(--text-secondary)]' />
                </button>
              </TooltipTrigger>
              <TooltipContent 
                side='bottom' 
                sideOffset={4}
                className='rounded-[8px] border border-[var(--border)] bg-white px-[8px] py-[4px] text-[12px] font-medium text-black shadow-lg'
              >
                {isCollapsed 
                  ? t('workspace.expandSidebar')
                  : t('workspace.collapseSidebar')
                }
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>

      {isDropdownOpen && (
        <>
          <div
            className='fixed inset-0 z-40'
            onClick={handleCloseDropdown}
          />
          <div className='absolute top-[calc(100%+4px)] left-0 right-0 z-50 rounded-[8px] border border-[var(--border)] bg-[var(--surface-1)] p-[4px] shadow-lg'>
                <div className='flex items-center justify-between px-[8px] py-[4px]'>
                  <span className='font-medium text-[11px] text-[var(--text-tertiary)]'>
                    {t('workspace.workspaces')}
                  </span>
                  <TooltipProvider delayDuration={100}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type='button'
                          className='rounded-[4px] p-[2px] transition-colors hover:bg-[var(--surface-5)]'
                          onClick={async () => {
                            if (onCreateWorkspace) {
                              await onCreateWorkspace()
                            }
                          }}
                          disabled={isCreatingWorkspace}
                        >
                          <Plus className='h-[14px] w-[14px] text-[var(--text-secondary)]' />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent 
                        side='bottom' 
                        sideOffset={4}
                        className='rounded-[8px] border border-[var(--border)] bg-white px-[8px] py-[4px] text-[12px] font-medium text-black shadow-lg'
                      >
                        {t('workspace.createWorkspace')}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>

                <div className='mx-[4px] mt-[4px] mb-[8px]'>
                  <div className='flex items-center gap-[6px] rounded-[6px] border border-[var(--border)] bg-[var(--surface-2)] px-[8px] py-[5px]'>
                    <Search className='h-[12px] w-[12px] flex-shrink-0 text-[var(--text-tertiary)]' />
                    <input
                      ref={searchInputRef}
                      type='text'
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder={t('workspace.searchWorkspaces')}
                      className='flex-1 bg-transparent font-medium text-[12px] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none'
                    />
                    {searchQuery && (
                      <button
                        type='button'
                        className='rounded-[2px] p-[1px] transition-colors hover:bg-[var(--surface-5)]'
                        onClick={() => setSearchQuery('')}
                      >
                        <X className='h-[10px] w-[10px] text-[var(--text-tertiary)]' />
                      </button>
                    )}
                  </div>
                </div>

                <div className='max-h-[240px] overflow-y-auto'>
                  {isWorkspacesLoading ? (
                    <div className='px-[8px] py-[6px] text-[12px] text-[var(--text-tertiary)]'>
                      {t('workspace.loadingAgents')}
                    </div>
                  ) : filteredWorkspaces.length === 0 ? (
                    <div className='px-[8px] py-[6px] text-[12px] text-[var(--text-tertiary)]'>
                      {searchQuery ? t('workspace.noWorkspacesFound') : t('workspace.noWorkspaces')}
                    </div>
                  ) : (
                    filteredWorkspaces.map((workspace) => (
                      <div
                        key={workspace.id}
                        className={cn(
                          'group relative grid grid-cols-[1fr_auto_auto] items-center gap-[4px] rounded-[6px] transition-colors',
                          workspace.id === workspaceId
                            ? 'bg-[var(--surface-9)]'
                            : 'hover:bg-[var(--surface-5)]'
                        )}
                      >
                        {editingWorkspaceId === workspace.id ? (
                          <div className='flex flex-1 items-center gap-[4px] px-[8px] py-[6px]'>
                            <input
                              ref={renameInputRef}
                              type='text'
                              value={editName}
                              onChange={(e) => setEditName(e.target.value)}
                              onBlur={() => {
                                setTimeout(() => {
                                  handleSaveWorkspaceRename(workspace.id)
                                }, 200)
                              }}
                              onKeyDown={(e) => handleRenameKeyDown(e, workspace.id)}
                              className='flex-1 rounded-[4px] border border-[var(--brand-primary)] bg-transparent px-[4px] py-[1px] font-medium text-[12px] text-[var(--text-primary)] outline-none'
                              onClick={(e) => e.stopPropagation()}
                            />
                            <button
                              type='button'
                              className='rounded-[4px] p-[2px] text-[var(--brand-primary)] transition-colors hover:bg-[var(--surface-5)]'
                              onClick={(e) => {
                                e.stopPropagation()
                                handleSaveWorkspaceRename(workspace.id)
                              }}
                            >
                              <Check className='h-[12px] w-[12px]' />
                            </button>
                            <button
                              type='button'
                              className='rounded-[4px] p-[2px] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--surface-5)]'
                              onClick={(e) => {
                                e.stopPropagation()
                                handleCancelWorkspaceRename()
                              }}
                            >
                              <X className='h-[12px] w-[12px]' />
                            </button>
                          </div>
                        ) : (
                          <>
                            <TooltipProvider delayDuration={400}>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <button
                                    type='button'
                                    className={cn(
                                      'flex items-center px-[8px] py-[6px] text-left font-medium text-[12px] min-w-0',
                                      workspace.id === workspaceId
                                        ? 'text-[var(--text-primary)]'
                                        : 'text-[var(--text-secondary)]'
                                    )}
                                    onClick={() => {
                                      if (onWorkspaceSwitch) {
                                        onWorkspaceSwitch(workspace)
                                      }
                                      handleCloseDropdown()
                                    }}
                                  >
                                    <span className='truncate'>{getWorkspaceDisplayName(workspace)}</span>
                                  </button>
                                </TooltipTrigger>
                                <TooltipContent 
                                  side='right' 
                                  sideOffset={8}
                                  className='max-w-[280px] break-words rounded-[8px] border border-[var(--border)] bg-[var(--surface-1)] px-[10px] py-[6px] text-[12px] font-medium text-[var(--text-primary)] shadow-lg'
                                >
                                  {getWorkspaceDisplayName(workspace)}
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                            
                            <div className='shrink-0 w-[44px] flex justify-center'>
                              {workspace.type === 'personal' ? (
                                <span className='w-[36px] text-center rounded-[4px] bg-blue-100 dark:bg-blue-900/30 px-[4px] py-[1px] text-[10px] font-medium text-blue-600 dark:text-blue-400'>
                                  {t('workspace.personal')}
                                </span>
                              ) : workspace.type === 'team' ? (
                                <span className='w-[36px] text-center rounded-[4px] bg-purple-100 dark:bg-purple-900/30 px-[4px] py-[1px] text-[10px] font-medium text-purple-600 dark:text-purple-400'>
                                  {t('workspace.team')}
                                </span>
                              ) : null}
                            </div>

                            <div className='w-[20px] mr-[4px] flex justify-end'>
                              {workspace.type !== 'personal' && (
                                <button
                                  ref={(el) => {
                                    menuButtonRefs.current[workspace.id] = el
                                  }}
                                  data-workspace-menu-button
                                  type='button'
                                  className='rounded-[4px] p-[4px] opacity-0 transition-opacity group-hover:opacity-100 hover:bg-[var(--surface-9)]'
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
                                    setShowWorkspaceMenu(showWorkspaceMenu === workspace.id ? null : workspace.id)
                                  }}
                                >
                                  <MoreHorizontal className='h-[12px] w-[12px] text-[var(--text-tertiary)]' />
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
        </>
      )}

      {showWorkspaceMenu && menuPosition && (
        <>
          <div
            className='fixed inset-0 z-[100]'
            onClick={() => {
              setShowWorkspaceMenu(null)
              setMenuPosition(null)
            }}
          />
          <div
            data-workspace-menu
            className='fixed z-[101] min-w-[120px] rounded-[8px] border border-[var(--border)] bg-[var(--surface-1)] p-[4px] shadow-lg'
            style={{
              left: `${menuPosition.x}px`,
              top: `${menuPosition.y}px`,
            }}
          >
            {(() => {
              const workspace = workspaces.find((w) => w.id === showWorkspaceMenu)
              if (!workspace) return null

              if (workspace.type === 'personal') {
                return null
              }

              return (
                <>
                  <button
                    type='button'
                    className='flex w-full items-center gap-[8px] rounded-[6px] px-[8px] py-[6px] font-medium text-[12px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]'
                    onClick={(e) => {
                      e.stopPropagation()
                      router.push(`/workspace/${workspace.id}/settings/members`)
                      setShowWorkspaceMenu(null)
                      setMenuPosition(null)
                    }}
                  >
                    <Users className='h-[12px] w-[12px]' />
                    {t('workspace.membersManagement')}
                  </button>
                  <div className='my-[4px] h-[1px] bg-[var(--border)]' />
                  <button
                    type='button'
                    className='flex w-full items-center gap-[8px] rounded-[6px] px-[8px] py-[6px] font-medium text-[12px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]'
                    onClick={(e) => {
                      e.stopPropagation()
                      handleStartWorkspaceRenameWithClose(workspace)
                    }}
                  >
                    <Pencil className='h-[12px] w-[12px]' />
                    {t('workspace.rename')}
                  </button>
                  <button
                    type='button'
                    className='flex w-full items-center gap-[8px] rounded-[6px] px-[8px] py-[6px] font-medium text-[12px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]'
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDuplicateWorkspace(workspace.id)
                    }}
                  >
                    <Copy className='h-[12px] w-[12px]' />
                    {t('workspace.duplicate')}
                  </button>
                  <div className='my-[4px] h-[1px] bg-[var(--border)]' />
                  <button
                    type='button'
                    className='flex w-full items-center gap-[8px] rounded-[6px] px-[8px] py-[6px] font-medium text-[12px] text-[#ef4444] transition-colors hover:bg-[var(--surface-5)]'
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDeleteWorkspace(workspace.id)
                    }}
                  >
                    <Trash2 className='h-[12px] w-[12px]' />
                    {t('workspace.delete')}
                  </button>
                </>
              )
            })()}
          </div>
        </>
      )}

      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent variant="destructive">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.deleteConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {workspaceToDelete ? (
                <>
                  {t('workspace.deleteConfirmMessagePrefix')}{' '}
                  <span className='font-semibold text-[#ef4444]'>{workspaceToDelete.name}</span>
                  {t('workspace.deleteConfirmMessageSuffix')}
                </>
              ) : (
                t('workspace.deleteConfirmMessageDefault')
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => {
              setDeleteConfirmOpen(false)
              setWorkspaceToDelete(null)
            }}>
              {t('workspace.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className='bg-[#ef4444] text-white hover:bg-[#dc2626]'
            >
              {t('workspace.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
