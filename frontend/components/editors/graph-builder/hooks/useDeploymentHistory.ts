'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, useCallback, useMemo } from 'react'

import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { agentVersionService } from '@/services/agentVersionService'

import { deploymentAdapter } from '../services/deploymentAdapter'
import { useBuilderStore } from '../stores/builderStore'

export interface GraphDeploymentVersion {
  id?: string
  version: number
  name?: string
  created_at: string
  createdAt?: string
  is_current?: boolean
  isActive?: boolean
  createdBy?: string
  createdByName?: string
  /** The underlying release id (used for activate/retire calls). */
  releaseId?: string
  /** The underlying agent version id (used for preview). */
  agentVersionId?: string
}

export interface GraphDeploymentStatus {
  is_deployed: boolean
  version?: number
  deployed_at?: string
}

export interface GraphVersionState {
  nodes: Array<{
    id: string
    type: string
    position: { x: number; y: number }
    data: Record<string, unknown>
  }>
  edges: Array<{ id: string; source: string; target: string }>
}

type PreviewMode = 'current' | 'selected'

export function useDeploymentHistory(
  _graphId: string,
  open: boolean,
  onOpenChange: (open: boolean) => void,
) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const agentId = useBuilderStore((state) => state.agentId)
  const workspaceId = useBuilderStore((state) => state.workspaceId)
  const rfInstance = useBuilderStore((state) => state.rfInstance)
  const currentNodes = useBuilderStore((state) => state.nodes)
  const currentEdges = useBuilderStore((state) => state.edges)

  // ── List loading ──────────────────────────────────────────────────────────

  const releasesQuery = useQuery({
    queryKey: ['releases', agentId, workspaceId],
    queryFn: () => deploymentAdapter.list(agentId!, workspaceId!),
    enabled: open && !!agentId && !!workspaceId,
  })

  // Map DeploymentVersion[] → GraphDeploymentVersion[]
  // We store the releaseId (the release's own id) in `releaseId` so mutation
  // handlers can call activate/retire without a second lookup.
  // We also propagate agent_version_id from the raw AgentRelease objects if available.
  const rawReleases = releasesQuery.data ?? []

  const versions: GraphDeploymentVersion[] = useMemo(
    () =>
      rawReleases.map((r) => ({
        id: r.id,
        releaseId: r.id,
        version: r.version,
        name: undefined,
        created_at: r.published_at ?? '',
        createdAt: r.published_at ?? '',
        isActive: r.status === 'ready',
        is_current: r.status === 'ready',
        // agent_version_id is not exposed by DeploymentVersion; keep undefined so
        // fetchVersionState can handle it gracefully.
        agentVersionId: undefined,
      })),
    [rawReleases],
  )

  const isLoadingVersions = releasesQuery.isLoading

  // Pagination: frontend pagination over the full list
  const [currentPage, setCurrentPage] = useState(1)
  const pageSize = 10
  const totalVersions = versions.length
  const totalPages = Math.max(1, Math.ceil(totalVersions / pageSize))
  const pagedVersions = versions.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  // Deployment status derived from releases (any release in 'ready' state = deployed)
  const deploymentStatus: GraphDeploymentStatus | undefined = useMemo(() => {
    if (!releasesQuery.isFetched) return undefined
    const activeRelease = versions.find((v) => v.isActive)
    return {
      is_deployed: !!activeRelease,
      version: activeRelease?.version,
      deployed_at: activeRelease?.createdAt ?? activeRelease?.created_at,
    }
  }, [releasesQuery.isFetched, versions])

  // ── Preview state ─────────────────────────────────────────────────────────

  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [previewMode, setPreviewMode] = useState<PreviewMode>('current')
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)
  const [versionCache, setVersionCache] = useState<Record<number, GraphVersionState>>({})

  const currentState: GraphVersionState = useMemo(
    () => ({
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
    }),
    [currentNodes, currentEdges],
  )

  const cachedSelectedState =
    selectedVersion !== null ? (versionCache[selectedVersion] ?? null) : null

  const fetchVersionState = useCallback(
    async (version: number) => {
      if (!agentId || !workspaceId) return
      if (versionCache[version]) return

      // Find the corresponding release to get its agent_version_id
      const release = rawReleases.find((r) => r.version === version)
      if (!release) return

      // DeploymentVersion doesn't expose agent_version_id — we need to look it
      // up from the full AgentRelease which agentReleaseService.get() would give us.
      // For now derive it from the agentVersionService list as a fallback.
      setIsLoadingPreview(true)
      try {
        const agentVersions = await agentVersionService.list(agentId, workspaceId)
        // Each release maps to a version by release_number → version_number ordering;
        // we match by release.version (release_number). The simplest heuristic is
        // version_number === release_number (they tend to align), but we use the
        // version list sorted to find the one at position `version`.
        const sorted = [...agentVersions].sort((a, b) => a.version_number - b.version_number)
        const agentVersion = sorted[version - 1] ?? sorted[sorted.length - 1]
        if (!agentVersion) return

        const fullVersion = await agentVersionService.get(agentId, agentVersion.id, workspaceId)
        const payload = fullVersion.definition_payload as {
          nodes?: GraphVersionState['nodes']
          edges?: GraphVersionState['edges']
        }
        const state: GraphVersionState = {
          nodes: payload.nodes ?? [],
          edges: payload.edges ?? [],
        }
        setVersionCache((prev) => ({ ...prev, [version]: state }))
      } catch (error) {
        console.error('Failed to fetch version state:', error)
      } finally {
        setIsLoadingPreview(false)
      }
    },
    [agentId, workspaceId, versionCache, rawReleases],
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
    if (open) {
      setCurrentPage(1)
      setSelectedVersion(null)
      setPreviewMode('current')
    } else {
      setVersionCache({})
      setSelectedVersion(null)
      setPreviewMode('current')
    }
  }, [open])

  const previewState =
    previewMode === 'selected' && cachedSelectedState ? cachedSelectedState : currentState

  const selectedVersionInfo = pagedVersions.find((v) => v.version === selectedVersion)
  const showToggle = selectedVersion !== null

  // ── UI state ──────────────────────────────────────────────────────────────

  const [editingVersion, setEditingVersion] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  const [revertConfirmOpen, setRevertConfirmOpen] = useState(false)
  const [versionToRevert, setVersionToRevert] = useState<number | null>(null)

  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [versionToDelete, setVersionToDelete] = useState<number | null>(null)

  const [undeployConfirmOpen, setUndeployConfirmOpen] = useState(false)

  // ── Mutations ─────────────────────────────────────────────────────────────

  const activateMutation = useMutation({
    mutationFn: ({ releaseId }: { releaseId: string }) =>
      deploymentAdapter.activate(agentId!, releaseId, workspaceId!),
    onSuccess: (_data, { releaseId: _releaseId }) => {
      queryClient.invalidateQueries({ queryKey: ['releases', agentId, workspaceId] })
    },
  })

  const retireMutation = useMutation({
    mutationFn: ({ releaseId }: { releaseId: string }) =>
      deploymentAdapter.retire(agentId!, releaseId, workspaceId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['releases', agentId, workspaceId] })
    },
  })

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleSelectVersion = useCallback(
    (version: number) => {
      setSelectedVersion((prev) => (prev === version ? null : version))
    },
    [],
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

  const handleConfirmRevert = async () => {
    if (versionToRevert === null || !agentId || !workspaceId) return

    const release = versions.find((v) => v.version === versionToRevert)
    const releaseId = release?.releaseId
    if (!releaseId) return

    try {
      await activateMutation.mutateAsync({ releaseId })

      // Reload canvas state from the activated version's definition_payload
      try {
        const agentVersions = await agentVersionService.list(agentId, workspaceId)
        const sorted = [...agentVersions].sort((a, b) => a.version_number - b.version_number)
        const agentVersion = sorted[versionToRevert - 1] ?? sorted[sorted.length - 1]
        if (agentVersion) {
          const fullVersion = await agentVersionService.get(agentId, agentVersion.id, workspaceId)
          const payload = fullVersion.definition_payload as {
            nodes?: unknown[]
            edges?: unknown[]
            viewport?: { x: number; y: number; zoom: number }
          }
          useBuilderStore.setState({
            nodes: (payload.nodes as import('reactflow').Node[]) ?? [],
            edges: (payload.edges as import('reactflow').Edge[]) ?? [],
            past: [],
            future: [],
            selectedNodeId: null,
          })
          if (payload.viewport && rfInstance) {
            rfInstance.setViewport(payload.viewport)
          } else if (rfInstance) {
            setTimeout(() => rfInstance.fitView({ padding: 0.2 }), 100)
          }
        }
      } catch (loadError) {
        console.error('Failed to reload canvas after revert:', loadError)
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
      console.error('Failed to activate version:', error)
      toast({
        title: t('workspace.revertFailed'),
        description: t('workspace.revertFailedDescription'),
        variant: 'destructive',
      })
    }
  }

  const handleConfirmDelete = async () => {
    if (versionToDelete === null || !agentId || !workspaceId) return

    const release = versions.find((v) => v.version === versionToDelete)
    const releaseId = release?.releaseId
    if (!releaseId) return

    try {
      await retireMutation.mutateAsync({ releaseId })

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
      console.error('Failed to retire version:', error)
      toast({
        title: t('workspace.deleteVersionFailed'),
        description: t('workspace.deleteVersionFailedDescription'),
        variant: 'destructive',
      })
    }
  }

  const handleConfirmUndeploy = async () => {
    if (!agentId || !workspaceId) return

    // Find the currently active release and retire it
    const activeRelease = versions.find((v) => v.isActive)
    const releaseId = activeRelease?.releaseId
    if (!releaseId) {
      setUndeployConfirmOpen(false)
      return
    }

    try {
      await retireMutation.mutateAsync({ releaseId })

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

  // Rename is not supported in the new API — show an informational toast instead.
  const handleStartEdit = (_version: GraphDeploymentVersion) => {
    toast({
      title: t('workspace.renameNotSupported', { defaultValue: 'Rename not supported' }),
      description: t('workspace.renameNotSupportedDescription', {
        defaultValue: 'Version renaming is not available in this release.',
      }),
    })
  }

  const handleCancelEdit = () => {
    setEditingVersion(null)
    setEditName('')
  }

  const handleSaveName = async () => {
    // No-op: rename is not supported; handleStartEdit already shows a toast.
    setIsSaving(false)
    setEditingVersion(null)
    setEditName('')
  }

  const formatDate = (dateString: string) => {
    if (!dateString) return ''
    const date = new Date(dateString)
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hours = String(date.getHours()).padStart(2, '0')
    const minutes = String(date.getMinutes()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}`
  }

  const isReverting = activateMutation.isPending
  const isDeleting = retireMutation.isPending
  const isUndeploying = retireMutation.isPending

  return {
    t,
    // Data
    deploymentStatus,
    versions: pagedVersions,
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
