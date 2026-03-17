'use client'

/**
 * ExecutionSelectionContext - Manages selection and collapse state for the execution tree.
 *
 * Responsibilities:
 * - Track selected node ID
 * - Track collapsed/expanded node IDs
 * - Provide toggle and selection methods
 */

import React, { createContext, useContext, useCallback, useState, useMemo } from 'react'

interface ExecutionSelectionContextValue {
  selectedNodeId: string | null
  collapsedIds: Set<string>
  selectNode: (nodeId: string | null) => void
  toggleCollapse: (nodeId: string) => void
  expandAll: () => void
  collapseAll: (allNodeIds: string[]) => void
}

const ExecutionSelectionCtx = createContext<ExecutionSelectionContextValue | null>(null)

export function useExecutionSelection() {
  const ctx = useContext(ExecutionSelectionCtx)
  if (!ctx) {
    throw new Error('useExecutionSelection must be used within ExecutionSelectionProvider')
  }
  return ctx
}

interface ExecutionSelectionProviderProps {
  children: React.ReactNode
}

export function ExecutionSelectionProvider({ children }: ExecutionSelectionProviderProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set())

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId)
  }, [])

  const toggleCollapse = useCallback((nodeId: string) => {
    setCollapsedIds(prev => {
      const next = new Set(prev)
      if (next.has(nodeId)) {
        next.delete(nodeId)
      } else {
        next.add(nodeId)
      }
      return next
    })
  }, [])

  const expandAll = useCallback(() => {
    setCollapsedIds(new Set())
  }, [])

  const collapseAll = useCallback((allNodeIds: string[]) => {
    setCollapsedIds(new Set(allNodeIds))
  }, [])

  const value = useMemo(
    () => ({
      selectedNodeId,
      collapsedIds,
      selectNode,
      toggleCollapse,
      expandAll,
      collapseAll,
    }),
    [selectedNodeId, collapsedIds, selectNode, toggleCollapse, expandAll, collapseAll]
  )

  return (
    <ExecutionSelectionCtx.Provider value={value}>
      {children}
    </ExecutionSelectionCtx.Provider>
  )
}
