import { create } from 'zustand'

type ToolView = 'tools' | 'files' | 'terminal' | 'browser'

interface ToolPanelState {
  isOpen: boolean
  activeView: ToolView
  selectedToolIndex: number
  selectedFilePath: string | null
  suiteMode: boolean
  setIsOpen: (value: boolean) => void
  setActiveView: (view: ToolView) => void
  setSelectedToolIndex: (index: number) => void
  setSelectedFilePath: (path: string | null) => void
  setSuiteMode: (value: boolean) => void
  toggle: () => void
  nextTool: (totalTools: number) => void
  prevTool: (totalTools: number) => void
}

export const useToolPanelStore = create<ToolPanelState>()((set) => ({
  isOpen: false,
  activeView: 'tools',
  selectedToolIndex: 0,
  selectedFilePath: null,
  suiteMode: false,
  setIsOpen: (value) => set({ isOpen: value }),
  setActiveView: (view) => set({ activeView: view }),
  setSelectedToolIndex: (index) => set({ selectedToolIndex: index }),
  setSelectedFilePath: (path) => set({ selectedFilePath: path }),
  setSuiteMode: (value) => set({ suiteMode: value }),
  toggle: () => set((state) => ({ isOpen: !state.isOpen })),
  nextTool: (totalTools) =>
    set((state) => ({
      selectedToolIndex: (state.selectedToolIndex + 1) % totalTools,
    })),
  prevTool: (totalTools) =>
    set((state) => ({
      selectedToolIndex: state.selectedToolIndex === 0 ? totalTools - 1 : state.selectedToolIndex - 1,
    })),
}))
