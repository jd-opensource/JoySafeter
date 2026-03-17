import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Sidebar state interface
 */
interface SidebarState {
  workspaceDropdownOpen: boolean
  sidebarWidth: number
  isCollapsed: boolean
  isAppSidebarCollapsed: boolean
  setWorkspaceDropdownOpen: (isOpen: boolean) => void
  setSidebarWidth: (width: number) => void
  setIsCollapsed: (isCollapsed: boolean) => void
  setIsAppSidebarCollapsed: (isCollapsed: boolean) => void
}

/**
 * Sidebar width constraints
 * Note: Maximum width is enforced dynamically at 30% of viewport width in the resize hook
 */
export const DEFAULT_SIDEBAR_WIDTH = 200
export const MIN_SIDEBAR_WIDTH = 200

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set, get) => ({
      workspaceDropdownOpen: false,
      sidebarWidth: DEFAULT_SIDEBAR_WIDTH,
      isCollapsed: false,
      isAppSidebarCollapsed: false,
      setWorkspaceDropdownOpen: (isOpen) => set({ workspaceDropdownOpen: isOpen }),
      setSidebarWidth: (width) => {
        // Only enforce minimum - maximum is enforced dynamically by the resize hook
        const clampedWidth = Math.max(MIN_SIDEBAR_WIDTH, width)
        set({ sidebarWidth: clampedWidth })
        // Update CSS variable for immediate visual feedback
        if (typeof window !== 'undefined') {
          document.documentElement.style.setProperty('--sidebar-width', `${clampedWidth}px`)
        }
      },
      setIsCollapsed: (isCollapsed) => {
        set({ isCollapsed })
        // Set width to 0 when collapsed (floating UI doesn't need sidebar space)
        if (isCollapsed && typeof window !== 'undefined') {
          document.documentElement.style.setProperty('--sidebar-width', '0px')
        } else if (!isCollapsed && typeof window !== 'undefined') {
          // Restore to stored width when expanding
          const currentWidth = get().sidebarWidth
          document.documentElement.style.setProperty('--sidebar-width', `${currentWidth}px`)
        }
      },
      setIsAppSidebarCollapsed: (isCollapsed) => set({ isAppSidebarCollapsed: isCollapsed }),
    }),
    {
      name: 'sidebar-state',
      onRehydrateStorage: () => (state) => {
        // Validate and enforce constraints after rehydration
        if (state && typeof window !== 'undefined') {
          // If stored width is larger than new default, reset to new default
          if (!state.isCollapsed && state.sidebarWidth > DEFAULT_SIDEBAR_WIDTH) {
            state.sidebarWidth = DEFAULT_SIDEBAR_WIDTH
          }
          // Ensure width meets minimum constraint
          if (!state.isCollapsed && state.sidebarWidth < MIN_SIDEBAR_WIDTH) {
            state.sidebarWidth = MIN_SIDEBAR_WIDTH
          }
          // Use 0 width if collapsed (floating UI), otherwise use stored width
          const width = state.isCollapsed ? 0 : state.sidebarWidth
          document.documentElement.style.setProperty('--sidebar-width', `${width}px`)
        }
      },
    }
  )
)
