'use client'

import { useParams, usePathname } from 'next/navigation'
import { useCallback, useState, useMemo } from 'react'

import type {
  Folder as FolderType,
  AgentMetadata,
} from '@/app/workspace/[workspaceId]/components/sidebar/sidebar'
import { Skeleton } from '@/components/ui/skeleton'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useDropZone } from '../../hooks/use-drop-zone'
import { AgentItem } from './agent-item'
import { AgentListProvider } from './agent-list-context'
import { FolderItem } from './folder-item'

/**
 * Root drop zone for removing from folders
 */
interface RootDropZoneProps {
  children: React.ReactNode
  isDragActive: boolean
  onDropAgent?: (agentId: string) => void
}

function RootDropZone({ children, isDragActive, onDropAgent }: RootDropZoneProps) {
  const { t } = useTranslation()
  const { isDragOver, handleDragOver, handleDragLeave, handleDrop } = useDropZone(onDropAgent)

  if (!isDragActive) {
    return <>{children}</>
  }

  return (
    <div
      className={cn('rounded-md p-[4px] transition-all', isDragOver && 'bg-[var(--surface-5)]')}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {children}
      {isDragOver && (
        <div className="rounded-md border border-dashed border-[var(--border)] py-2 text-center text-app-xs font-medium text-[var(--text-tertiary)]">
          {t('workspace.dropHereToRemoveFromFolder')}
        </div>
      )}
    </div>
  )
}

const DEFAULT_MAX_FOLDER_DEPTH = 2

interface AgentListProps {
  regularAgents: AgentMetadata[]
  folders?: FolderType[]
  isLoading?: boolean
  searchQuery?: string
  onToggleFolder?: (folderId: string) => void
  onRenameFolder?: (folderId: string, newName: string) => void
  onDeleteFolder?: (folderId: string) => void
  onMoveAgentToFolder?: (agentId: string, folderId: string | null) => void
  onCreateSubfolder?: (parentId: string) => void
  onDuplicateFolder?: (folderId: string) => void
  maxFolderDepth?: number
  onRenameAgent?: (id: string, newName: string) => void
  onDeleteAgent?: (id: string) => void
  onDuplicateAgent?: (id: string) => void
  canEdit?: boolean
}

/**
 * AgentList component with folders and drag-drop support
 */
