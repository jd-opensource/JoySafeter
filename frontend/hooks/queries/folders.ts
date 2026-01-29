/**
 * Folders Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { API_ENDPOINTS, apiDelete, apiGet, apiPost, apiPut } from '@/lib/api-client'
import i18n from '@/lib/i18n/config'
import { createLogger } from '@/lib/logs/console/logger'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { useFolderStore, type WorkflowFolder } from '@/stores/folders/store'

import { STALE_TIME } from './constants'

const logger = createLogger('FolderQueries')

export const folderKeys = {
  all: ['folders'] as const,
  lists: () => [...folderKeys.all, 'list'] as const,
  list: (workspaceId: string | undefined) => [...folderKeys.lists(), workspaceId ?? ''] as const,
}

interface WorkflowFolderDto {
  id: string
  name: string
  userId: string
  workspaceId: string
  parentId: string | null
  color: string | null
  isExpanded: boolean
  sortOrder: number
  createdAt: string
  updatedAt: string
}

interface ListFoldersResponse {
  folders: WorkflowFolderDto[]
}

const mapFolderDtoToModel = (folder: WorkflowFolderDto): WorkflowFolder => ({
  id: folder.id,
  name: folder.name,
  workspaceId: folder.workspaceId,
  parentId: folder.parentId,
  color: folder.color ?? '#6B7280',
  isExpanded: folder.isExpanded,
  sortOrder: folder.sortOrder,
  createdAt: new Date(folder.createdAt),
  updatedAt: new Date(folder.updatedAt),
})

export function useFolders(workspaceId?: string) {
  const setFolders = useFolderStore((state) => state.setFolders)

  const query = useQuery({
    queryKey: folderKeys.list(workspaceId),
    queryFn: async () => {
      if (!workspaceId) {
        return [] as WorkflowFolder[]
      }

      logger.info('Fetching folders from API', { workspaceId })
      const result = await apiGet<ListFoldersResponse>(
        `${API_ENDPOINTS.folders}?workspaceId=${encodeURIComponent(workspaceId)}`
      )
      const folders = result.folders.map(mapFolderDtoToModel)
      return folders
    },
    enabled: Boolean(workspaceId),
    placeholderData: keepPreviousData,
    staleTime: STALE_TIME.STANDARD,
  })

  useEffect(() => {
    if (query.data) {
      setFolders(query.data)
    }
  }, [query.data, setFolders])

  return query
}

interface CreateFolderVariables {
  workspaceId: string
  name: string
  parentId?: string | null
  color?: string
}

interface CreateFolderResponse {
  folder: WorkflowFolderDto
}

export function useCreateFolder() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ workspaceId, name, parentId, color }: CreateFolderVariables) => {
      logger.info('Creating folder', { workspaceId, name })
      
      const result = await apiPost<CreateFolderResponse>(API_ENDPOINTS.folders, {
        workspaceId,
        name,
        parentId: parentId ?? null,
        color,
      })

      return mapFolderDtoToModel(result.folder)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: folderKeys.list(variables.workspaceId) })
      logger.info('Folder created successfully')
      toastSuccess(i18n.t('workspace.folderCreateSuccess') || 'Folder created successfully')
    },
    onError: (error) => {
      logger.error('Failed to create folder', { error })
      let errorMessage = i18n.t('workspace.folderCreateFailed') || 'Failed to create folder'
      if (error instanceof Error) {
        errorMessage = error.message || errorMessage
      }
      toastError(errorMessage)
    },
  })
}

interface UpdateFolderVariables {
  workspaceId: string
  id: string
  updates: Partial<Pick<WorkflowFolder, 'name' | 'parentId' | 'color' | 'sortOrder' | 'isExpanded'>>
}

interface UpdateFolderResponse {
  folder: WorkflowFolderDto
}

export function useUpdateFolder() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ workspaceId, id, updates }: UpdateFolderVariables) => {
      logger.info('Updating folder', { id, workspaceId, updates })
      
      const payload: Record<string, unknown> = {
        workspaceId,
      }

      if (typeof updates.name !== 'undefined') {
        payload.name = updates.name
      }
      if (typeof updates.parentId !== 'undefined') {
        payload.parentId = updates.parentId
      }
      if (typeof updates.color !== 'undefined') {
        payload.color = updates.color
      }
      if (typeof updates.isExpanded !== 'undefined') {
        payload.isExpanded = updates.isExpanded
      }

      const result = await apiPut<UpdateFolderResponse>(
        `${API_ENDPOINTS.folders}/${encodeURIComponent(id)}`,
        payload
      )

      return mapFolderDtoToModel(result.folder)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: folderKeys.list(variables.workspaceId) })
      // Only show toast when modifying name (expand/collapse doesn't need notification)
      if (variables.updates.name) {
        toastSuccess(i18n.t('workspace.folderUpdateSuccess') || 'Folder updated successfully')
      }
    },
    onError: (error) => {
      logger.error('Failed to update folder', { error })
      let errorMessage = i18n.t('workspace.folderUpdateFailed') || 'Failed to update folder'
      if (error instanceof Error) {
        errorMessage = error.message || errorMessage
      }
      toastError(errorMessage)
    },
  })
}

interface DeleteFolderVariables {
  workspaceId: string
  id: string
}

export function useDeleteFolderMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ workspaceId, id }: DeleteFolderVariables) => {
      logger.info('Deleting folder', { id, workspaceId })
      
      await apiDelete<unknown>(`${API_ENDPOINTS.folders}/${encodeURIComponent(id)}`)
      return { success: true }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: folderKeys.list(variables.workspaceId) })
      toastSuccess(i18n.t('workspace.folderDeleteSuccess') || 'Folder deleted successfully')
    },
    onError: (error) => {
      logger.error('Failed to delete folder', { error })
      let errorMessage = i18n.t('workspace.folderDeleteFailed') || 'Failed to delete folder'
      if (error instanceof Error) {
        errorMessage = error.message || errorMessage
      }
      toastError(errorMessage)
    },
  })
}

interface DuplicateFolderVariables {
  workspaceId: string
  id: string
  name: string
  parentId?: string | null
  color?: string
}

interface DuplicateFolderResponse {
  id: string
  name: string
  color?: string | null
  workspaceId: string
  parentId: string | null
}

export function useDuplicateFolderMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ workspaceId, id, name, parentId, color }: DuplicateFolderVariables) => {
      logger.info('Duplicating folder', { id, name, workspaceId })
      
      const result = await apiPost<DuplicateFolderResponse>(
        `${API_ENDPOINTS.folders}/${encodeURIComponent(id)}/duplicate`,
        {
          workspaceId,
          name,
          parentId: parentId ?? null,
          color,
        }
      )
      
      const dto: WorkflowFolderDto = {
        id: result.id,
        name: result.name,
        userId: '', // Backend does not currently return user ID in duplicate response
        workspaceId: result.workspaceId,
        parentId: result.parentId,
        color: result.color ?? '#6B7280',
        isExpanded: false,
        sortOrder: 0,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }

      return mapFolderDtoToModel(dto)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: folderKeys.list(variables.workspaceId) })
      toastSuccess(i18n.t('workspace.folderDuplicateSuccess') || 'Folder duplicated successfully')
    },
    onError: (error) => {
      logger.error('Failed to duplicate folder', { error })
      let errorMessage = i18n.t('workspace.folderDuplicateFailed') || 'Failed to duplicate folder'
      if (error instanceof Error) {
        errorMessage = error.message || errorMessage
      }
      toastError(errorMessage)
    },
  })
}
