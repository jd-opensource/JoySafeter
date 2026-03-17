import { create } from 'zustand'

interface GeneralSettingsState {
  isAutoConnectEnabled: boolean
  showTrainingControls: boolean
  superUserModeEnabled: boolean
  theme: 'light' | 'dark' | 'system'
  telemetryEnabled: boolean
  isBillingUsageNotificationsEnabled: boolean
  isErrorNotificationsEnabled: boolean
}

interface GeneralSettingsActions {
  setSettings: (settings: Partial<GeneralSettingsState>) => void
}

type GeneralSettingsStore = GeneralSettingsState & GeneralSettingsActions

const defaultState: GeneralSettingsState = {
  isAutoConnectEnabled: true,
  showTrainingControls: false,
  superUserModeEnabled: true,
  theme: 'dark',
  telemetryEnabled: true,
  isBillingUsageNotificationsEnabled: true,
  isErrorNotificationsEnabled: true,
}

export const useGeneralStore = create<GeneralSettingsStore>((set) => ({
  ...defaultState,

  setSettings: (settings) => {
    set((state) => ({
      ...state,
      ...settings,
    }))
  },
}))