export function AgentList({
  regularAgents,
  folders = [],
  isLoading = false,
  searchQuery = '',
  onToggleFolder,
  onRenameFolder,
  onDeleteFolder,
  onMoveAgentToFolder,
  onCreateSubfolder,
  onDuplicateFolder,
  maxFolderDepth = DEFAULT_MAX_FOLDER_DEPTH,
  onRenameAgent,
  onDeleteAgent,
  onDuplicateAgent,
  canEdit = true,
}: AgentListProps) {
  const { t } = useTranslation()
  const pathname = usePathname()
  const params = useParams()
  const agentId = params.agentId as string | undefined
  const [isDragActive, setIsDragActive] = useState(false)

  const isAgentActive = useCallback((id: string) => pathname?.includes(`/${id}`), [pathname])

  const filteredAgents = useMemo(() => {
    if (!searchQuery.trim()) return regularAgents
    const query = searchQuery.toLowerCase().trim()
    return regularAgents.filter((agent) => agent.name.toLowerCase().includes(query))
  }, [regularAgents, searchQuery])

  const filteredFolders = useMemo(() => {
    if (!searchQuery.trim()) return folders
    const query = searchQuery.toLowerCase().trim()
    return folders.filter((folder) => {
      if (folder.name.toLowerCase().includes(query)) return true
      const agentsInFolder = filteredAgents.filter((a) => a.folderId === folder.id)
      return agentsInFolder.length > 0
    })
  }, [folders, searchQuery, filteredAgents])

  const getAgentsInFolder = useCallback(
    (folderId: string) => filteredAgents.filter((a) => a.folderId === folderId),
    [filteredAgents],
  )

  const getSubfolders = useCallback(
    (parentId: string) => filteredFolders.filter((f) => f.parentId === parentId),
    [filteredFolders],
  )

  const rootFolders = filteredFolders.filter((f) => !f.parentId)
  const rootAgents = filteredAgents.filter((a) => !a.folderId)

  const handleDragStart = useCallback(() => setIsDragActive(true), [])
  const handleDragEnd = useCallback(() => setIsDragActive(false), [])

  const agentListContextValue = useMemo(
    () => ({
      getAgentsInFolder,
      getSubfolders,
      allFolders: folders,
      activeAgentId: agentId,
      maxDepth: maxFolderDepth,
      onToggleFolder: (id: string) => onToggleFolder?.(id),
      onRenameFolder: (id: string, name: string) => onRenameFolder?.(id, name),
      onDeleteFolder: (id: string) => onDeleteFolder?.(id),
      onCreateSubfolderFor: (id: string) => onCreateSubfolder?.(id),
      onDuplicateFolder: (id: string) => onDuplicateFolder?.(id),
      onMoveAgentToFolder: (aId: string, fId: string) => onMoveAgentToFolder?.(aId, fId),
      onRenameAgent,
      onDeleteAgent,
      onDuplicateAgent,
      onDragAgentStart: handleDragStart,
      onDragAgentEnd: handleDragEnd,
      isDragActive,
      canEdit,
    }),
    [
      getAgentsInFolder,
      getSubfolders,
      folders,
      agentId,
      maxFolderDepth,
      onToggleFolder,
      onRenameFolder,
      onDeleteFolder,
      onCreateSubfolder,
      onDuplicateFolder,
      onMoveAgentToFolder,
      onRenameAgent,
      onDeleteAgent,
      onDuplicateAgent,
      handleDragStart,
      handleDragEnd,
      isDragActive,
      canEdit,
    ],
  )

  if (isLoading) {
    return (
      <div className="space-y-[4px]">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={`skeleton-${i}`} className="flex items-center gap-1.5 rounded-md px-1.5 py-[5px]">
            <Skeleton className="h-3 w-3 rounded-xs" />
            <Skeleton className="h-3.5 w-[80px]" />
          </div>
        ))}
      </div>
    )
  }

  const hasNoContent = rootFolders.length === 0 && regularAgents.length === 0

  if (hasNoContent) {
    return (
      <div className="px-2 py-3 text-center text-small font-medium text-[var(--text-tertiary)]">
        {t('workspace.noAgentsYet')}
      </div>
    )
  }

  return (
    <div className="space-y-[4px]">
      <AgentListProvider value={agentListContextValue}>
        {rootFolders.map((folder) => (
          <FolderItem
            key={folder.id}
            folder={folder}
            agents={getAgentsInFolder(folder.id)}
            subfolders={getSubfolders(folder.id)}
            depth={0}
            onToggle={() => onToggleFolder?.(folder.id)}
            onRename={(newName) => onRenameFolder?.(folder.id, newName)}
            onDelete={() => onDeleteFolder?.(folder.id)}
            onCreateSubfolder={() => onCreateSubfolder?.(folder.id)}
            onDuplicate={() => onDuplicateFolder?.(folder.id)}
            onDropAgent={(aId) => onMoveAgentToFolder?.(aId, folder.id)}
          />
        ))}
      </AgentListProvider>

      {rootAgents.length > 0 && (
        <RootDropZone
          isDragActive={isDragActive && rootFolders.length > 0}
          onDropAgent={(aId) => onMoveAgentToFolder?.(aId, null)}
        >
          <div className="space-y-[2px]">
            {rootFolders.length > 0 && (
              <div className="px-2 py-1 text-app-xs font-medium text-[var(--text-tertiary)]">
                {t('workspace.ungrouped')}
              </div>
            )}
            {rootAgents.map((agent) => (
              <AgentItem
                key={agent.id}
                agent={agent}
                active={isAgentActive(agent.id)}
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
                onRename={onRenameAgent}
                onDelete={onDeleteAgent}
                onDuplicate={onDuplicateAgent}
                canEdit={canEdit}
              />
            ))}
          </div>
        </RootDropZone>
      )}

      {rootAgents.length === 0 && rootFolders.length > 0 && isDragActive && (
        <RootDropZone isDragActive={true} onDropAgent={(aId) => onMoveAgentToFolder?.(aId, null)}>
          <div className="rounded-md border border-dashed border-[var(--border)] py-3 text-center text-app-xs font-medium text-[var(--text-tertiary)]">
            {t('workspace.dropHereToRemoveFromFolder')}
          </div>
        </RootDropZone>
      )}
    </div>
  )
}
