'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, useCallback, useRef } from 'react'

import { useToast } from '@/hooks/use-toast'
import { useDeploymentStatus, useDeploymentVersions, graphKeys } from '@/hooks/queries/graphs'
import { useTranslation } from '@/lib/i18n'
import {
  graphDeploymentService,
  type GraphDeploymentVersion,
  type GraphVersionState,
} from '@/services/graphDeploymentService'
import { useDeploymentStore } from '@/stores/deploymentStore'

import { agentService } from '../services/agentService'
import { useBuilderStore } from '../stores/builderStore'

type PreviewMode = 'current' | 'selected'

export function useDeploymentHistory(
  graphId: string,
  open: boolean,
  onOpenChange: (open: boolean) => void,
) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1)
  const pageSize = 10

  const { data: deploymentStatus } = useDeploymentStatus(graphId, { enabled: open })
  const {
    data: versionsData,
    isLoading: isLoadingVersions,
  } = useDeploymentVersions(graphId, currentPage, pageSize, { enabled: open })

  const versions = versionsData?.versions || []
  const totalVersions = versionsData?.total || 0
  const totalPages = versionsData?.totalPages || 1

  const { revertToVersion, renameVersion, deleteVersion, undeploy, isUndeploying } =
    useDeploymentStore()

  const [editingVersion, setEditingVersion] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [previewMode, setPreviewMode] = useState<PreviewMode>('current')
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)

  const [revertConfirmOpen, setRevertConfirmOpen] = useState(false)
  const [versionToRevert, setVersionToRevert] = useState<number | null>(null)
  const [isReverting, setIsReverting] = useState(false)

  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [versionToDelete, setVersionToDelete] = useState<number | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const [undeployConfirmOpen, setUndeployConfirmOpen] = useState(false)

  const versionCacheRef = useRef<Map<number, GraphVersionState>>(new Map())
  const [, forceUpdate] = useState({})

  const rfInstance = useBuilderStore((state) => state.rfInstance)
  const currentNodes = useBuilderStore((state) => state.nodes)
  const currentEdges = useBuilderStore((state) => state.edges)

  const currentState: GraphVersionState = {
    nodes: currentNodes.map((node) => ({
      id: node.id,
      type: node.type || 'custom',
      position: node.position,
      data: node.data as Record<string, unknown>,
    })),
    edges: currentEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
    })),
  }

  const cachedSelectedState =
    selectedVersion !== null ? versionCacheRef.current.get(selectedVersion) : null

  const fetchVersionState = useCallback(
    async (version: number) => {
      if (!graphId) return
      if (versionCacheRef.current.has(version)) return

      setIsLoadingPreview(true)
      try {
        const response = await graphDeploymentService.getVersionState(graphId, version)
        if (response.state) {
          versionCacheRef.current.set(version, response.state)
          forceUpdate({})
        }
      } catch (error) {
        console.error('Failed to fetch version state:', error)
      } finally {
        setIsLoadingPreview(false)
      }
    },
    [graphId],
  )

  useEffect(() => {
    if (selectedVersion !== null) {
      fetchVersionState(selectedVersion)
      setPreviewMode('selected')
    } else {
      setPreviewMode('current')
    }
  }, [selectedVersion, fetchVersionState])

  useEffect(() => {
    if (open && graphId) {
      setCurrentPage(1)
      setSelectedVersion(null)
      setPreviewMode('current')
    } else if (!open) {
      versionCacheRef.current.clear()
      setSelectedVersion(null)
      setPreviewMode('current')
    }
  }, [open, graphId])

  const handleSelectVersion = useCallback(
    (version: number) => {
      if (selectedVersion === version) {
        setSelectedVersion(null)
      } else {
        setSelectedVersion(version)
      }
    },
    [selectedVersion],
  )

  const handlePageChange = useCallback(
    (page: number) => {
      if (page >= 1 && page <= totalPages) {
        setCurrentPage(page)
      }
    },
    [totalPages],
  )

  const handleRevertClick = (version: number) => {
    setVersionToRevert(version)
    setRevertConfirmOpen(true)
  }

  const handleDeleteClick = (version: number) => {
    setVersionToDelete(version)
    setDeleteConfirmOpen(true)
  }

  const handleConfirmDelete = async () => {
    if (versionToDelete === null) return

    setIsDeleting(true)
    try {
      await deleteVersion(graphId, versionToDelete)
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(graphId) })

      toast({
        title: t('workspace.deleteVersionSuccess'),
        description: t('workspace.deleteVersionSuccessDescription', { version: versionToDelete }),
        variant: 'success',
      })
      setDeleteConfirmOpen(false)
      setVersionToDelete(null)
      if (selectedVersion === versionToDelete) {
        setSelectedVersion(null)
        setPreviewMode('current')
      }
    } catch (error) {
      console.error('Failed to delete version:', error)
      toast({
        title: t('workspace.deleteVersionFailed'),
        description: t('workspace.deleteVersionFailedDescription'),
        variant: 'destructive',
      })
    } finally {
      setIsDeleting(false)
    }
  }

  const handleConfirmUndeploy = async () => {
    try {
      await undeploy(graphId)
      queryClient.invalidateQueries({ queryKey: graphKeys.deployment(graphId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(graphId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.deployed() })

      toast({
        title: t('workspace.undeploySuccess'),
        description: t('workspace.undeploySuccessDescription'),
        variant: 'success',
      })
      setUndeployConfirmOpen(false)
    } catch (error) {
      console.error('Failed to undeploy:', error)
      toast({
        title: t('workspace.undeployFailed'),
        description: t('workspace.undeployFailedDescription'),
        variant: 'destructive',
      })
    }
  }

  const handleConfirmRevert = async () => {
    if (versionToRevert === null) return

    setIsReverting(true)
    try {
      await revertToVersion(graphId, versionToRevert)
      queryClient.invalidateQueries({ queryKey: graphKeys.deployment(graphId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(graphId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.deployed() })

      const state = await agentService.loadGraphState(graphId)

      useBuilderStore.setState({
        nodes: state.nodes || [],
        edges: state.edges || [],
        past: [],
        future: [],
        selectedNodeId: null,
      })

      if (state.viewport && rfInstance) {
        rfInstance.setViewport(state.viewport)
      } else if (rfInstance) {
        setTimeout(() => {
          rfInstance?.fitView({ padding: 0.2 })
        }, 100)
      }

      toast({
        title: t('workspace.revertSuccess'),
        description: t('workspace.revertSuccessDescription', { version: versionToRevert }),
        variant: 'success',
      })

      setRevertConfirmOpen(false)
      setVersionToRevert(null)
      onOpenChange(false)
    } catch (error) {
      console.error('Failed to revert version:', error)
      toast({
        title: t('workspace.revertFailed'),
        description: t('workspace.revertFailedDescription'),
        variant: 'destructive',
      })
    } finally {
      setIsReverting(false)
    }
  }

  const handleStartEdit = (version: GraphDeploymentVersion) => {
    setEditingVersion(version.version)
    setEditName(version.name || '')
  }

  const handleCancelEdit = () => {
    setEditingVersion(null)
    setEditName('')
  }

  const handleSaveName = async () => {
    if (!editingVersion) return
    setIsSaving(true)
    try {
      await renameVersion(graphId, editingVersion, editName)
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(graphId) })
    } catch (error) {
      console.error('Failed to rename version:', error)
    } finally {
      setIsSaving(false)
      setEditingVersion(null)
      setEditName('')
    }
  }

  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}`
  }

  const previewState =
    previewMode === 'selected' && cachedSelectedState ? cachedSelectedState : currentState

  const selectedVersionInfo = versions.find((v) => v.version === selectedVersion)
  const showToggle = selectedVersion !== null

  return {
    t,
    // Data
    deploymentStatus,
    versions,
    totalVersions,
    totalPages,
    isLoadingVersions,
    // Preview
    previewMode,
    setPreviewMode,
    selectedVersion,
    selectedVersionInfo,
    showToggle,
    isLoadingPreview,
    previewState,
    // Version list
    editingVersion,
    editName,
    setEditName,
    isSaving,
    isUndeploying,
    currentPage,
    // Handlers
    handleSelectVersion,
    handlePageChange,
    handleRevertClick,
    handleDeleteClick,
    handleStartEdit,
    handleCancelEdit,
    handleSaveName,
    formatDate,
    // Confirmation dialogs
    revertConfirmOpen,
    setRevertConfirmOpen,
    versionToRevert,
    setVersionToRevert,
    isReverting,
    handleConfirmRevert,
    deleteConfirmOpen,
    setDeleteConfirmOpen,
    versionToDelete,
    setVersionToDelete,
    isDeleting,
    handleConfirmDelete,
    undeployConfirmOpen,
    setUndeployConfirmOpen,
    handleConfirmUndeploy,
  }
}
