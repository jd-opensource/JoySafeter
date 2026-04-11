'use client'

import { FolderPlus, Plus } from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useRef, useState, useEffect, useMemo } from 'react'

import type { AgentGraph } from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import {
  AgentList,
  WorkspaceHeader,
} from '@/app/workspace/[workspaceId]/components/sidebar/components'
import { CreateAgentDialog } from '@/app/workspace/[workspaceId]/components/sidebar/components/create-agent-dialog'
import { DeleteAgentDialog } from '@/app/workspace/[workspaceId]/components/sidebar/components/create-folder-dialog'
import { useAgentMutations } from '@/app/workspace/[workspaceId]/components/sidebar/hooks/use-agent-mutations'
import { useFolderHandlers } from '@/app/workspace/[workspaceId]/components/sidebar/hooks/use-folder-handlers'
import { useWorkspaceHandlers } from '@/app/workspace/[workspaceId]/components/sidebar/hooks/use-workspace-handlers'
import { SearchInput } from '@/components/ui/search-input'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import { useFolders } from '@/hooks/queries/folders'
import { useGraphs } from '@/hooks/queries/graphs'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useFolderStore, MAX_FOLDER_DEPTH, type WorkflowFolder } from '@/stores/folders/store'
import { MIN_SIDEBAR_WIDTH, useSidebarStore } from '@/stores/sidebar/store'

/**
 * Folder interface for component props (simplified from store)
 */
export interface Folder {
  id: string
  name: string
  isExpanded: boolean
  createdAt: Date
  parentId?: string | null
}

/**
 * Mock agent metadata type
 */
export interface AgentMetadata {
  id: string
  name: string
  color?: string
  folderId?: string | null
  graphMode?: string | null
}

function toFolder(wf: WorkflowFolder, expandedFolders: Set<string>): Folder {
  return {
    id: wf.id,
    name: wf.name,
    isExpanded: expandedFolders.has(wf.id),
    createdAt: wf.createdAt,
    parentId: wf.parentId,
  }
}

function graphToAgentMetadata(graph: AgentGraph): AgentMetadata {
  const variables = graph.variables as { graph_mode?: string } | undefined
  return {
    id: graph.id,
    name: graph.name,
    color: graph.color || undefined,
    folderId: graph.folderId || null,
    graphMode: variables?.graph_mode || null,
  }
}

/**
 * Sidebar component with resizable width that persists across page refreshes
 */
