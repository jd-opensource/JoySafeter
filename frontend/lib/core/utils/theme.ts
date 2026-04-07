/**
 * Theme utility functions for syncing with next-themes
 */

/**
 * Sync theme to next-themes by updating localStorage.
 * next-themes listens for storage events and applies the class automatically.
 *
 * @param theme - The theme to set ('light' | 'dark' | 'system')
 */
export function syncThemeToNextThemes(theme: 'light' | 'dark' | 'system'): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    const storageKey = 'joysafeter-theme'

    if (localStorage.getItem(storageKey) === theme) return

    localStorage.setItem(storageKey, theme)

    window.dispatchEvent(
      new StorageEvent('storage', {
        key: storageKey,
        newValue: theme,
        storageArea: localStorage,
      }),
    )
  } catch (error) {
    console.error('Failed to sync theme to next-themes:', error)
  }
}
