'use client'

import { createContext, useContext } from 'react'

import type {
  Folder as FolderType,
  AgentMetadata,
} from '@/app/workspace/[workspaceId]/components/sidebar/sidebar'

interface AgentListContextValue {
  // Data accessors
  getAgentsInFolder: (folderId: string) => AgentMetadata[]
  getSubfolders: (parentId: string) => FolderType[]
  allFolders: FolderType[]
  activeAgentId?: string
  maxDepth: number

  // Folder actions
  onToggleFolder: (folderId: string) => void
  onRenameFolder: (folderId: string, newName: string) => void
  onDeleteFolder: (folderId: string) => void
  onCreateSubfolderFor: (parentId: string) => void
  onDuplicateFolder: (folderId: string) => void
  onMoveAgentToFolder: (agentId: string, folderId: string) => void

  // Agent actions
  onRenameAgent?: (id: string, newName: string) => void
  onDeleteAgent?: (id: string) => void
  onDuplicateAgent?: (id: string) => void

  // Drag
  onDragAgentStart?: (agentId: string) => void
  onDragAgentEnd?: () => void
  isDragActive: boolean

  // Permissions
  canEdit: boolean
}

const AgentListContext = createContext<AgentListContextValue | null>(null)

export function AgentListProvider({
  children,
  value,
}: {
  children: React.ReactNode
  value: AgentListContextValue
}) {
  return <AgentListContext.Provider value={value}>{children}</AgentListContext.Provider>
}

export function useAgentListContext() {
  const ctx = useContext(AgentListContext)
  if (!ctx) throw new Error('useAgentListContext must be used within AgentListProvider')
  return ctx
}