export function Sidebar() {
  const { t } = useTranslation()
  const params = useParams()
  const router = useRouter()
  const workspaceId = params.workspaceId as string
  const agentId = params.agentId as string | undefined
  const { toast } = useToast()

  const sidebarRef = useRef<HTMLElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)

  const [deleteAgentConfirmOpen, setDeleteAgentConfirmOpen] = useState(false)
  const [agentToDelete, setAgentToDelete] = useState<{ id: string; name: string } | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [newAgentName, setNewAgentName] = useState('')
  const [createAgentMode, setCreateAgentMode] = useState<'code' | 'canvas'>('canvas')
  const isCollapsed = useSidebarStore((state) => state.isCollapsed)
  const setIsCollapsed = useSidebarStore((state) => state.setIsCollapsed)
  const sidebarWidth = useSidebarStore((state) => state.sidebarWidth)
  const setSidebarWidth = useSidebarStore((state) => state.setSidebarWidth)
  const isAppSidebarCollapsed = useSidebarStore((state) => state.isAppSidebarCollapsed)

  const folderStoreData = useFolderStore((state) => state.folders)
  const expandedFolders = useFolderStore((state) => state.expandedFolders)
  const toggleExpanded = useFolderStore((state) => state.toggleExpanded)

  const { data: foldersData, isLoading: isFoldersLoading } = useFolders(workspaceId)
  const { data: workspacesData, isLoading: isWorkspacesLoading } = useWorkspaces()
  const { data: graphsData, isLoading: isAgentsLoading } = useGraphs(workspaceId)

  const agents: AgentMetadata[] = useMemo(() => graphsData?.map(graphToAgentMetadata) || [], [graphsData])

  const {
    createAgentMutation, updateAgentMutation, deleteAgentMutation,
    duplicateAgentMutation, handleMoveAgentToFolder,
  } = useAgentMutations(workspaceId)

  const {
    createFolderMutation, handleCreateFolder, handleRenameFolder,
    handleDeleteFolder, handleDuplicateFolder: handleDuplicateFolderBase,
  } = useFolderHandlers(workspaceId, userPermissions.canEdit)

  const handleDuplicateFolder = useCallback(
    (folderId: string) => handleDuplicateFolderBase(folderId, foldersData),
    [handleDuplicateFolderBase, foldersData],
  )

  const {
    createWorkspaceMutation, handleWorkspaceSwitch, handleCreateWorkspace,
    handleRenameWorkspace, handleDeleteWorkspace, handleDuplicateWorkspace,
  } = useWorkspaceHandlers(router)

  const folders: Folder[] = Object.values(folderStoreData)
    .filter((f) => f.workspaceId === workspaceId)
    .map((f) => toFolder(f, expandedFolders))

  const activeWorkspace = workspacesData?.find((w) => w.id === workspaceId) || workspacesData?.[0]
  const isOnAgentPage = !!agentId

  const generateRandomColor = useCallback(() => {
    const colors = [
      '#3972F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899',
      '#06B6D4', '#84CC16', '#F97316', '#6366F1', '#14B8A6', '#A855F7',
    ]
    return colors[Math.floor(Math.random() * colors.length)]
  }, [])

  const handleCreateAgent = useCallback(() => {
    if (!userPermissions.canEdit) {
      toast({ title: t('workspace.noPermission'), description: t('workspace.cannotCreateAgent'), variant: 'destructive' })
      return
    }
    setNewAgentName(t('workspace.defaultAgentName'))
    setCreateAgentMode('canvas')
    setShowCreateDialog(true)
  }, [userPermissions.canEdit, toast, t])

  const handleConfirmCreateAgent = useCallback(() => {
    if (!newAgentName.trim()) return
    setShowCreateDialog(false)
    createAgentMutation.mutate(
      { name: newAgentName.trim(), description: '', color: generateRandomColor(), mode: createAgentMode },
      { onSuccess: (graph: AgentGraph) => { if (graph?.id) router.push(`/workspace/${workspaceId}/${graph.id}`) } },
    )
  }, [newAgentName, createAgentMode, createAgentMutation, generateRandomColor, router, workspaceId])

  const handleToggleFolder = useCallback((folderId: string) => toggleExpanded(folderId), [toggleExpanded])

  useEffect(() => {
    if (searchQuery.trim() && folders.length > 0 && agents.length > 0) {
      const query = searchQuery.toLowerCase().trim()
      folders.forEach((folder) => {
        const agentsInFolder = agents.filter((a) => a.folderId === folder.id)
        const hasMatchingAgents = agentsInFolder.some((agent) => agent.name.toLowerCase().includes(query))
        const folderNameMatches = folder.name.toLowerCase().includes(query)
        if ((hasMatchingAgents || folderNameMatches) && !expandedFolders.has(folder.id)) {
          toggleExpanded(folder.id)
        }
      })
    }
  }, [searchQuery, folders, agents, expandedFolders, toggleExpanded])

  const handleRenameAgent = useCallback(
    (agentId: string, newName: string) => updateAgentMutation.mutate({ id: agentId, name: newName }),
    [updateAgentMutation],
  )

  const handleDeleteAgent = useCallback(
    (agentId: string) => {
      if (!userPermissions.canEdit) {
        toast({ title: t('workspace.noPermission'), description: t('workspace.cannotDeleteAgent'), variant: 'destructive' })
        return
      }
      const agent = agents.find((a) => a.id === agentId)
      if (!agent) return
      setAgentToDelete({ id: agentId, name: agent.name })
      setDeleteAgentConfirmOpen(true)
    },
    [agents, userPermissions.canEdit, toast, t],
  )

  const handleConfirmDeleteAgent = useCallback(() => {
    if (!agentToDelete) return
    deleteAgentMutation.mutate(agentToDelete.id)
    setDeleteAgentConfirmOpen(false)
    setAgentToDelete(null)
  }, [agentToDelete, deleteAgentMutation])

  const handleDuplicateAgent = useCallback(
    (agentId: string) => {
      if (!userPermissions.canEdit) {
        toast({ title: t('workspace.noPermission'), description: t('workspace.cannotCreateAgent'), variant: 'destructive' })
        return
      }
      duplicateAgentMutation.mutate(agentId)
    },
    [duplicateAgentMutation, userPermissions.canEdit, toast, t],
  )

  const handleToggleCollapse = useCallback(() => setIsCollapsed(!isCollapsed), [isCollapsed, setIsCollapsed])

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      const startX = e.clientX
      const startWidth = sidebarWidth
      const handleMouseMove = (e: MouseEvent) => {
        const delta = e.clientX - startX
        const newWidth = Math.max(MIN_SIDEBAR_WIDTH, startWidth + delta)
        setSidebarWidth(Math.min(newWidth, window.innerWidth * 0.3))
      }
      const handleMouseUp = () => {
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
      }
      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
    },
    [sidebarWidth, setSidebarWidth],
  )

  const workspaceHeaderProps = {
    activeWorkspace,
    workspaceId,
    workspaces: workspacesData || [],
    isWorkspacesLoading,
    isCreatingWorkspace: createWorkspaceMutation.isPending,
    onWorkspaceSwitch: handleWorkspaceSwitch,
    onCreateWorkspace: handleCreateWorkspace,
    onToggleCollapse: handleToggleCollapse,
    isCollapsed,
    showCollapseButton: true as const,
    onRenameWorkspace: handleRenameWorkspace,
    onDeleteWorkspace: handleDeleteWorkspace,
    onDuplicateWorkspace: handleDuplicateWorkspace,
  }

  if (isCollapsed) {
    return (
      <div
        className="fixed top-[14px] z-10 max-w-[232px] rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 transition-all duration-300"
        style={{ left: isAppSidebarCollapsed ? 'calc(var(--sidebar-width-collapsed) + 14px)' : 'calc(var(--sidebar-width) + 14px)' }}
      >
        <WorkspaceHeader {...workspaceHeaderProps} />
      </div>
    )
  }

  return (
    <>
      <aside
        ref={sidebarRef}
        className={cn(
          'sidebar-container fixed inset-y-0 overflow-hidden bg-[var(--surface-2)] transition-all duration-300',
          isCollapsed ? 'pointer-events-none z-0' : 'z-10',
        )}
        style={{
          left: isCollapsed ? '-1000px' : isAppSidebarCollapsed ? 'var(--sidebar-width-collapsed)' : 'var(--sidebar-width)',
          width: isCollapsed ? '0px' : `${sidebarWidth}px`,
          opacity: isCollapsed ? 0 : 1,
          visibility: isCollapsed ? 'hidden' : 'visible',
          transition: 'left 0.3s ease, width 0.3s ease, opacity 0.3s ease',
        }}
        aria-label="Workspace sidebar"
      >
        <div className="flex h-full flex-col border-r border-[var(--border)] pt-[14px]">
          <div className="flex-shrink-0 px-2.5">
            <WorkspaceHeader {...workspaceHeaderProps} />
          </div>

          <div className="mx-[5px] mt-[10px]">
            <SearchInput value={searchQuery} onValueChange={setSearchQuery} placeholder={t('workspace.searchAgents')} />
          </div>

          <div className="relative mt-[14px] flex flex-1 flex-col overflow-hidden">
            <div className="flex flex-shrink-0 items-center justify-between px-2.5">
              <span className="text-sm font-medium text-[var(--text-tertiary)]">{t('workspace.agents')}</span>
              <div className="flex items-center gap-2">
                <TooltipProvider delayDuration={100}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className={`rounded-sm p-0.5 transition-colors ${createFolderMutation.isPending || !userPermissions.canEdit ? 'cursor-not-allowed opacity-50' : 'hover:bg-[var(--surface-5)]'}`}
                        onClick={() => handleCreateFolder()}
                        disabled={createFolderMutation.isPending}
                      >
                        <FolderPlus className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" sideOffset={4} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-sm font-medium text-[var(--text-primary)] shadow-lg">
                      {t('workspace.createFolder')}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
                <TooltipProvider delayDuration={100}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className={`rounded-sm border border-[var(--border)] p-0.5 transition-colors ${createAgentMutation.isPending || !userPermissions.canEdit ? 'cursor-not-allowed opacity-50' : 'hover:bg-[var(--surface-5)]'}`}
                        onClick={handleCreateAgent}
                        disabled={createAgentMutation.isPending}
                      >
                        <Plus className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" sideOffset={4} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-sm font-medium text-[var(--text-primary)] shadow-lg">
                      {t('workspace.createAgent')}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>

            <div ref={scrollContainerRef} className="mt-[8px] flex-1 overflow-y-auto overflow-x-hidden px-[5px]">
              <AgentList
                regularAgents={agents}
                folders={folders}
                isLoading={isFoldersLoading || isAgentsLoading}
                searchQuery={searchQuery}
                onToggleFolder={handleToggleFolder}
                onRenameFolder={handleRenameFolder}
                onDeleteFolder={handleDeleteFolder}
                onMoveAgentToFolder={handleMoveAgentToFolder}
                onCreateSubfolder={handleCreateFolder}
                onDuplicateFolder={handleDuplicateFolder}
                maxFolderDepth={MAX_FOLDER_DEPTH}
                onRenameAgent={handleRenameAgent}
                onDeleteAgent={handleDeleteAgent}
                onDuplicateAgent={handleDuplicateAgent}
              />
            </div>
          </div>
        </div>
      </aside>

      {isOnAgentPage && (
        <div
          className="fixed bottom-0 top-0 z-20 w-[8px] cursor-ew-resize"
          style={{ left: `calc(${isAppSidebarCollapsed ? 'var(--sidebar-width-collapsed)' : 'var(--sidebar-width)'} + ${sidebarWidth - 4}px)` }}
          onMouseDown={handleMouseDown}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
        />
      )}

      <DeleteAgentDialog
        open={deleteAgentConfirmOpen}
        onOpenChange={setDeleteAgentConfirmOpen}
        agentToDelete={agentToDelete}
        onConfirm={handleConfirmDeleteAgent}
        onCancel={() => { setDeleteAgentConfirmOpen(false); setAgentToDelete(null) }}
      />

      <CreateAgentDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        newAgentName={newAgentName}
        setNewAgentName={setNewAgentName}
        createAgentMode={createAgentMode}
        setCreateAgentMode={setCreateAgentMode}
        onConfirm={handleConfirmCreateAgent}
      />
    </>
  )
}
