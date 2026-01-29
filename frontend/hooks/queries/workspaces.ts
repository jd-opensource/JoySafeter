/**
 * Workspaces Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPost, apiPut, apiDelete, API_ENDPOINTS } from '@/lib/api-client'
import i18n from '@/lib/i18n/config'
import { createLogger } from '@/lib/logs/console/logger'
import { toastError, toastSuccess } from '@/lib/utils/toast'

import { STALE_TIME } from './constants'

const logger = createLogger('WorkspaceQueries')

/**
 * Workspace interface
 */
export interface Workspace {
  id: string
  name: string
  ownerId: string
  description?: string
  type?: string  // 'personal' | 'team'
  createdAt: Date
  updatedAt: Date
}

/**
 * Query key factories for workspace-related queries
 */
export const workspaceKeys = {
  all: ['workspaces'] as const,
  lists: () => [...workspaceKeys.all, 'list'] as const,
  list: () => [...workspaceKeys.lists()] as const,
  detail: (id: string) => [...workspaceKeys.all, 'detail', id] as const,
}

/**
 * Map API workspace response to Workspace
 */
function mapWorkspace(workspace: any): Workspace {
  return {
    id: workspace.id,
    name: workspace.name,
    ownerId: workspace.ownerId || workspace.owner_id,
    description: workspace.description,
    type: workspace.type,  // 'personal' | 'team'
    createdAt: new Date(workspace.createdAt || workspace.created_at),
    updatedAt: new Date(workspace.updatedAt || workspace.updated_at),
  }
}

/**
 * Fetch workspaces from API
 */
async function fetchWorkspaces(): Promise<Workspace[]> {
  const response = await apiGet<{ workspaces: any[] }>(API_ENDPOINTS.workspaces)
  const workspaces = (response.workspaces || []).map(mapWorkspace)
  return workspaces
}

/**
 * Hook to fetch all workspaces
 */
export function useWorkspaces() {
  return useQuery({
    queryKey: workspaceKeys.list(),
    queryFn: fetchWorkspaces,
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME.SHORT,
    refetchOnWindowFocus: true,
  })
}

/**
 * Fetch single workspace
 */
async function fetchWorkspace(id: string): Promise<Workspace> {
  const response = await apiGet<{ workspace: any }>(`${API_ENDPOINTS.workspaces}/${id}`)
  return mapWorkspace(response.workspace)
}

/**
 * Hook to fetch a single workspace
 */
export function useWorkspace(id?: string) {
  return useQuery({
    queryKey: workspaceKeys.detail(id || ''),
    queryFn: () => fetchWorkspace(id as string),
    enabled: Boolean(id),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME.SHORT,
  })
}

/**
 * Create workspace variables
 */
interface CreateWorkspaceVariables {
  name: string
  description?: string
}

/**
 * Hook to create a workspace
 */
export function useCreateWorkspace() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (variables: CreateWorkspaceVariables): Promise<Workspace> => {
      const response = await apiPost<{ workspace: any }>(API_ENDPOINTS.workspaces, variables)
      return mapWorkspace(response.workspace)
    },
    onSuccess: (newWorkspace) => {
      queryClient.setQueryData<Workspace[]>(workspaceKeys.list(), (old) => {
        if (!old) return [newWorkspace]
        return [...old, newWorkspace]
      })
      toastSuccess(i18n.t('workspace.createSuccess') || 'Workspace created successfully')
    },
    onError: (error) => {
      logger.error('Failed to create workspace', { error })
      
      // Show error message to user
      let errorMessage = 'Failed to create workspace'
      if (error instanceof Error) {
        errorMessage = error.message
      }
      toastError(errorMessage)
    },
  })
}

/**
 * Update workspace variables
 */
interface UpdateWorkspaceVariables {
  id: string
  updates: Partial<Pick<Workspace, 'name' | 'description'>>
}

/**
 * Hook to update a workspace
 */
