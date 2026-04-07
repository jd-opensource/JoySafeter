import { useState, useCallback } from 'react'

interface Workspace {
  id: string
  name: string
  ownerId?: string
  role?: string
  type?: string
}

export function useWorkspaceRename(
  activeWorkspace: { id?: string; name: string; type?: string } | null | undefined,
  workspaceId: string,
  workspaces: Workspace[],
  onRenameWorkspace?: (workspaceId: string, newName: string) => void,
  onDeleteWorkspace?: (workspaceId: string) => void,
  onDuplicateWorkspace?: (workspaceId: string) => void,
) {
  const [isRenaming, setIsRenaming] = useState(false)
  const [editingWorkspaceId, setEditingWorkspaceId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [workspaceToDelete, setWorkspaceToDelete] = useState<{ id: string; name: string } | null>(null)

  const handleStartHeaderRename = useCallback(() => {
    if (activeWorkspace?.type === 'personal') return
    setIsRenaming(true)
    setEditName(activeWorkspace?.name || '')
  }, [activeWorkspace?.name, activeWorkspace?.type])

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
    if (!trimmedName || !isDifferent || !onRenameWorkspace) return
    onRenameWorkspace(workspaceId, trimmedName)
  }, [editName, activeWorkspace?.name, activeWorkspace?.type, workspaceId, onRenameWorkspace])

  const handleCancelHeaderRename = useCallback(() => {
    setIsRenaming(false)
    setEditName('')
  }, [])

  const handleStartWorkspaceRename = useCallback((workspace: Workspace) => {
    if (workspace.type === 'personal') return
    setEditingWorkspaceId(workspace.id)
    setEditName(workspace.name)
  }, [])

  const handleSaveWorkspaceRename = useCallback(
    (wsId: string) => {
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
      if (!trimmedName || !isDifferent || !onRenameWorkspace) return
      onRenameWorkspace(wsId, trimmedName)
    },
    [editName, onRenameWorkspace, workspaces],
  )

  const handleCancelWorkspaceRename = useCallback(() => {
    setEditingWorkspaceId(null)
    setEditName('')
  }, [])

  const handleDeleteWorkspace = useCallback(
    (wsId: string) => {
      const workspace = workspaces.find((w) => w.id === wsId)
      if (workspace?.type === 'personal') return
      if (workspace) {
        setWorkspaceToDelete({ id: wsId, name: workspace.name })
        setDeleteConfirmOpen(true)
      }
    },
    [workspaces],
  )

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
    } catch {
      setDeleteConfirmOpen(false)
      setWorkspaceToDelete(null)
    }
  }, [workspaceToDelete, onDeleteWorkspace])

  const handleDuplicateWorkspace = useCallback(
    (wsId: string) => {
      const workspace = workspaces.find((w) => w.id === wsId)
      if (workspace?.type === 'personal') return
      if (!onDuplicateWorkspace) return
      onDuplicateWorkspace(wsId)
    },
    [onDuplicateWorkspace, workspaces],
  )

  const handleStartWorkspaceRenameWithClose = useCallback(
    (workspace: Workspace) => handleStartWorkspaceRename(workspace),
    [handleStartWorkspaceRename],
  )

  const handleRenameKeyDown = useCallback(
    (e: React.KeyboardEvent, wsId: string, isHeader = false) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        e.stopPropagation()
        if (isHeader) handleSaveHeaderRename()
        else handleSaveWorkspaceRename(wsId)
      } else if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        if (isHeader) handleCancelHeaderRename()
        else handleCancelWorkspaceRename()
      }
    },
    [handleSaveHeaderRename, handleCancelHeaderRename, handleSaveWorkspaceRename, handleCancelWorkspaceRename],
  )

  return {
    isRenaming,
    editingWorkspaceId,
    setEditingWorkspaceId,
    editName,
    setEditName,
    deleteConfirmOpen,
    setDeleteConfirmOpen,
    workspaceToDelete,
    setWorkspaceToDelete,
    handleStartHeaderRename,
    handleSaveHeaderRename,
    handleCancelHeaderRename,
    handleSaveWorkspaceRename,
    handleCancelWorkspaceRename,
    handleDeleteWorkspace,
    handleConfirmDelete,
    handleDuplicateWorkspace,
    handleStartWorkspaceRenameWithClose,
    handleRenameKeyDown,
  }
}
