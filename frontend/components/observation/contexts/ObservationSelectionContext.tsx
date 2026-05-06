'use client'

import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { useSearchParams, useRouter, usePathname } from 'next/navigation'

interface ObservationSelectionValue {
  selectedNodeId: string | null
  selectNode: (id: string | null) => void
  collapsedNodes: Set<string>
  toggleCollapse: (id: string) => void
  expandAll: () => void
  collapseAll: (ids: string[]) => void
  searchInputValue: string
  searchQuery: string
  setSearchInputValue: (v: string) => void
  setSearchQueryImmediate: (v: string) => void
  viewMode: 'tree' | 'timeline'
  setViewMode: (mode: 'tree' | 'timeline') => void
  selectedTab: 'preview' | 'scores'
  setSelectedTab: (tab: 'preview' | 'scores') => void
  viewPref: 'formatted' | 'json'
  setViewPref: (pref: 'formatted' | 'json') => void
}

const ObservationSelectionCtx = createContext<ObservationSelectionValue | null>(null)

export function ObservationSelectionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const selectedNodeId = searchParams.get('observation') ?? null
  const selectNode = useCallback(
    (id: string | null) => {
      const params = new URLSearchParams(searchParams.toString())
      if (id) params.set('observation', id)
      else params.delete('observation')
      router.replace(`${pathname}?${params.toString()}`, { scroll: false })
    },
    [router, pathname, searchParams],
  )

  const viewMode = (searchParams.get('view') as 'tree' | 'timeline') ?? 'tree'
  const setViewMode = useCallback(
    (mode: 'tree' | 'timeline') => {
      const params = new URLSearchParams(searchParams.toString())
      if (mode === 'timeline') params.set('view', 'timeline')
      else params.delete('view')
      router.replace(`${pathname}?${params.toString()}`, { scroll: false })
    },
    [router, pathname, searchParams],
  )

  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set())
  const toggleCollapse = useCallback((id: string) => {
    setCollapsedNodes((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])
  const expandAll = useCallback(() => setCollapsedNodes(new Set()), [])
  const collapseAll = useCallback((ids: string[]) => setCollapsedNodes(new Set(ids)), [])

  const [searchInputValue, setSearchInputValue] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const handleSearchInput = useCallback((v: string) => {
    setSearchInputValue(v)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setSearchQuery(v), 500)
  }, [])

  const setSearchQueryImmediate = useCallback((v: string) => {
    clearTimeout(debounceRef.current)
    setSearchInputValue(v)
    setSearchQuery(v)
  }, [])

  const [selectedTab, setSelectedTab] = useState<'preview' | 'scores'>('preview')
  const [viewPref, _setViewPref] = useState<'formatted' | 'json'>(() => {
    if (typeof window === 'undefined') return 'formatted'
    return (localStorage.getItem('obs-view-pref') as 'formatted' | 'json') ?? 'formatted'
  })
  const setViewPref = useCallback((v: 'formatted' | 'json') => {
    localStorage.setItem('obs-view-pref', v)
    _setViewPref(v)
  }, [])

  const value = useMemo(
    () => ({
      selectedNodeId,
      selectNode,
      collapsedNodes,
      toggleCollapse,
      expandAll,
      collapseAll,
      searchInputValue,
      searchQuery,
      setSearchInputValue: handleSearchInput,
      setSearchQueryImmediate,
      viewMode,
      setViewMode,
      selectedTab,
      setSelectedTab,
      viewPref,
      setViewPref,
    }),
    [
      selectedNodeId,
      selectNode,
      collapsedNodes,
      toggleCollapse,
      expandAll,
      collapseAll,
      searchInputValue,
      searchQuery,
      handleSearchInput,
      setSearchQueryImmediate,
      viewMode,
      setViewMode,
      selectedTab,
      setSelectedTab,
      viewPref,
      setViewPref,
    ],
  )

  return (
    <ObservationSelectionCtx.Provider value={value}>{children}</ObservationSelectionCtx.Provider>
  )
}

export function useObservationSelection() {
  const ctx = useContext(ObservationSelectionCtx)
  if (!ctx)
    throw new Error('useObservationSelection must be used within ObservationSelectionProvider')
  return ctx
}
