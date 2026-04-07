import { useCallback } from 'react'

import { useToast } from '@/hooks/use-toast'
import {
  useCreateFolder,
  useUpdateFolder,
  useDeleteFolderMutation as useDeleteFolder,
  useDuplicateFolderMutation as useDuplicateFolder,
} from '@/hooks/queries/folders'
import { useTranslation } from '@/lib/i18n'
import { isPermissionError } from '@/lib/utils/is-permission-error'
import { useFolderStore, type WorkflowFolder } from '@/stores/folders/store'

export function useFolderHandlers(
  workspaceId: string,
  canEdit: boolean,
) {
  const { t } = useTranslation()
  const { toast } = useToast()

  const folderStoreData = useFolderStore((state) => state.folders)
  const canCreateSubfolderCheck = useFolderStore((state) => state.canCreateSubfolder)

  const createFolderMutation = useCreateFolder()
  const updateFolderMutation = useUpdateFolder()
  const deleteFolderMutation = useDeleteFolder()
  const duplicateFolderMutation = useDuplicateFolder()

  const handleCreateFolder = useCallback(
    async (parentId?: string | null) => {
      if (!canEdit) {
        toast({
          title: t('workspace.noPermission'),
          description: t('workspace.cannotCreateFolder'),
          variant: 'destructive',
        })
        return
      }
      if (parentId && !canCreateSubfolderCheck(parentId)) {
        return
      }

      const defaultFolderName = t('workspace.defaultFolderName')
      createFolderMutation.mutate({
        workspaceId,
        name: defaultFolderName,
        parentId: parentId || undefined,
      })
    },
    [workspaceId, createFolderMutation, canCreateSubfolderCheck, t, canEdit, toast],
  )

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

  const handleDeleteFolder = useCallback(
    (folderId: string) => {
      if (!canEdit) {
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
            let errorMessage = t('workspace.cannotDeleteFolder')
            if (error instanceof Error) {
              if (isPermissionError(error)) {
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
    [workspaceId, deleteFolderMutation, canEdit, toast, t],
  )

  const handleDuplicateFolder = useCallback(
    (folderId: string, foldersData?: WorkflowFolder[]) => {
      if (!canEdit) {
        toast({
          title: t('workspace.noPermission'),
          description: t('workspace.cannotCreateFolder'),
          variant: 'destructive',
        })
        return
      }
      const folder = folderStoreData[folderId] || foldersData?.find((f: WorkflowFolder) => f.id === folderId)
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
              if (isPermissionError(error)) {
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
    [workspaceId, duplicateFolderMutation, folderStoreData, canEdit, toast, t],
  )

  return {
    createFolderMutation,
    handleCreateFolder,
    handleRenameFolder,
    handleDeleteFolder,
    handleDuplicateFolder,
  }
}
