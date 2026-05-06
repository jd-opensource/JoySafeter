'use client'

import React, { createContext, useCallback, useContext, useMemo, useReducer, useState } from 'react'
import { buildTraceTree } from '../lib/tree-building'
import type { ObservationNode, RawObservation, SearchItem, TraceTreeResult } from '../lib/types'

interface ObservationDataState {
  nodeMap: Map<string, ObservationNode>
  roots: ObservationNode[]
  searchItems: SearchItem[]
  traceStartTime: Date | null
}

const initialState: ObservationDataState = {
  nodeMap: new Map(),
  roots: [],
  searchItems: [],
  traceStartTime: null,
}

type ObservationAction =
  | { type: 'SET_TREE'; result: TraceTreeResult; traceStartTime: Date }
  | { type: 'INSERT_NODE'; observation: RawObservation }
  | { type: 'UPDATE_NODE'; observation: RawObservation; data?: Record<string, unknown> }
  | { type: 'CLOSE_NODE'; observation: RawObservation }
  | { type: 'RESET' }

function parseRawToNode(
  raw: RawObservation,
  traceStartTime: Date,
  parentNode?: ObservationNode,
): ObservationNode {
  const startTime = new Date(raw.startTime)
  const endTime = raw.endTime ? new Date(raw.endTime) : null
  return {
    id: raw.id,
    parentObservationId: raw.parentObservationId,
    traceId: raw.traceId,
    type: raw.type ?? 'SPAN',
    name: raw.name ?? '',
    level: raw.level ?? 'DEFAULT',
    statusMessage: raw.statusMessage,
    startTime,
    endTime,
    completionStartTime: raw.completionStartTime ? new Date(raw.completionStartTime) : null,
    input: raw.input ?? null,
    output: raw.output ?? null,
    metadata: raw.metadata ?? null,
    model: raw.model,
    modelParameters: raw.modelParameters ?? null,
    usageDetails: raw.usageDetails,
    calculatedInputCost: raw.calculatedInputCost ?? null,
    calculatedOutputCost: raw.calculatedOutputCost ?? null,
    calculatedTotalCost: raw.calculatedTotalCost ?? null,
    environment: raw.environment ?? null,
    promptName: raw.promptName ?? null,
    promptVersion: raw.promptVersion ?? null,
    children: [],
    depth: parentNode ? parentNode.depth + 1 : 0,
    childrenDepth: 0,
    totalCost: raw.calculatedTotalCost ?? 0,
    inputUsage: raw.usageDetails?.input ?? null,
    outputUsage: raw.usageDetails?.output ?? null,
    totalUsage:
      raw.usageDetails?.total ??
      (raw.usageDetails?.input != null || raw.usageDetails?.output != null
        ? (raw.usageDetails?.input ?? 0) + (raw.usageDetails?.output ?? 0)
        : null),
    latency: endTime ? (endTime.getTime() - startTime.getTime()) / 1000 : null,
    startTimeSinceTrace: startTime.getTime() - traceStartTime.getTime(),
    startTimeSinceParentStart: parentNode
      ? startTime.getTime() - parentNode.startTime.getTime()
      : null,
  }
}

function rebuildRootsAndSearch(nodeMap: Map<string, ObservationNode>): {
  roots: ObservationNode[]
  searchItems: SearchItem[]
} {
  const roots = [...nodeMap.values()]
    .filter((n) => !n.parentObservationId)
    .sort((a, b) => a.startTime.getTime() - b.startTime.getTime())

  const searchItems: SearchItem[] = []
  const stack = [...roots].reverse()
  while (stack.length > 0) {
    const node = stack.pop()!
    searchItems.push({ node, observationId: node.id })
    for (let i = node.children.length - 1; i >= 0; i--) {
      stack.push(node.children[i])
    }
  }
  return { roots, searchItems }
}

function propagateAggregates(nodeMap: Map<string, ObservationNode>, nodeId: string): void {
  let current = nodeMap.get(nodeId)
  while (current) {
    const nodeCost =
      current.calculatedTotalCost ??
      (current.calculatedInputCost ?? 0) + (current.calculatedOutputCost ?? 0)
    current.totalCost = nodeCost + current.children.reduce((sum, c) => sum + c.totalCost, 0)
    if (!current.parentObservationId) break
    current = nodeMap.get(current.parentObservationId)
  }
}

