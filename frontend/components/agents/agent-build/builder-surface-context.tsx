'use client'

import { createContext, useContext } from 'react'
import type { BuilderSurface } from './agent-build-types'

export const BuilderSurfaceContext = createContext<BuilderSurface | null>(null)

export function useBuilderSurface(): BuilderSurface {
  const ctx = useContext(BuilderSurfaceContext)
  if (!ctx) {
    throw new Error('useBuilderSurface must be used within a BuilderSurfaceContext.Provider')
  }
  return ctx
}
