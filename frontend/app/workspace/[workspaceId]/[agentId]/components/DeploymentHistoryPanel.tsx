'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  History,
  RotateCcw,
  Edit2,
  Check,
  X,
  Loader2,
  Clock,
  User,
  Eye,
  ChevronLeft,
  ChevronRight,
  Rocket,
  Trash2,
  XCircle,
} from 'lucide-react'
import React, { useEffect, useState, useCallback, useRef } from 'react'

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
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useToast } from '@/components/ui/use-toast'
import { useDeploymentStatus, useDeploymentVersions, graphKeys } from '@/hooks/queries/graphs'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import { graphDeploymentService, type GraphDeploymentVersion, type GraphVersionState } from '@/services/graphDeploymentService'
import { useDeploymentStore } from '@/stores/deploymentStore'



import { agentService } from '../services/agentService'
import { useBuilderStore } from '../stores/builderStore'


import { GraphPreview } from './GraphPreview'

interface DeploymentHistoryPanelProps {
  graphId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  nodesCount?: number
}

type PreviewMode = 'current' | 'selected'

export const DeploymentHistoryPanel: React.FC<DeploymentHistoryPanelProps> = ({
  graphId,
  open,
  onOpenChange,
  nodesCount = 0,
}) => {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1)
  const pageSize = 10

  // Use React Query hooks to fetch data
  // Key optimization: Only execute queries when panel is open, avoiding unnecessary API requests
  const { data: deploymentStatus } = useDeploymentStatus(graphId, { enabled: open })
  const {
    data: versionsData,
    isLoading: isLoadingVersions,
    refetch: refetchVersions
  } = useDeploymentVersions(graphId, currentPage, pageSize, { enabled: open })

  const versions = versionsData?.versions || []
  const totalVersions = versionsData?.total || 0
  const totalPages = versionsData?.totalPages || 1

  // Get UI state and operation methods from Zustand store
  const {
    revertToVersion,
    renameVersion,
    deleteVersion,
    undeploy,
    isDeploying,
    isUndeploying,
  } = useDeploymentStore()

  const [editingVersion, setEditingVersion] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  // Version preview related state
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [previewMode, setPreviewMode] = useState<PreviewMode>('current')
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)

  // Revert confirmation dialog state
  const [revertConfirmOpen, setRevertConfirmOpen] = useState(false)
  const [versionToRevert, setVersionToRevert] = useState<number | null>(null)
  const [isReverting, setIsReverting] = useState(false)

  // Delete version confirmation dialog state
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [versionToDelete, setVersionToDelete] = useState<number | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  // Undeploy graph confirmation dialog state
  const [undeployConfirmOpen, setUndeployConfirmOpen] = useState(false)

  // Version state cache
  const versionCacheRef = useRef<Map<number, GraphVersionState>>(new Map())
  const [, forceUpdate] = useState({})

  // Get rfInstance and current nodes for preview
  const rfInstance = useBuilderStore((state) => state.rfInstance)
  const currentNodes = useBuilderStore((state) => state.nodes)
  const currentEdges = useBuilderStore((state) => state.edges)

  // Current editing state
  const currentState: GraphVersionState = {
    nodes: currentNodes.map(node => ({
      id: node.id,
      type: node.type || 'custom',
      position: node.position,
      data: node.data as Record<string, unknown>,
    })),
    edges: currentEdges.map(edge => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
    })),
  }

  // Get cached state of selected version
  const cachedSelectedState = selectedVersion !== null
    ? versionCacheRef.current.get(selectedVersion)
    : null

  // Fetch state of selected version
  const fetchVersionState = useCallback(async (version: number) => {
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
  }, [graphId])

  // Load state when selecting version
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
      // React Query will automatically fetch data, just need to reset pagination and selection state
      setCurrentPage(1)
      setSelectedVersion(null)
      setPreviewMode('current')
    } else if (!open) {
      // Clear cache when dialog closes to avoid memory leaks
      versionCacheRef.current.clear()
      setSelectedVersion(null)
      setPreviewMode('current')
    }
  }, [open, graphId])

  const handleSelectVersion = useCallback((version: number) => {
    if (selectedVersion === version) {
      // Click again to cancel selection
      setSelectedVersion(null)
    } else {
      setSelectedVersion(version)
    }
  }, [selectedVersion])

  // Pagination handling
  const handlePageChange = useCallback((page: number) => {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page)
    }
  }, [totalPages])

  // Open revert confirmation dialog
  const handleRevertClick = (version: number) => {
    setVersionToRevert(version)
    setRevertConfirmOpen(true)
  }

  // Open delete confirmation dialog
  const handleDeleteClick = (version: number) => {
    setVersionToDelete(version)
    setDeleteConfirmOpen(true)
  }

  // Confirm delete version
  const handleConfirmDelete = async () => {
    if (versionToDelete === null) return

    setIsDeleting(true)
    try {
      await deleteVersion(graphId, versionToDelete)

      // Refresh deployment versions cache after successful delete
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(graphId) })

      toast({
        title: t('workspace.deleteVersionSuccess'),
        description: t('workspace.deleteVersionSuccessDescription', { version: versionToDelete }),
        variant: 'success',
      })
      setDeleteConfirmOpen(false)
      setVersionToDelete(null)
      // If deleting the selected version, clear selection state
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

  // Confirm undeploy graph
  const handleConfirmUndeploy = async () => {
    try {
      await undeploy(graphId)

      // Refresh deployment status cache after successful undeploy
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

  // Confirm revert
  const handleConfirmRevert = async () => {
    if (versionToRevert === null) return

    setIsReverting(true)
    try {
      await revertToVersion(graphId, versionToRevert)

      // Refresh deployment status cache after successful revert
      queryClient.invalidateQueries({ queryKey: graphKeys.deployment(graphId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(graphId) })
      queryClient.invalidateQueries({ queryKey: graphKeys.deployed() })

      // Reload graph data after successful revert
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

      // Close dialog and panel
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

      // Refresh deployment versions cache after successful rename
      queryClient.invalidateQueries({ queryKey: graphKeys.versions(graphId) })
    } catch (error) {
      console.error('Failed to rename version:', error)
    } finally {
      setIsSaving(false)
      setEditingVersion(null)
      setEditName('')
    }
  }

  // Format to specific time
  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}`
  }

  // Preview state to display
  const previewState = previewMode === 'selected' && cachedSelectedState
    ? cachedSelectedState
    : currentState

  const selectedVersionInfo = versions.find(v => v.version === selectedVersion)
  const showToggle = selectedVersion !== null

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[800px] p-0 bg-white border border-gray-200 rounded-2xl shadow-2xl flex flex-col overflow-hidden max-h-[85vh]">
        <DialogHeader className="px-4 py-3.5 border-b border-gray-100 shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <History size={20} />
            {t('workspace.deploymentHistory')}
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto custom-scrollbar px-4 py-4">
          <div className="grid grid-cols-2 gap-4">
          {/* Left: Preview area */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-700">
                {previewMode === 'selected' && selectedVersionInfo
                  ? selectedVersionInfo.name || `v${selectedVersion}`
                  : t('workspace.currentDraft')
                }
              </span>
              {showToggle && (
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant={previewMode === 'current' ? 'default' : 'ghost'}
                    className="h-6 px-2 text-xs"
                    onClick={() => setPreviewMode('current')}
                  >
                    {t('workspace.current')}
                  </Button>
                  <Button
                    size="sm"
                    variant={previewMode === 'selected' ? 'default' : 'ghost'}
                    className="h-6 px-2 text-xs"
                    onClick={() => setPreviewMode('selected')}
                  >
                    v{selectedVersion}
                  </Button>
                </div>
              )}
            </div>
            
            <div className="relative">
              {isLoadingPreview && previewMode === 'selected' && (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/80 rounded-lg">
                  <Loader2 size={24} className="animate-spin text-gray-400" />
                </div>
              )}
              <GraphPreview 
                state={previewState} 
                height={300}
                className="bg-gray-50"
              />
            </div>
          </div>

          {/* Right: Version list */}
          <div className="space-y-3">
            {/* Current deployment status */}
            {deploymentStatus && (
              <div className="p-2 bg-gray-50 rounded-lg border text-sm">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Rocket size={14} className={deploymentStatus.isDeployed ? 'text-green-600' : 'text-gray-400'} />
                    <span className="font-medium">
                      {deploymentStatus.isDeployed
                        ? t('workspace.deployed')
                        : t('workspace.notDeployed')
                      }
                    </span>
                    {deploymentStatus.deployment && (
                      <span className="text-xs text-gray-500">
                        v{deploymentStatus.deployment.version}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {deploymentStatus.needsRedeployment && deploymentStatus.isDeployed && (
                      <span className="text-xs text-orange-600 bg-orange-50 px-2 py-0.5 rounded">
                        {t('workspace.needsRedeployment')}
                      </span>
                    )}
                    {deploymentStatus.isDeployed && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
                        onClick={() => setUndeployConfirmOpen(true)}
                        disabled={isUndeploying}
                      >
                        {isUndeploying ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <XCircle size={12} className="mr-1" />
                        )}
                        {t('workspace.undeploy')}
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Version list */}
            <div className="space-y-1.5 max-h-[240px] overflow-y-auto">
              {isLoadingVersions ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 size={24} className="animate-spin text-gray-400" />
                </div>
              ) : versions.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <History size={32} className="mx-auto mb-2 opacity-50" />
                  <p className="text-xs">
                    {t('workspace.noDeployments')}
                  </p>
                </div>
              ) : (
                versions.map((version) => (
                  <div
                    key={version.id}
                    className={cn(
                      "p-2 rounded-lg border-2 transition-all cursor-pointer",
                      version.isActive
                        ? 'bg-green-50 border-green-500 shadow-sm shadow-green-100'
                        : 'bg-white border-gray-200 hover:bg-gray-50 hover:border-gray-300',
                      selectedVersion === version.version && 'ring-2 ring-blue-500 ring-offset-1'
                    )}
                    onClick={() => handleSelectVersion(version.version)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      {/* Version info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <span className="text-xs font-medium">
                            v{version.version}
                          </span>
                          {version.isActive && (
                            <span className="text-[10px] text-green-700 bg-green-100 px-1.5 py-0.5 rounded-full font-medium">
                              {t('workspace.active')}
                            </span>
                          )}
                          {selectedVersion === version.version && (
                            <Eye size={12} className="text-blue-500" />
                          )}
                        </div>

                        {/* Name editing */}
                        {editingVersion === version.version ? (
                          <div className="flex items-center gap-1 mb-1" onClick={e => e.stopPropagation()}>
                            <Input
                              value={editName}
                              onChange={(e) => setEditName(e.target.value)}
                              placeholder={t('workspace.versionName')}
                              className="h-6 text-xs"
                              autoFocus
                            />
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 w-6 p-0"
                              onClick={handleSaveName}
                              disabled={isSaving}
                            >
                              {isSaving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 w-6 p-0"
                              onClick={handleCancelEdit}
                              disabled={isSaving}
                            >
                              <X size={12} />
                            </Button>
                          </div>
                        ) : (
                          version.name && (
                            <p className="text-xs text-gray-600 mb-0.5 truncate">{version.name}</p>
                          )
                        )}

                        {/* Time and username */}
                        <div className="flex items-center gap-2 text-[10px] text-gray-600">
                          <div className="flex items-center gap-0.5">
                            <Clock size={10} />
                            <span>{formatDate(version.createdAt)}</span>
                          </div>
                          {(version.createdByName || version.createdBy) && (
                            <div className="flex items-center gap-0.5">
                              <User size={10} />
                              <span className="truncate max-w-[80px]">
                                {version.createdByName || version.createdBy}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Action buttons */}
                      <div className="flex items-center gap-0.5" onClick={e => e.stopPropagation()}>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 w-6 p-0"
                          onClick={() => handleRevertClick(version.version)}
                          title={t('workspace.revertToThisVersion')}
                        >
                          <RotateCcw size={12} />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 w-6 p-0"
                          onClick={() => handleStartEdit(version)}
                          title={t('workspace.rename')}
                        >
                          <Edit2 size={12} />
                        </Button>
                        {!version.isActive && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 w-6 p-0 text-gray-400 hover:text-red-600 hover:bg-red-50"
                            onClick={() => handleDeleteClick(version.version)}
                            title={t('workspace.deleteVersion')}
                          >
                            <Trash2 size={12} />
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Pagination controls */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between pt-2 border-t border-gray-100">
                <span className="text-[10px] text-gray-400">
                  {t('workspace.totalVersions', { total: totalVersions })}
                </span>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0"
                    onClick={() => handlePageChange(currentPage - 1)}
                    disabled={currentPage <= 1 || isLoadingVersions}
                  >
                    <ChevronLeft size={14} />
                  </Button>
                  <span className="text-[10px] text-gray-500 min-w-[50px] text-center">
                    {currentPage} / {totalPages}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 w-6 p-0"
                    onClick={() => handlePageChange(currentPage + 1)}
                    disabled={currentPage >= totalPages || isLoadingVersions}
                  >
                    <ChevronRight size={14} />
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
        </div>
      </DialogContent>
    </Dialog>

    {/* Revert confirmation dialog */}
    <AlertDialog open={revertConfirmOpen} onOpenChange={setRevertConfirmOpen}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t('workspace.revertConfirmTitle')}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {versionToRevert !== null ? (
              <>
                {t('workspace.revertConfirmMessagePrefix')}{' '}
                <span className="font-semibold text-[#ef4444]">
                  {versions.find(v => v.version === versionToRevert)?.name || `v${versionToRevert}`}
                </span>{' '}
                {t('workspace.revertConfirmMessageSuffix')}
              </>
            ) : (
              t('workspace.revertConfirmMessageDefault')
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel 
            onClick={() => {
              setRevertConfirmOpen(false)
              setVersionToRevert(null)
            }}
            disabled={isReverting}
          >
            {t('workspace.cancel')}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirmRevert}
            disabled={isReverting}
            className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
          >
            {isReverting ? (
              <>
                <Loader2 size={14} className="mr-1 animate-spin" />
                {t('workspace.reverting')}
              </>
            ) : (
              t('workspace.confirmRevert')
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    {/* Delete version confirmation dialog */}
    <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
      <AlertDialogContent variant="destructive">
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t('workspace.deleteVersionConfirmTitle')}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {versionToDelete !== null ? (
              <>
                {t('workspace.deleteVersionConfirmMessagePrefix')}{' '}
                <span className="font-semibold text-[#ef4444]">
                  {versions.find(v => v.version === versionToDelete)?.name || `v${versionToDelete}`}
                </span>{' '}
                {t('workspace.deleteVersionConfirmMessageSuffix')}
              </>
            ) : (
              t('workspace.deleteVersionConfirmMessageDefault')
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel 
            onClick={() => {
              setDeleteConfirmOpen(false)
              setVersionToDelete(null)
            }}
            disabled={isDeleting}
          >
            {t('workspace.cancel')}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirmDelete}
            disabled={isDeleting}
            className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
          >
            {isDeleting ? (
              <>
                <Loader2 size={14} className="mr-1 animate-spin" />
                {t('workspace.deleting')}
              </>
            ) : (
              t('workspace.confirmDelete')
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    {/* Undeploy graph confirmation dialog */}
    <AlertDialog open={undeployConfirmOpen} onOpenChange={setUndeployConfirmOpen}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t('workspace.undeployConfirmTitle')}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t('workspace.undeployConfirmMessage')}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel 
            onClick={() => setUndeployConfirmOpen(false)}
            disabled={isUndeploying}
          >
            {t('workspace.cancel')}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirmUndeploy}
            disabled={isUndeploying}
            className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
          >
            {isUndeploying ? (
              <>
                <Loader2 size={14} className="mr-1 animate-spin" />
                {t('workspace.undeploying')}
              </>
            ) : (
              t('workspace.confirmUndeploy')
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  )
}
