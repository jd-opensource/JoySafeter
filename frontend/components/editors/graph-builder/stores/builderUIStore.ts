import { create } from 'zustand'

interface BuilderUIState {
  copilotExpanded: boolean
  toggleCopilot: () => void
  setCopilotExpanded: (expanded: boolean) => void
}

export const useBuilderUIStore = create<BuilderUIState>((set) => ({
  copilotExpanded: false,
  toggleCopilot: () => set((s) => ({ copilotExpanded: !s.copilotExpanded })),
  setCopilotExpanded: (expanded) => set({ copilotExpanded: expanded }),
}))