function reducer(state: ObservationDataState, action: ObservationAction): ObservationDataState {
  switch (action.type) {
    case 'SET_TREE': {
      return {
        ...state,
        nodeMap: action.result.nodeMap,
        roots: action.result.roots,
        searchItems: action.result.searchItems,
        traceStartTime: action.traceStartTime,
      }
    }
    case 'INSERT_NODE': {
      const traceStartTime = state.traceStartTime ?? new Date()
      const parentNode = action.observation.parentObservationId
        ? state.nodeMap.get(action.observation.parentObservationId)
        : undefined
      const node = parseRawToNode(action.observation, traceStartTime, parentNode)
      const newMap = new Map(state.nodeMap)
      newMap.set(node.id, node)
      if (parentNode) {
        const newChildren = [...parentNode.children]
        const insertIdx = newChildren.findIndex(
          (c) => c.startTime.getTime() > node.startTime.getTime(),
        )
        if (insertIdx === -1) newChildren.push(node)
        else newChildren.splice(insertIdx, 0, node)
        const updatedParent = { ...parentNode, children: newChildren }
        newMap.set(updatedParent.id, updatedParent)
      }
      const { roots, searchItems } = rebuildRootsAndSearch(newMap)
      return { ...state, nodeMap: newMap, roots, searchItems, traceStartTime }
    }
    case 'UPDATE_NODE': {
      const existing = state.nodeMap.get(action.observation.id)
      if (!existing) return state
      const updated = { ...existing }
      if (action.observation.model !== undefined) updated.model = action.observation.model
      if (action.observation.metadata !== undefined) updated.metadata = action.observation.metadata
      if (action.data && Object.keys(action.data).length > 0) {
        const prev = (updated.metadata as Record<string, unknown>) ?? {}
        const prevUpdates = (prev._intermediateUpdates as unknown[]) ?? []
        updated.metadata = {
          ...prev,
          _intermediateUpdates: [...prevUpdates, action.data],
        }
      }
      const newMap = new Map(state.nodeMap)
      newMap.set(updated.id, updated)
      return { ...state, nodeMap: newMap }
    }
    case 'CLOSE_NODE': {
      const existing = state.nodeMap.get(action.observation.id)
      if (!existing) return state
      const updated = { ...existing }
      if (action.observation.endTime) updated.endTime = new Date(action.observation.endTime)
      if (action.observation.completionStartTime)
        updated.completionStartTime = new Date(action.observation.completionStartTime)
      if (action.observation.input !== undefined) updated.input = action.observation.input
      if (action.observation.output !== undefined) updated.output = action.observation.output
      if (action.observation.model !== undefined) updated.model = action.observation.model
      if (action.observation.metadata !== undefined) updated.metadata = action.observation.metadata
      if (action.observation.statusMessage !== undefined)
        updated.statusMessage = action.observation.statusMessage
      if (action.observation.modelParameters !== undefined)
        updated.modelParameters = action.observation.modelParameters
      if (action.observation.environment !== undefined)
        updated.environment = action.observation.environment
      if (action.observation.promptName !== undefined)
        updated.promptName = action.observation.promptName
      if (action.observation.promptVersion !== undefined)
        updated.promptVersion = action.observation.promptVersion
      if (action.observation.calculatedTotalCost !== undefined)
        updated.calculatedTotalCost = action.observation.calculatedTotalCost as number
      if (action.observation.calculatedInputCost !== undefined)
        updated.calculatedInputCost = action.observation.calculatedInputCost as number
      if (action.observation.calculatedOutputCost !== undefined)
        updated.calculatedOutputCost = action.observation.calculatedOutputCost as number
      if (action.observation.usageDetails !== undefined) {
        updated.usageDetails = action.observation.usageDetails
        updated.inputUsage = updated.usageDetails?.input ?? null
        updated.outputUsage = updated.usageDetails?.output ?? null
        updated.totalUsage =
          updated.usageDetails?.total ??
          (updated.inputUsage != null || updated.outputUsage != null
            ? (updated.inputUsage ?? 0) + (updated.outputUsage ?? 0)
            : null)
      }
      updated.latency = updated.endTime
        ? (updated.endTime.getTime() - updated.startTime.getTime()) / 1000
        : null
      const newMap = new Map(state.nodeMap)
      newMap.set(updated.id, updated)
      propagateAggregates(newMap, updated.id)
      return { ...state, nodeMap: newMap }
    }
    case 'RESET':
      return initialState
    default:
      return state
  }
}

interface ObservationDataContextValue {
  roots: ObservationNode[]
  nodeMap: Map<string, ObservationNode>
  searchItems: SearchItem[]
  isExecuting: boolean
  traceStartTime: Date | null
  dispatch: React.Dispatch<ObservationAction>
  loadTrace: (observations: RawObservation[], traceStartTime: Date) => void
  setIsExecuting: (v: boolean) => void
}

const ObservationDataCtx = createContext<ObservationDataContextValue | null>(null)

export function ObservationDataProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const [isExecuting, setIsExecuting] = useState(false)

  const loadTrace = useCallback((observations: RawObservation[], traceStartTime: Date) => {
    const result = buildTraceTree(observations, traceStartTime)
    dispatch({ type: 'SET_TREE', result, traceStartTime })
  }, [])

  const value = useMemo(
    () => ({ ...state, isExecuting, dispatch, loadTrace, setIsExecuting }),
    [state, isExecuting, dispatch, loadTrace],
  )

  return <ObservationDataCtx.Provider value={value}>{children}</ObservationDataCtx.Provider>
}

export function useObservationData() {
  const ctx = useContext(ObservationDataCtx)
  if (!ctx) throw new Error('useObservationData must be used within ObservationDataProvider')
  return ctx
}
