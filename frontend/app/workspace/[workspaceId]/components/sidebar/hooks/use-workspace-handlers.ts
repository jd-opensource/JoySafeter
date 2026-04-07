import { useCallback } from 'react'

import {
  useCreateWorkspace,
  useUpdateWorkspace,
  useDeleteWorkspace,
  useDuplicateWorkspace,
} from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'

export function useWorkspaceHandlers(router: { push: (url: string) => void }) {
  const { t } = useTranslation()

  const createWorkspaceMutation = useCreateWorkspace()
  const updateWorkspaceMutation = useUpdateWorkspace()
  const deleteWorkspaceMutation = useDeleteWorkspace()
  const duplicateWorkspaceMutation = useDuplicateWorkspace()

  const handleWorkspaceSwitch = useCallback(
    (workspace: { id: string; name: string }) => {
      router.push(`/workspace/${workspace.id}`)
    },
    [router],
  )

  const handleCreateWorkspace = useCallback(async () => {
    createWorkspaceMutation.mutate({ name: t('workspace.newWorkspace') })
  }, [createWorkspaceMutation, t])

  const handleRenameWorkspace = useCallback(
    (id: string, name: string) => {
      if (!updateWorkspaceMutation) {
        return
      }
      updateWorkspaceMutation.mutate({ id, updates: { name } })
    },
    [updateWorkspaceMutation],
  )

  const handleDeleteWorkspace = useCallback(
    (id: string) => {
      if (!deleteWorkspaceMutation) {
        return
      }
      deleteWorkspaceMutation.mutate(id)
    },
    [deleteWorkspaceMutation],
  )

  const handleDuplicateWorkspace = useCallback(
    (id: string) => {
      if (!duplicateWorkspaceMutation) {
        return
      }
      duplicateWorkspaceMutation.mutate({ id })
    },
    [duplicateWorkspaceMutation],
  )

  return {
    createWorkspaceMutation,
    handleWorkspaceSwitch,
    handleCreateWorkspace,
    handleRenameWorkspace,
    handleDeleteWorkspace,
    handleDuplicateWorkspace,
  }
}