export function useUpdateWorkspace() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (variables: UpdateWorkspaceVariables): Promise<Workspace> => {
      try {
        const response = await apiPut<{ workspace: any }>(
          `${API_ENDPOINTS.workspaces}/${variables.id}`, 
          variables.updates
        )
        const workspaceData = response.workspace || response
        if (!workspaceData) {
          throw new Error('Invalid response format: workspace data not found')
        }
        return mapWorkspace(workspaceData)
      } catch (error) {
        throw error
      }
    },
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: workspaceKeys.list() })
      const previousWorkspaces = queryClient.getQueryData<Workspace[]>(workspaceKeys.list())

      queryClient.setQueryData<Workspace[]>(workspaceKeys.list(), (old) => {
        if (!old) return old
        return old.map((ws) =>
          ws.id === variables.id
            ? { ...ws, ...variables.updates, updatedAt: new Date() }
            : ws
        )
      })

      return { previousWorkspaces }
    },
    onError: (error, _variables, context) => {
      if (context?.previousWorkspaces) {
        queryClient.setQueryData(workspaceKeys.list(), context.previousWorkspaces)
      }
      logger.error('Failed to update workspace', { error })
      
      // Show error message to user
      let errorMessage = 'Failed to update workspace'
      if (error instanceof Error) {
        errorMessage = error.message
      }
      toastError(errorMessage)
    },
    onSuccess: (updatedWorkspace, variables) => {
      queryClient.setQueryData(workspaceKeys.detail(variables.id), updatedWorkspace)
      
      queryClient.setQueryData<Workspace[]>(workspaceKeys.list(), (old) => {
        if (!old) return old
        return old.map((ws) =>
          ws.id === variables.id ? updatedWorkspace : ws
        )
      })
      
      toastSuccess(i18n.t('workspace.renameSuccess') || 'Workspace renamed successfully')
    },
  })
}

/**
 * Hook to delete a workspace
 */
export function useDeleteWorkspace() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id: string): Promise<string> => {
      await apiDelete(`${API_ENDPOINTS.workspaces}/${id}`)
      return id
    },
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: workspaceKeys.list() })
      const previousWorkspaces = queryClient.getQueryData<Workspace[]>(workspaceKeys.list())

      queryClient.setQueryData<Workspace[]>(workspaceKeys.list(), (old) => {
        if (!old) return old
        return old.filter((ws) => ws.id !== id)
      })

      return { previousWorkspaces }
    },
    onError: (error, id, context) => {
      if (context?.previousWorkspaces) {
        queryClient.setQueryData(workspaceKeys.list(), context.previousWorkspaces)
      }
      logger.error('Failed to delete workspace', { error, id })
      
      // Show error message to user
      let errorMessage = 'Failed to delete workspace'
      if (error instanceof Error) {
        errorMessage = error.message
        // Check if it's a personal space deletion error (backend returns Chinese message)
        if (errorMessage.includes('个人空间不允许删除')) {
          // Use i18n to get translated message
          errorMessage = i18n.t('workspace.personalSpaceCannotBeDeleted')
        }
      }
      
      toastError(errorMessage)
    },
    onSuccess: (deletedId) => {
      queryClient.removeQueries({ queryKey: workspaceKeys.detail(deletedId) })
      toastSuccess(i18n.t('workspace.deleteSuccess') || 'Workspace deleted successfully')
    },
  })
}

/**
 * Hook to duplicate a workspace
 */
export function useDuplicateWorkspace() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (variables: { id: string; name?: string }): Promise<Workspace> => {
      const response = await apiPost<{ workspace: any }>(
        `${API_ENDPOINTS.workspaces}/${variables.id}/duplicate`, 
        { name: variables.name }
      )
      return mapWorkspace(response.workspace)
    },
    onSuccess: (newWorkspace) => {
      queryClient.setQueryData<Workspace[]>(workspaceKeys.list(), (old) => {
        if (!old) return [newWorkspace]
        return [...old, newWorkspace]
      })
      toastSuccess(i18n.t('workspace.duplicateSuccess') || 'Workspace duplicated successfully')
    },
    onError: (error) => {
      logger.error('Failed to duplicate workspace', { error })
      
      // Show error message to user
      let errorMessage = 'Failed to duplicate workspace'
      if (error instanceof Error) {
        errorMessage = error.message
        // Check if it's a personal space duplication error
        if (errorMessage.includes('个人空间不允许复制')) {
          errorMessage = i18n.t('workspace.personalSpaceCannotBeDuplicated') || 'Personal space cannot be duplicated'
        }
      }
      toastError(errorMessage)
    },
  })
}
