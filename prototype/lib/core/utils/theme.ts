/**
 * Theme utility functions for syncing with next-themes
 */

/**
 * Sync theme to next-themes
 * This function sets the theme in next-themes based on the provided theme value
 *
 * @param theme - The theme to set ('light' | 'dark' | 'system')
 */
export function syncThemeToNextThemes(theme: 'light' | 'dark' | 'system'): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    const storageKey = 'joysafeter-theme'

    if (theme === 'system') {
      localStorage.removeItem(storageKey)
    } else {
      localStorage.setItem(storageKey, theme)
    }

    window.dispatchEvent(new StorageEvent('storage', {
      key: storageKey,
      newValue: theme === 'system' ? null : theme,
      storageArea: localStorage,
    }))

    const htmlElement = document.documentElement
    if (theme === 'dark') {
      htmlElement.classList.add('dark')
      htmlElement.classList.remove('light')
    } else if (theme === 'light') {
      htmlElement.classList.add('light')
      htmlElement.classList.remove('dark')
    }
  } catch (error) {
    console.error('Failed to sync theme to next-themes:', error)
  }
}
