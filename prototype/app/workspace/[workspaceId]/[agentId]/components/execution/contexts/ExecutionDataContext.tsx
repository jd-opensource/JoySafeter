'use client'

/**
 * ExecutionDataContext - Provides execution tree data to child components.
 *
 * Responsibilities:
 * - Provide treeRoots, nodeMap, flat steps
 * - Compute flattened items for virtualized rendering
 * - Memoize computations for performance
 */

import React, { createContext, useContext, useMemo } from 'react'

import type { ExecutionStep, ExecutionTreeNode, ExecutionTreeFlatItem } from '@/types'

import { flattenTree } from '../../../lib/tree-building'

interface ExecutionDataContextValue {
  steps: ExecutionStep[]
  treeRoots: ExecutionTreeNode[]
  nodeMap: Map<string, ExecutionTreeNode>
  flatItems: ExecutionTreeFlatItem[]
  isExecuting: boolean
  collapsedIds: Set<string>
}

const ExecutionDataCtx = createContext<ExecutionDataContextValue | null>(null)

export function useExecutionData() {
  const ctx = useContext(ExecutionDataCtx)
  if (!ctx) {
    throw new Error('useExecutionData must be used within ExecutionDataProvider')
  }
  return ctx
}

interface ExecutionDataProviderProps {
  steps: ExecutionStep[]
  treeRoots: ExecutionTreeNode[]
  nodeMap: Map<string, ExecutionTreeNode>
  isExecuting: boolean
  collapsedIds: Set<string>
  children: React.ReactNode
}

export function ExecutionDataProvider({
  steps,
  treeRoots,
  nodeMap,
  isExecuting,
  collapsedIds,
  children,
}: ExecutionDataProviderProps) {
  const flatItems = useMemo(
    () => flattenTree(treeRoots, collapsedIds),
    [treeRoots, collapsedIds]
  )

  const value = useMemo(
    () => ({
      steps,
      treeRoots,
      nodeMap,
      flatItems,
      isExecuting,
      collapsedIds,
    }),
    [steps, treeRoots, nodeMap, flatItems, isExecuting, collapsedIds]
  )

  return (
    <ExecutionDataCtx.Provider value={value}>
      {children}
    </ExecutionDataCtx.Provider>
  )
}
