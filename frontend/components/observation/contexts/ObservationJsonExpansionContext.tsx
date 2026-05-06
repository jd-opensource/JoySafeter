'use client'

import React, { createContext, useCallback, useContext, useMemo, useState } from 'react'

type Field = 'input' | 'output' | 'metadata'

interface ObservationJsonExpansionValue {
  formattedExpansion: Record<Field, Record<string, boolean>>
  setFormattedFieldExpansion: (field: Field, expansion: Record<string, boolean>) => void
  jsonExpansion: Record<Field, boolean>
  setJsonFieldExpansion: (field: Field, expanded: boolean) => void
}

const STORAGE_KEY = 'obs-json-expansion'

function readSession(): {
  formatted: Record<Field, Record<string, boolean>>
  json: Record<Field, boolean>
} {
  if (typeof window === 'undefined')
    return {
      formatted: { input: {}, output: {}, metadata: {} },
      json: { input: true, output: true, metadata: true },
    }
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return {
    formatted: { input: {}, output: {}, metadata: {} },
    json: { input: true, output: true, metadata: true },
  }
}

const ObservationJsonExpansionCtx = createContext<ObservationJsonExpansionValue | null>(null)

export function ObservationJsonExpansionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState(readSession)

  const setFormattedFieldExpansion = useCallback(
    (field: Field, expansion: Record<string, boolean>) => {
      setState((prev) => {
        const next = {
          ...prev,
          formatted: { ...prev.formatted, [field]: expansion },
        }
        try {
          sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
        } catch {}
        return next
      })
    },
    [],
  )

  const setJsonFieldExpansion = useCallback((field: Field, expanded: boolean) => {
    setState((prev) => {
      const next = {
        ...prev,
        json: { ...prev.json, [field]: expanded },
      }
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {}
      return next
    })
  }, [])

  const value = useMemo(
    () => ({
      formattedExpansion: state.formatted,
      setFormattedFieldExpansion,
      jsonExpansion: state.json,
      setJsonFieldExpansion,
    }),
    [state, setFormattedFieldExpansion, setJsonFieldExpansion],
  )

  return (
    <ObservationJsonExpansionCtx.Provider value={value}>
      {children}
    </ObservationJsonExpansionCtx.Provider>
  )
}

export function useObservationJsonExpansion() {
  const ctx = useContext(ObservationJsonExpansionCtx)
  if (!ctx)
    throw new Error(
      'useObservationJsonExpansion must be used within ObservationJsonExpansionProvider',
    )
  return ctx
}
