import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'

import { createLogger } from '@/lib/logs/console/logger'

const logger = createLogger('FoldersStore')

/**
 * Maximum folder nesting depth (2 levels: root + 1 subfolder)
 */
export const MAX_FOLDER_DEPTH = 2

/**
 * Workflow folder interface
 */
export interface WorkflowFolder {
  id: string
  name: string
  workspaceId: string
  parentId: string | null
  color: string
  isExpanded: boolean
  sortOrder: number
  createdAt: Date
  updatedAt: Date
}

/**
 * Folder tree node with children
 */
export interface FolderTreeNode extends WorkflowFolder {
  children: FolderTreeNode[]
  level: number
}

/**
 * Folder state interface
 */
interface FolderState {
  folders: Record<string, WorkflowFolder>
  expandedFolders: Set<string>
  isLoading: boolean
  error: string | null

  // Actions
  setFolders: (folders: WorkflowFolder[]) => void
  addFolder: (folder: WorkflowFolder) => void
  updateFolder: (id: string, updates: Partial<WorkflowFolder>) => void
  removeFolder: (id: string) => void
  toggleExpanded: (folderId: string) => void
  setExpanded: (folderId: string, expanded: boolean) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  reset: () => void

  // Computed getters
  getFolderTree: (workspaceId: string) => FolderTreeNode[]
  getFolderById: (id: string) => WorkflowFolder | undefined
  getChildFolders: (parentId: string | null, workspaceId: string) => WorkflowFolder[]
  getRootFolders: (workspaceId: string) => WorkflowFolder[]
  getFolderDepth: (folderId: string) => number
  canCreateSubfolder: (parentId: string) => boolean
}

const initialState = {
  folders: {},
  expandedFolders: new Set<string>(),
  isLoading: false,
  error: null,
}

export const useFolderStore = create<FolderState>()(
  devtools(
    persist(
      (set, get) => ({
        ...initialState,

        setFolders: (folders) =>
          set(() => ({
            folders: folders.reduce(
              (acc, folder) => {
                acc[folder.id] = folder
                return acc
              },
              {} as Record<string, WorkflowFolder>
            ),
          })),

        addFolder: (folder) =>
          set((state) => ({
            folders: { ...state.folders, [folder.id]: folder },
          })),

        updateFolder: (id, updates) =>
          set((state) => {
            const existing = state.folders[id]
            if (!existing) return state
            return {
              folders: {
                ...state.folders,
                [id]: { ...existing, ...updates, updatedAt: new Date() },
              },
            }
          }),

        removeFolder: (id) =>
          set((state) => {
            const { [id]: _, ...rest } = state.folders
            return { folders: rest }
          }),

        toggleExpanded: (folderId) =>
          set((state) => {
            const newExpanded = new Set(state.expandedFolders)
            if (newExpanded.has(folderId)) {
              newExpanded.delete(folderId)
            } else {
              newExpanded.add(folderId)
            }
            return { expandedFolders: newExpanded }
          }),

        setExpanded: (folderId, expanded) =>
          set((state) => {
            const newExpanded = new Set(state.expandedFolders)
            if (expanded) {
              newExpanded.add(folderId)
            } else {
              newExpanded.delete(folderId)
            }
            return { expandedFolders: newExpanded }
          }),

        setLoading: (isLoading) => set({ isLoading }),
        setError: (error) => set({ error }),
        reset: () => set(initialState),

        getFolderTree: (workspaceId) => {
          const folders = Object.values(get().folders).filter(
            (f) => f.workspaceId === workspaceId
          )

          const buildTree = (parentId: string | null, level = 0): FolderTreeNode[] => {
            // Limit to MAX_FOLDER_DEPTH levels
            if (level >= MAX_FOLDER_DEPTH) return []

            return folders
              .filter((folder) => folder.parentId === parentId)
              .sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name))
              .map((folder) => ({
                ...folder,
                children: buildTree(folder.id, level + 1),
                level,
              }))
          }

          return buildTree(null)
        },

        getFolderById: (id) => get().folders[id],

        getChildFolders: (parentId, workspaceId) =>
          Object.values(get().folders)
            .filter((folder) => folder.parentId === parentId && folder.workspaceId === workspaceId)
            .sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name)),

        getRootFolders: (workspaceId) =>
          Object.values(get().folders)
            .filter((folder) => folder.parentId === null && folder.workspaceId === workspaceId)
            .sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name)),

        getFolderDepth: (folderId) => {
          const allFolders = get().folders
          let depth = 0
          let currentId: string | null = folderId

          while (currentId && allFolders[currentId]) {
            const currentFolder: WorkflowFolder = allFolders[currentId]
            if (currentFolder.parentId) {
              depth++
              currentId = currentFolder.parentId
            } else {
              break
            }
          }

          return depth
        },

        canCreateSubfolder: (parentId) => {
          const depth = get().getFolderDepth(parentId)
          // Can create if parent is at depth 0 (root folder)
          // Depth 0 = root folder, Depth 1 = subfolder (max allowed)
          return depth < MAX_FOLDER_DEPTH - 1
        },
      }),
      {
        name: 'folder-store',
        partialize: (state) => ({
          expandedFolders: Array.from(state.expandedFolders),
        }),
        onRehydrateStorage: () => (state) => {
          if (state && Array.isArray(state.expandedFolders)) {
            state.expandedFolders = new Set(state.expandedFolders as unknown as string[])
          }
        },
      }
    ),
    { name: 'folder-store' }
  )
)

