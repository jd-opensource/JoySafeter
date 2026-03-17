'use client'

import { type ReactNode, useEffect } from 'react'

import i18n from '@/lib/i18n/config'

/**
 * I18n Provider
 * Ensure i18n is properly initialized on the client side
 */
export function I18nProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    // Ensure i18n is initialized
    if (!i18n.isInitialized) {
      i18n.init()
    }
  }, [])

  return <>{children}</>
}
