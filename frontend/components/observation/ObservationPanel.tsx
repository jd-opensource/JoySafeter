'use client'

import { Suspense } from 'react'
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels'
import { Search, TreePine, GanttChart, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ObservationViewPrefsProvider } from './contexts/ObservationViewPrefsContext'
import { ObservationDataProvider, useObservationData } from './contexts/ObservationDataContext'
import { ObservationSelectionProvider, useObservationSelection } from './contexts/ObservationSelectionContext'
import { ObservationJsonExpansionProvider } from './contexts/ObservationJsonExpansionContext'
import { ObservationNavigation } from './components/ObservationNavigation'
import { ObservationDetailPanel } from './components/ObservationDetailPanel'
import { usdFormatter, formatTokenCounts } from './lib/helpers'

export function Toolbar() {
  const { roots, isExecuting } = useObservationData()
  const {
    searchInputValue,
    setSearchInputValue,
    setSearchQueryImmediate,
    viewMode,
    setViewMode,
  } = useObservationSelection()

  const totalCost = roots.reduce((sum, r) => sum + r.totalCost, 0)
  const totalTokens = roots.reduce((sum, r) => sum + (r.totalUsage ?? 0), 0)

  return (
    <div className="flex items-center gap-2 border-b px-3 py-1.5">
      <div className="relative flex-1">
        <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          placeholder="Search observations..."
          value={searchInputValue}
          onChange={(e) => setSearchInputValue(e.target.value)}
          className="h-7 w-full rounded-sm border bg-transparent pl-7 pr-7 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary-accent"
        />
        {searchInputValue && (
          <button
            className="absolute right-2 top-1/2 -translate-y-1/2"
            onClick={() => setSearchQueryImmediate('')}
          >
            <X className="h-3 w-3 text-muted-foreground" />
          </button>
        )}
      </div>

      <div className="flex rounded-sm border">
        <button
          className={cn(
            'flex items-center gap-1 px-2 py-1 text-xs',
            viewMode === 'tree' && 'bg-muted',
          )}
          onClick={() => setViewMode('tree')}
        >
          <TreePine className="h-3 w-3" />
          Tree
        </button>
        <button
          className={cn(
            'flex items-center gap-1 px-2 py-1 text-xs',
            viewMode === 'timeline' && 'bg-muted',
          )}
          onClick={() => setViewMode('timeline')}
        >
          <GanttChart className="h-3 w-3" />
          Timeline
        </button>
      </div>

      {totalTokens > 0 && (
        <span className="text-xs text-muted-foreground">
          {formatTokenCounts(null, null, totalTokens)} tokens
        </span>
      )}
      {totalCost > 0 && (
        <span className="text-xs text-muted-foreground">
          {usdFormatter(totalCost)}
        </span>
      )}

      {isExecuting && (
        <span className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
      )}
    </div>
  )
}

function ObservationPanelContent() {
  return (
    <div className="flex h-full flex-col">
      <Toolbar />
      <PanelGroup direction="horizontal" className="flex-1">
        <Panel defaultSize={40} minSize={20} collapsible collapsedSize={3}>
          <ObservationNavigation />
        </Panel>
        <PanelResizeHandle className="w-px bg-border hover:bg-primary-accent/50 transition-colors" />
        <Panel defaultSize={60} minSize={30}>
          <ObservationDetailPanel />
        </Panel>
      </PanelGroup>
    </div>
  )
}

export function ObservationPanel() {
  return (
    <ObservationViewPrefsProvider>
      <ObservationDataProvider>
        <Suspense fallback={null}>
          <ObservationSelectionProvider>
            <ObservationJsonExpansionProvider>
              <ObservationPanelContent />
            </ObservationJsonExpansionProvider>
          </ObservationSelectionProvider>
        </Suspense>
      </ObservationDataProvider>
    </ObservationViewPrefsProvider>
  )
}
