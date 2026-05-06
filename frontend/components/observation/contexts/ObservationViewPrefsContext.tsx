'use client'

import React, { createContext, useCallback, useContext, useMemo, useState } from 'react'

interface ObservationViewPrefsValue {
  showDuration: boolean
  showCostTokens: boolean
  colorCodeMetrics: boolean
  setShowDuration: (v: boolean) => void
  setShowCostTokens: (v: boolean) => void
  setColorCodeMetrics: (v: boolean) => void
}

const ObservationViewPrefsCtx = createContext<ObservationViewPrefsValue | null>(null)

function readBool(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  const v = localStorage.getItem(key)
  return v === null ? fallback : v === 'true'
}

export function ObservationViewPrefsProvider({ children }: { children: React.ReactNode }) {
  const [showDuration, _setShowDuration] = useState(() => readBool('obs-show-duration', true))
  const [showCostTokens, _setShowCostTokens] = useState(() =>
    readBool('obs-show-cost-tokens', true),
  )
  const [colorCodeMetrics, _setColorCodeMetrics] = useState(() =>
    readBool('obs-color-code-metrics', true),
  )

  const setShowDuration = useCallback((v: boolean) => {
    localStorage.setItem('obs-show-duration', String(v))
    _setShowDuration(v)
  }, [])
  const setShowCostTokens = useCallback((v: boolean) => {
    localStorage.setItem('obs-show-cost-tokens', String(v))
    _setShowCostTokens(v)
  }, [])
  const setColorCodeMetrics = useCallback((v: boolean) => {
    localStorage.setItem('obs-color-code-metrics', String(v))
    _setColorCodeMetrics(v)
  }, [])

  const value = useMemo(
    () => ({
      showDuration,
      showCostTokens,
      colorCodeMetrics,
      setShowDuration,
      setShowCostTokens,
      setColorCodeMetrics,
    }),
    [
      showDuration,
      showCostTokens,
      colorCodeMetrics,
      setShowDuration,
      setShowCostTokens,
      setColorCodeMetrics,
    ],
  )

  return (
    <ObservationViewPrefsCtx.Provider value={value}>{children}</ObservationViewPrefsCtx.Provider>
  )
}

export function useObservationViewPrefs() {
  const ctx = useContext(ObservationViewPrefsCtx)
  if (!ctx)
    throw new Error('useObservationViewPrefs must be used within ObservationViewPrefsProvider')
  return ctx
}
