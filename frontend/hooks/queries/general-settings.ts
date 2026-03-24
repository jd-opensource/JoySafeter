/**
 * General Settings Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { apiGet } from '@/lib/api-client'
import { syncThemeToNextThemes } from '@/lib/core/utils/theme'
import { createLogger } from '@/lib/logs/console/logger'
import { useGeneralStore } from '@/stores/settings/general/store'

import { STALE_TIME } from './constants'

const logger = createLogger('GeneralSettingsQuery')

/**
 * Query key factories for general settings
 */
export const generalSettingsKeys = {
  all: ['generalSettings'] as const,
  settings: () => [...generalSettingsKeys.all, 'settings'] as const,
}

/**
 * General settings type
 */
export interface GeneralSettings {
  autoConnect: boolean
  showTrainingControls: boolean
  superUserModeEnabled: boolean
  theme: 'light' | 'dark' | 'system'
  telemetryEnabled: boolean
  billingUsageNotificationsEnabled: boolean
  errorNotificationsEnabled: boolean
}

/**
 * Fetch general settings from API
 */
async function fetchGeneralSettings(): Promise<GeneralSettings> {
  const data = await apiGet<GeneralSettings>('users/me/settings')

  return {
    autoConnect: data.autoConnect ?? true,
    showTrainingControls: data.showTrainingControls ?? false,
    superUserModeEnabled: data.superUserModeEnabled ?? true,
    // theme: data.theme || 'system',
    // Force dark mode - light mode is temporarily disabled
    theme: 'dark' as const,
    telemetryEnabled: data.telemetryEnabled ?? true,
    billingUsageNotificationsEnabled: data.billingUsageNotificationsEnabled ?? true,
    errorNotificationsEnabled: data.errorNotificationsEnabled ?? true,
  }
}

/**
 * Sync React Query cache to Zustand store and next-themes.
 * This ensures the rest of the app (which uses Zustand) stays in sync.
 * @param settings - The general settings to sync
 */
function syncSettingsToZustand(settings: GeneralSettings) {
  const { setSettings } = useGeneralStore.getState()

  setSettings({
    isAutoConnectEnabled: settings.autoConnect,
    showTrainingControls: settings.showTrainingControls,
    superUserModeEnabled: settings.superUserModeEnabled,
    theme: settings.theme,
    telemetryEnabled: settings.telemetryEnabled,
    isBillingUsageNotificationsEnabled: settings.billingUsageNotificationsEnabled,
    isErrorNotificationsEnabled: settings.errorNotificationsEnabled,
  })

  syncThemeToNextThemes(settings.theme)
}

/**
 * Hook to fetch general settings.
 * Also syncs to Zustand store to keep the rest of the app in sync.
 */
export function useGeneralSettings() {
  const query = useQuery({
    queryKey: generalSettingsKeys.settings(),
    queryFn: fetchGeneralSettings,
    staleTime: STALE_TIME.VERY_LONG,
    placeholderData: keepPreviousData,
  })

  useEffect(() => {
    if (query.data) {
      syncSettingsToZustand(query.data)
    }
  }, [query.data])

  return query
}

