'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderPlus, Plus } from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useRef, useState, useEffect, useMemo } from 'react'

import {
  agentService,
  type AgentGraph,
} from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { useBuilderStore } from '@/app/workspace/[workspaceId]/[agentId]/stores/builderStore'
import { DSL_STARTER_TEMPLATE } from '@/app/workspace/[workspaceId]/[agentId]/utils/dslTemplate'
import {
  AgentList,
  WorkspaceHeader,
} from '@/app/workspace/[workspaceId]/components/sidebar/components'
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
import { SearchInput } from '@/components/ui/search-input'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/components/ui/use-toast'
import {
  useFolders,
  useCreateFolder,
  useUpdateFolder,
  useDeleteFolderMutation as useDeleteFolder,
  useDuplicateFolderMutation as useDuplicateFolder,
} from '@/hooks/queries/folders'
import { useGraphs, graphKeys } from '@/hooks/queries/graphs'
import {
  useWorkspaces,
  useCreateWorkspace,
  useUpdateWorkspace,
  useDeleteWorkspace,
  useDuplicateWorkspace,
} from '@/hooks/queries/workspaces'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useTranslation } from '@/lib/i18n'
import { createLogger } from '@/lib/logs/console/logger'
import { cn } from '@/lib/utils'
import { useFolderStore, MAX_FOLDER_DEPTH, type WorkflowFolder } from '@/stores/folders/store'
import { MIN_SIDEBAR_WIDTH, useSidebarStore } from '@/stores/sidebar/store'

const logger = createLogger('Sidebar')

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

/**
 * Convert WorkflowFolder to Folder for component props
 */
function toFolder(wf: WorkflowFolder, expandedFolders: Set<string>): Folder {
  return {
    id: wf.id,
    name: wf.name,
    isExpanded: expandedFolders.has(wf.id),
    createdAt: wf.createdAt,
    parentId: wf.parentId,
  }
}

/**
 * Convert AgentGraph to AgentMetadata
 */
