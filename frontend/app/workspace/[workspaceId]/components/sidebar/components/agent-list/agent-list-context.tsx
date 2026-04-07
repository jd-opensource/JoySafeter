'use client'

import { createContext, useContext } from 'react'

import type { Folder as FolderType, AgentMetadata } from '../../sidebar'

export interface AgentListActions {
  // Folder actions
  onToggleFolder: (folderId: string) => void
  onRenameFolder: (folderId: string, newName: string) => void
  onDeleteFolder: (folderId: string) => void
  onCreateSubfolder: (parentId: string) => void
  onDuplicateFolder: (folderId: string) => void
  onMoveAgentToFolder: (agentId: string, folderId: string | null) => void

  // Agent actions
  onRenameAgent?: (id: string, newName: string) => void
  onDeleteAgent?: (id: string) => void
  onDuplicateAgent?: (id: string) => void

  // Drag
  onDragAgentStart: () => void
  onDragAgentEnd: () => void

  // Data helpers
  getAgentsInFolder: (folderId: string) => AgentMetadata[]
  getSubfolders: (parentId: string) => FolderType[]

  // Permissions
  canEdit: boolean
}

const AgentListContext = createContext<AgentListActions | null>(null)

export const AgentListProvider = AgentListContext.Provider

export function useAgentListActions(): AgentListActions {
  const ctx = useContext(AgentListContext)
  if (!ctx) throw new Error('useAgentListActions must be used within AgentListProvider')
  return ctx
}
