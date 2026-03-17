'use client'

/**
 * ExecutionViewPreferencesContext - Manages view preferences for the execution panel.
 *
 * Responsibilities:
 * - JSON view mode (formatted vs raw)
 * - Show/hide duration
 * - Active detail tab
 */

import React, { createContext, useContext, useState, useCallback, useMemo } from 'react'

export type JsonViewMode = 'formatted' | 'json'
export type DetailTab = 'preview' | 'output' | 'metadata'

interface ExecutionViewPreferencesContextValue {
  jsonViewMode: JsonViewMode
  setJsonViewMode: (mode: JsonViewMode) => void
  showDuration: boolean
  toggleShowDuration: () => void
  activeDetailTab: DetailTab
  setActiveDetailTab: (tab: DetailTab) => void
}

const ExecutionViewPreferencesCtx = createContext<ExecutionViewPreferencesContextValue | null>(null)

export function useExecutionViewPreferences() {
  const ctx = useContext(ExecutionViewPreferencesCtx)
  if (!ctx) {
    throw new Error('useExecutionViewPreferences must be used within ExecutionViewPreferencesProvider')
  }
  return ctx
}

interface ExecutionViewPreferencesProviderProps {
  children: React.ReactNode
}

export function ExecutionViewPreferencesProvider({ children }: ExecutionViewPreferencesProviderProps) {
  const [jsonViewMode, setJsonViewMode] = useState<JsonViewMode>('formatted')
  const [showDuration, setShowDuration] = useState(true)
  const [activeDetailTab, setActiveDetailTab] = useState<DetailTab>('preview')

  const toggleShowDuration = useCallback(() => {
    setShowDuration(prev => !prev)
  }, [])

  const value = useMemo(
    () => ({
      jsonViewMode,
      setJsonViewMode,
      showDuration,
      toggleShowDuration,
      activeDetailTab,
      setActiveDetailTab,
    }),
    [jsonViewMode, showDuration, activeDetailTab, toggleShowDuration]
  )

  return (
    <ExecutionViewPreferencesCtx.Provider value={value}>
      {children}
    </ExecutionViewPreferencesCtx.Provider>
  )
}