function graphToAgentMetadata(graph: AgentGraph): AgentMetadata {
  return {
    id: graph.id,
    name: graph.name,
    color: graph.color || undefined,
    folderId: graph.folderId || null,
    graphMode: (graph as any).variables?.graph_mode || null,
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
  const [createAgentMode, setCreateAgentMode] = useState<'dsl' | 'canvas'>('dsl')
  const isCollapsed = useSidebarStore((state) => state.isCollapsed)
  const setIsCollapsed = useSidebarStore((state) => state.setIsCollapsed)
  const sidebarWidth = useSidebarStore((state) => state.sidebarWidth)
  const setSidebarWidth = useSidebarStore((state) => state.setSidebarWidth)
  const isAppSidebarCollapsed = useSidebarStore((state) => state.isAppSidebarCollapsed)

  const folderStoreData = useFolderStore((state) => state.folders)
  const expandedFolders = useFolderStore((state) => state.expandedFolders)
  const toggleExpanded = useFolderStore((state) => state.toggleExpanded)
  const canCreateSubfolder = useFolderStore((state) => state.canCreateSubfolder)

  const { data: foldersData, isLoading: isFoldersLoading } = useFolders(workspaceId)
  const createFolderMutation = useCreateFolder()
  const updateFolderMutation = useUpdateFolder()
  const deleteFolderMutation = useDeleteFolder()
  const duplicateFolderMutation = useDuplicateFolder()

  const { data: workspacesData, isLoading: isWorkspacesLoading } = useWorkspaces()
  const createWorkspaceMutation = useCreateWorkspace()
  const updateWorkspaceMutation = useUpdateWorkspace()
  const deleteWorkspaceMutation = useDeleteWorkspace()
  const duplicateWorkspaceMutation = useDuplicateWorkspace()
  const queryClient = useQueryClient()

  // Use unified useGraphs hook to ensure cache sharing with other components
  const { data: graphsData, isLoading: isAgentsLoading } = useGraphs(workspaceId)

  const agents: AgentMetadata[] = useMemo(() => graphsData?.map(graphToAgentMetadata) || [], [graphsData])

  const createAgentMutation = useMutation({
    mutationFn: async (data: { name: string; description?: string; color?: string; mode?: 'canvas' | 'dsl' }) => {
      // Create Graph
      const graph = await agentService.createGraph({
        name: data.name,
        description: data.description,
        color: data.color,
        workspaceId: workspaceId || null,
      })

      if (graph?.id) {
        if (data.mode === 'dsl') {
          // DSL mode: save with starter template and graph_mode flag
          await agentService.saveGraphState({
            graphId: graph.id,
            nodes: [],
            edges: [],
            viewport: { x: 0, y: 0, zoom: 1 },
            variables: {
              graph_mode: 'dsl',
              dsl_code: DSL_STARTER_TEMPLATE,
            },
          })
        } else {
          await agentService.saveGraphState({
            graphId: graph.id,
            nodes: [],
            edges: [],
            viewport: { x: 0, y: 0, zoom: 1 },
          })
        }
      }
      return graph
    },
    onSuccess: (graph: AgentGraph) => {
      // Refresh agent list
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })

      // Show success toast
      toast({
        title: t('workspace.agentCreateSuccess'),
        variant: 'success',
      })

      // Automatically navigate to the newly created agent
      if (graph?.id) {
        router.push(`/workspace/${workspaceId}/${graph.id}`)
      }
    },
    onError: (error: unknown) => {
      let errorMessage = t('workspace.cannotCreateAgent')
      if (error instanceof Error) {
        const isPermissionError =
          error.message.includes('403') ||
          error.message.includes('permission') ||
          error.message.includes('Forbidden') ||
          error.message.includes('insufficient') ||
          error.message.includes('Insufficient')

        if (isPermissionError) {
          errorMessage = t('workspace.cannotCreateAgent')
        } else {
          errorMessage = error.message || errorMessage
        }
      }
      toast({
        title: t('workspace.agentCreateFailed'),
        description: errorMessage,
        variant: 'destructive',
      })
    },
  })

  const updateAgentMutation = useMutation({
    mutationFn: async (data: {
      id: string
      name?: string
      description?: string
      color?: string
    }) => {
      await agentService.updateGraph(data.id, {
        name: data.name,
        description: data.description,
        color: data.color,
      })
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      // If renaming the currently editing graph, update graphName in store
      const { graphId, setGraphName } = useBuilderStore.getState()
      if (variables.name && graphId === variables.id) {
        setGraphName(variables.name)
        // Also update localStorage for compatibility
        agentService.setCachedGraphName(variables.name)
      }
      toast({
        title: t('workspace.agentUpdateSuccess'),
        variant: 'success',
      })
    },
    onError: (error: unknown) => {
      let errorMessage = t('workspace.agentUpdateFailed')
      if (error instanceof Error) {
        errorMessage = error.message || errorMessage
      }
      toast({
        title: t('workspace.agentUpdateFailed'),
        description: errorMessage,
        variant: 'destructive',
      })
    },
  })

  const deleteAgentMutation = useMutation({
    mutationFn: async (id: string) => {
      await agentService.deleteGraph(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      toast({
        title: t('workspace.agentDeleteSuccess'),
        variant: 'success',
      })
    },
    onError: (error: unknown) => {
      let errorMessage = t('workspace.cannotDeleteAgent')
      if (error instanceof Error) {
        const isPermissionError =
          error.message.includes('403') ||
          error.message.includes('permission') ||
          error.message.includes('Forbidden') ||
          error.message.includes('insufficient') ||
          error.message.includes('Insufficient')

        if (isPermissionError) {
          errorMessage = t('workspace.cannotDeleteAgent')
        } else {
          errorMessage = error.message || errorMessage
        }
      }
      toast({
        title: t('workspace.agentDeleteFailed'),
        description: errorMessage,
        variant: 'destructive',
      })
    },
  })

  const duplicateAgentMutation = useMutation({
    mutationFn: async (id: string) => {
      await agentService.duplicateGraph(id, { workspaceId: workspaceId || null })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      toast({
        title: t('workspace.agentDuplicateSuccess'),
        variant: 'success',
      })
    },
    onError: (error: unknown) => {
      let errorMessage = t('workspace.agentDuplicateFailed')
      if (error instanceof Error) {
        const isPermissionError =
          error.message.includes('403') ||
          error.message.includes('permission') ||
          error.message.includes('Forbidden') ||
          error.message.includes('insufficient') ||
          error.message.includes('Insufficient')

        if (isPermissionError) {
          errorMessage = t('workspace.cannotCreateAgent')
        } else {
          errorMessage = error.message || errorMessage
        }
      }
      toast({
        title: t('workspace.agentDuplicateFailed'),
        description: errorMessage,
        variant: 'destructive',
      })
    },
  })

  const folders: Folder[] = Object.values(folderStoreData)
    .filter((f) => f.workspaceId === workspaceId)
    .map((f) => toFolder(f, expandedFolders))

  const activeWorkspace = workspacesData?.find((w) => w.id === workspaceId) || workspacesData?.[0]
  const isOnAgentPage = !!agentId

  const generateRandomColor = useCallback(() => {
    const colors = [
      '#3972F6',
      '#10B981',
      '#F59E0B',
      '#EF4444',
      '#8B5CF6',
      '#EC4899',
      '#06B6D4',
      '#84CC16',
      '#F97316',
      '#6366F1',
      '#14B8A6',
      '#A855F7',
    ]
    return colors[Math.floor(Math.random() * colors.length)]
  }, [])

  const handleCreateAgent = useCallback(() => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotCreateAgent'),
        variant: 'destructive',
      })
      return
    }
    setNewAgentName(t('workspace.defaultAgentName'))
    setCreateAgentMode('dsl')
    setShowCreateDialog(true)
  }, [userPermissions.canEdit, toast, t])

  const handleConfirmCreateAgent = useCallback(() => {
    if (!newAgentName.trim()) return
    setShowCreateDialog(false)
    createAgentMutation.mutate({
      name: newAgentName.trim(),
      description: '',
      color: generateRandomColor(),
      mode: createAgentMode,
    })
  }, [newAgentName, createAgentMode, createAgentMutation, generateRandomColor])

  /**
   * Handle create folder (root level)
   */
  const handleCreateFolder = useCallback(
    async (parentId?: string | null) => {
      if (!userPermissions.canEdit) {
        toast({
          title: t('workspace.noPermission'),
          description: t('workspace.cannotCreateFolder'),
          variant: 'destructive',
        })
        return
      }
      if (parentId && !canCreateSubfolder(parentId)) {
        return
      }

      const defaultFolderName = t('workspace.defaultFolderName')
      createFolderMutation.mutate({
        workspaceId,
        name: defaultFolderName,
        parentId: parentId || undefined,
      })
    },
    [
      workspaceId,
      createFolderMutation,
      canCreateSubfolder,
      t,
      userPermissions.canEdit,
      toast,
    ],
  )

  /**
   * Handle toggle folder expand/collapse
   */
  const handleToggleFolder = useCallback(
    (folderId: string) => {
      toggleExpanded(folderId)
    },
    [toggleExpanded],
  )

  useEffect(() => {
    if (searchQuery.trim() && folders.length > 0 && agents.length > 0) {
      const query = searchQuery.toLowerCase().trim()
      folders.forEach((folder) => {
        const agentsInFolder = agents.filter((a) => a.folderId === folder.id)
        const hasMatchingAgents = agentsInFolder.some((agent) =>
          agent.name.toLowerCase().includes(query),
        )
        const folderNameMatches = folder.name.toLowerCase().includes(query)

        if ((hasMatchingAgents || folderNameMatches) && !expandedFolders.has(folder.id)) {
          toggleExpanded(folder.id)
        }
      })
    }
  }, [searchQuery, folders, agents, expandedFolders, toggleExpanded])

  /**
   * Handle rename folder
   */
  const handleRenameFolder = useCallback(
    (folderId: string, newName: string) => {
      updateFolderMutation.mutate({
        workspaceId,
        id: folderId,
        updates: { name: newName },
      })
    },
    [workspaceId, updateFolderMutation],
  )

  /**
   * Handle delete folder
   */
  const handleDeleteFolder = useCallback(
    (folderId: string) => {
      if (!userPermissions.canEdit) {
        toast({
          title: t('workspace.noPermission'),
          description: t('workspace.cannotDeleteFolder'),
          variant: 'destructive',
        })
        return
      }
      deleteFolderMutation.mutate(
        { workspaceId, id: folderId },
        {
          onError: (error: unknown) => {
            // Check if it's a permission error (403 or contains permission-related keywords)
            let errorMessage = t('workspace.cannotDeleteFolder')
            if (error instanceof Error) {
              const isPermissionError =
                error.message.includes('403') ||
                error.message.includes('permission') ||
                error.message.includes('Forbidden') ||
                error.message.includes('insufficient') ||
                error.message.includes('Insufficient')

              if (isPermissionError) {
                errorMessage = t('workspace.cannotDeleteFolder')
              } else {
                errorMessage = error.message || errorMessage
              }
            }
            toast({
              title: t('workspace.noPermission'),
              description: errorMessage,
              variant: 'destructive',
            })
          },
        },
      )
    },
    [workspaceId, deleteFolderMutation, userPermissions.canEdit, toast, t],
  )

  /**
   * Handle duplicate folder
   */
  const handleDuplicateFolder = useCallback(
    (folderId: string) => {
      if (!userPermissions.canEdit) {
        toast({
          title: t('workspace.noPermission'),
          description: t('workspace.cannotCreateFolder'),
          variant: 'destructive',
        })
        return
      }
      const folder = folderStoreData[folderId] || foldersData?.find((f) => f.id === folderId)
      if (!folder) {
        return
      }

      duplicateFolderMutation.mutate(
        {
          workspaceId,
          id: folderId,
          name: `${folder.name} (Copy)`,
          parentId: folder.parentId,
          color: folder.color,
        },
        {
          onError: (error: unknown) => {
            let errorMessage = t('workspace.cannotCreateFolder')
            if (error instanceof Error) {
              const isPermissionError =
                error.message.includes('403') ||
                error.message.includes('permission') ||
                error.message.includes('Forbidden') ||
                error.message.includes('insufficient') ||
                error.message.includes('Insufficient')

              if (isPermissionError) {
                errorMessage = t('workspace.cannotCreateFolder')
              } else {
                errorMessage = error.message || errorMessage
              }
            }
            toast({
              title: t('workspace.noPermission'),
              description: errorMessage,
              variant: 'destructive',
            })
          },
        },
      )
    },
    [
      workspaceId,
      duplicateFolderMutation,
      folderStoreData,
      foldersData,
      userPermissions.canEdit,
      toast,
      t,
    ],
  )

  /**
   * Handle move agent to folder
   */
  const handleMoveAgentToFolder = useCallback(
    async (agentId: string, folderId: string | null) => {
      try {
        await agentService.moveToFolder(agentId, folderId)
        queryClient.invalidateQueries({ queryKey: graphKeys.list(workspaceId) })
      } catch (error) {
        logger.error('Failed to move agent to folder', { error, agentId, folderId })
      }
    },
    [workspaceId, queryClient],
  )

  /**
   * Handle rename agent
   */
  const handleRenameAgent = useCallback(
    (agentId: string, newName: string) => {
      updateAgentMutation.mutate({
        id: agentId,
        name: newName,
      })
    },
    [updateAgentMutation],
  )

  /**
   * Handle delete agent - opens confirmation dialog
   */
  const handleDeleteAgent = useCallback(
    (agentId: string) => {
      if (!userPermissions.canEdit) {
        toast({
          title: t('workspace.noPermission'),
          description: t('workspace.cannotDeleteAgent'),
          variant: 'destructive',
        })
        return
      }
      const agent = agents.find((a) => a.id === agentId)
      if (!agent) {
        return
      }
      setAgentToDelete({ id: agentId, name: agent.name })
      setDeleteAgentConfirmOpen(true)
    },
    [agents, userPermissions.canEdit, toast, t],
  )

  /**
   * Handle confirm delete agent
   */
  const handleConfirmDeleteAgent = useCallback(() => {
    if (!agentToDelete) {
      return
    }
    deleteAgentMutation.mutate(agentToDelete.id)
    setDeleteAgentConfirmOpen(false)
    setAgentToDelete(null)
  }, [agentToDelete, deleteAgentMutation])

  /**
   * Handle duplicate agent
   */
  const handleDuplicateAgent = useCallback(
    (agentId: string) => {
      if (!userPermissions.canEdit) {
        toast({
          title: t('workspace.noPermission'),
          description: t('workspace.cannotCreateAgent'),
          variant: 'destructive',
        })
        return
      }
      duplicateAgentMutation.mutate(agentId)
    },
    [duplicateAgentMutation, userPermissions.canEdit, toast, t],
  )

  /**
   * Handle sidebar collapse toggle
   */
  const handleToggleCollapse = useCallback(() => {
    setIsCollapsed(!isCollapsed)
  }, [isCollapsed, setIsCollapsed])

  /**
   * Handle workspace switch
   */
  const handleWorkspaceSwitch = useCallback(
    (workspace: { id: string; name: string }) => {
      router.push(`/workspace/${workspace.id}`)
    },
    [router],
  )

  /**
   * Handle create workspace
   */
  const handleCreateWorkspace = useCallback(async () => {
    createWorkspaceMutation.mutate({ name: t('workspace.newWorkspace') })
  }, [createWorkspaceMutation, t])

  /**
   * Handle rename workspace
   */
  const handleRenameWorkspace = useCallback(
    (id: string, name: string) => {
      if (!updateWorkspaceMutation) {
        return
      }
      updateWorkspaceMutation.mutate({ id, updates: { name } })
    },
    [updateWorkspaceMutation],
  )

  /**
   * Handle delete workspace
   */
  const handleDeleteWorkspace = useCallback(
    (id: string) => {
      if (!deleteWorkspaceMutation) {
        return
      }
      deleteWorkspaceMutation.mutate(id)
    },
    [deleteWorkspaceMutation],
  )

  /**
   * Handle duplicate workspace
   */
  const handleDuplicateWorkspace = useCallback(
    (id: string) => {
      if (!duplicateWorkspaceMutation) {
        return
      }
      duplicateWorkspaceMutation.mutate({ id })
    },
    [duplicateWorkspaceMutation],
  )

  /**
   * Handle resize
   */
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()

      const startX = e.clientX
      const startWidth = sidebarWidth

      const handleMouseMove = (e: MouseEvent) => {
        const delta = e.clientX - startX
        const newWidth = Math.max(MIN_SIDEBAR_WIDTH, startWidth + delta)
        const maxWidth = window.innerWidth * 0.3
        setSidebarWidth(Math.min(newWidth, maxWidth))
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

  if (isCollapsed) {
    return (
      <div
        className="fixed top-[14px] z-10 max-w-[232px] rounded-[8px] border border-[var(--border)] bg-[var(--surface-2)] px-[12px] py-[8px] transition-all duration-300"
        style={{
          left: isAppSidebarCollapsed ? '78px' : '154px',
        }}
      >
        <WorkspaceHeader
          activeWorkspace={activeWorkspace}
          workspaceId={workspaceId}
          workspaces={workspacesData || []}
          isWorkspacesLoading={isWorkspacesLoading}
          isCreatingWorkspace={createWorkspaceMutation.isPending}
          onWorkspaceSwitch={handleWorkspaceSwitch}
          onCreateWorkspace={handleCreateWorkspace}
          onToggleCollapse={handleToggleCollapse}
          isCollapsed={isCollapsed}
          showCollapseButton={true}
          onRenameWorkspace={handleRenameWorkspace}
          onDeleteWorkspace={handleDeleteWorkspace}
          onDuplicateWorkspace={handleDuplicateWorkspace}
        />
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
          left: isCollapsed ? '-1000px' : isAppSidebarCollapsed ? '64px' : '140px',
          width: isCollapsed ? '0px' : `${sidebarWidth}px`,
          opacity: isCollapsed ? 0 : 1,
          visibility: isCollapsed ? 'hidden' : 'visible',
          transition: 'left 0.3s ease, width 0.3s ease, opacity 0.3s ease',
        }}
        aria-label="Workspace sidebar"
      >
        <div className="flex h-full flex-col border-r border-[var(--border)] pt-[14px]">
          {/* Header */}
          <div className="flex-shrink-0 px-[10px]">
            <WorkspaceHeader
              activeWorkspace={activeWorkspace}
              workspaceId={workspaceId}
              workspaces={workspacesData || []}
              isWorkspacesLoading={isWorkspacesLoading}
              isCreatingWorkspace={createWorkspaceMutation.isPending}
              onWorkspaceSwitch={handleWorkspaceSwitch}
              onCreateWorkspace={handleCreateWorkspace}
              onToggleCollapse={handleToggleCollapse}
              isCollapsed={isCollapsed}
              showCollapseButton={true}
              onRenameWorkspace={handleRenameWorkspace}
              onDeleteWorkspace={handleDeleteWorkspace}
              onDuplicateWorkspace={handleDuplicateWorkspace}
            />
          </div>

          {/* Search */}
          <div className="mx-[5px] mt-[10px]">
            <SearchInput
              value={searchQuery}
              onValueChange={setSearchQuery}
              placeholder={t('workspace.searchAgents')}
            />
          </div>

          {/* Agents Section */}
          <div className="relative mt-[14px] flex flex-1 flex-col overflow-hidden">
            {/* Header */}
            <div className="flex flex-shrink-0 items-center justify-between px-[10px]">
              <span className="text-[12px] font-medium text-[var(--text-tertiary)]">
                {t('workspace.agents')}
              </span>
              <div className="flex items-center gap-[8px]">
                <TooltipProvider delayDuration={100}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className={`rounded-[4px] p-[2px] transition-colors ${
                          createFolderMutation.isPending || !userPermissions.canEdit
                            ? 'cursor-not-allowed opacity-50'
                            : 'hover:bg-[var(--surface-5)]'
                        }`}
                        onClick={() => handleCreateFolder()}
                        disabled={createFolderMutation.isPending}
                      >
                        <FolderPlus className="h-[14px] w-[14px] text-[var(--text-secondary)]" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent
                      side="bottom"
                      sideOffset={4}
                      className="rounded-[8px] border border-[var(--border)] bg-[var(--surface-elevated)] px-[8px] py-[4px] text-[12px] font-medium text-[var(--text-primary)] shadow-lg"
                    >
                      {t('workspace.createFolder')}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
                <TooltipProvider delayDuration={100}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className={`rounded-[4px] border border-[var(--border)] p-[2px] transition-colors ${
                          createAgentMutation.isPending || !userPermissions.canEdit
                            ? 'cursor-not-allowed opacity-50'
                            : 'hover:bg-[var(--surface-5)]'
                        }`}
                        onClick={handleCreateAgent}
                        disabled={createAgentMutation.isPending}
                      >
                        <Plus className="h-[14px] w-[14px] text-[var(--text-secondary)]" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent
                      side="bottom"
                      sideOffset={4}
                      className="rounded-[8px] border border-[var(--border)] bg-[var(--surface-elevated)] px-[8px] py-[4px] text-[12px] font-medium text-[var(--text-primary)] shadow-lg"
                    >
                      {t('workspace.createAgent')}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>

            {/* Scrollable Agent List */}
            <div
              ref={scrollContainerRef}
              className="mt-[8px] flex-1 overflow-y-auto overflow-x-hidden px-[5px]"
            >
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

      {/* Resize Handle */}
      {isOnAgentPage && (
        <div
          className="fixed bottom-0 top-0 z-20 w-[8px] cursor-ew-resize"
          style={{ left: `${(isAppSidebarCollapsed ? 64 : 140) + sidebarWidth - 4}px` }}
          onMouseDown={handleMouseDown}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
        />
      )}

      {/* Delete Agent Confirmation Dialog */}
      <AlertDialog open={deleteAgentConfirmOpen} onOpenChange={setDeleteAgentConfirmOpen}>
        <AlertDialogContent variant="destructive">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.deleteAgentConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {agentToDelete ? (
                <>
                  {t('workspace.deleteAgentConfirmMessagePrefix')}{' '}
                  <span className="font-semibold text-[#ef4444]">{agentToDelete.name}</span>{' '}
                  {t('workspace.deleteAgentConfirmMessageSuffix')}
                </>
              ) : (
                t('workspace.deleteAgentConfirmMessageDefault')
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => {
                setDeleteAgentConfirmOpen(false)
                setAgentToDelete(null)
              }}
            >
              {t('workspace.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDeleteAgent}
              className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
            >
              {t('workspace.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Create Agent Dialog */}
      <AlertDialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workspace.createAgent', { defaultValue: 'Create New Agent' })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('workspace.createAgentDescription', { defaultValue: 'Choose a mode and name for your agent.' })}
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="space-y-4 py-2">
            {/* Mode Selection */}
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setCreateAgentMode('dsl')}
                className={cn(
                  'flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-all',
                  createAgentMode === 'dsl'
                    ? 'border-primary bg-primary/5 ring-1 ring-primary'
                    : 'border-[var(--border)] hover:border-primary/30'
                )}
              >
                <span className="text-sm font-medium">Code (DSL)</span>
                <span className="text-[11px] leading-tight text-[var(--text-muted)]">
                  Python code to define graph structure
                </span>
              </button>
              <button
                type="button"
                onClick={() => setCreateAgentMode('canvas')}
                className={cn(
                  'flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-all',
                  createAgentMode === 'canvas'
                    ? 'border-primary bg-primary/5 ring-1 ring-primary'
                    : 'border-[var(--border)] hover:border-primary/30'
                )}
              >
                <span className="text-sm font-medium">Canvas</span>
                <span className="text-[11px] leading-tight text-[var(--text-muted)]">
                  Drag-and-drop DeepAgents builder
                </span>
              </button>
            </div>

            {/* Name Input */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[var(--text-secondary)]">
                {t('workspace.agentName', { defaultValue: 'Agent Name' })}
              </label>
              <input
                value={newAgentName}
                onChange={(e) => setNewAgentName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleConfirmCreateAgent()}
                className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 text-sm outline-none focus:border-primary focus:ring-1 focus:ring-primary"
                autoFocus
              />
            </div>
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel>{t('workspace.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmCreateAgent}
              disabled={!newAgentName.trim()}
            >
              {t('workspace.create', { defaultValue: 'Create' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
