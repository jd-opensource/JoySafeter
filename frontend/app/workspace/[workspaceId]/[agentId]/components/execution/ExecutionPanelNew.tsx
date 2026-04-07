'use client'

/**
 * ExecutionPanelNew - Langfuse-style execution trace viewer.
 *
 * Architecture:
 * - Left panel: Tree / Timeline view with search
 * - Right panel: Tabbed detail view (Preview / Output / Metadata)
 * - Resizable split via react-resizable-panels
 * - Context Providers for data, selection, and view preferences
 * - Keyboard navigation (up/down arrows, enter to select)
 */

import { Activity, ChevronDown, Trash2, TreePine, GanttChart, Search, X } from 'lucide-react'
import React, { useEffect, useState, useCallback, useRef, useDeferredValue } from 'react'
import { PanelGroup, Panel, PanelResizeHandle } from 'react-resizable-panels'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useExecutionStore } from '../../stores/executionStore'
import { InterruptPanel } from '../InterruptPanel'

import { ExecutionDataProvider, useExecutionData } from './contexts/ExecutionDataContext'
import {
  ExecutionSelectionProvider,
  useExecutionSelection,
} from './contexts/ExecutionSelectionContext'
import { ExecutionViewPreferencesProvider } from './contexts/ExecutionViewPreferencesContext'
import { ExecutionDetailPanel } from './ExecutionDetailPanel'
import { ExecutionTimelineView } from './ExecutionTimeline'
import { ExecutionTree } from './ExecutionTree'

type NavigationView = 'tree' | 'timeline'

// ============ Inner Content (has access to contexts) ============

function ExecutionPanelContent() {
  const { t } = useTranslation()
  const {
    steps: executionSteps,
    isExecuting,
    togglePanel: toggleExecutionPanel,
    clear: clearExecution,
    pendingInterrupts,
  } = useExecutionStore()

  const deferredSteps = useDeferredValue(executionSteps)
  const { flatItems } = useExecutionData()
  const { selectedNodeId, selectNode } = useExecutionSelection()

  const [navigationView, setNavigationView] = useState<NavigationView>('tree')
  const [searchQuery, setSearchQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Auto-select latest interesting step during execution
  useEffect(() => {
    if (isExecuting && deferredSteps.length > 0) {
      const lastInterestingStep = [...deferredSteps]
        .reverse()
        .find(
          (s) =>
            s.stepType === 'tool_execution' ||
            s.stepType === 'model_io' ||
            (s.stepType === 'agent_thought' && s.content) ||
            s.stepType === 'code_agent_code' ||
            s.stepType === 'code_agent_observation',
        )
      if (lastInterestingStep) {
        selectNode(lastInterestingStep.id)
      }
    }
  }, [deferredSteps.length, isExecuting, selectNode, deferredSteps])

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!flatItems.length) return

      const currentIdx = flatItems.findIndex((item) => item.node.id === selectedNodeId)

      switch (e.key) {
        case 'ArrowDown': {
          e.preventDefault()
          const nextIdx = currentIdx < flatItems.length - 1 ? currentIdx + 1 : 0
          selectNode(flatItems[nextIdx].node.id)
          break
        }
        case 'ArrowUp': {
          e.preventDefault()
          const prevIdx = currentIdx > 0 ? currentIdx - 1 : flatItems.length - 1
          selectNode(flatItems[prevIdx].node.id)
          break
        }
        case '/': {
          e.preventDefault()
          setIsSearching(true)
          setTimeout(() => searchInputRef.current?.focus(), 0)
          break
        }
        case 'Escape': {
          if (isSearching) {
            setIsSearching(false)
            setSearchQuery('')
          }
          break
        }
      }
    },
    [flatItems, selectedNodeId, selectNode, isSearching],
  )

  // Get the first interrupt (if any)
  const firstInterrupt =
    pendingInterrupts.size > 0 ? Array.from(pendingInterrupts.values())[0] : null

  return (
    <div
      className="z-40 flex h-[320px] w-[calc(100%-320px)] shrink-0 flex-col border-t border-[var(--border)] bg-[var(--surface-elevated)] font-sans shadow-[0_-4px_20px_rgba(0,0,0,0.05)] duration-300 animate-in slide-in-from-bottom-10"
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      <PanelGroup direction="horizontal" className="min-h-0 flex-1">
        {/* Left Panel: Navigation (Tree / Timeline) */}
        <Panel defaultSize={35} minSize={25} maxSize={60}>
          <div className="flex h-full flex-col border-r border-[var(--border)] bg-[var(--surface-elevated)]">
            {/* Panel Header */}
            <div className="flex h-9 shrink-0 select-none items-center justify-between border-b border-[var(--border)] bg-[var(--surface-2)] px-3 backdrop-blur-sm">
              <div className="flex items-center gap-2">
                <Activity size={13} className="text-primary" />
                <span className="text-2xs font-bold uppercase tracking-widest text-[var(--text-secondary)]">
                  {t('workspace.executionStream', { defaultValue: 'Trace' })}
                </span>
                <div className="h-3 w-[1px] bg-[var(--border-strong)]" />
                <span className="font-mono text-micro text-[var(--text-tertiary)]">
                  {deferredSteps.length} {t('workspace.ops', { defaultValue: 'OPS' })}
                </span>
                {isExecuting && (
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-500" />
                )}
              </div>
              <div className="flex items-center gap-1">
                {/* View Toggle: Tree / Timeline */}
                <div className="flex items-center gap-0.5 rounded border border-[var(--border)] bg-[var(--surface-3)] p-0.5">
                  <button
                    onClick={() => setNavigationView('tree')}
                    className={cn(
                      'rounded p-0.5 transition-colors',
                      navigationView === 'tree'
                        ? 'bg-[var(--surface-elevated)] text-primary shadow-sm'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                    )}
                    title="Tree View"
                  >
                    <TreePine size={12} />
                  </button>
                  <button
                    onClick={() => setNavigationView('timeline')}
                    className={cn(
                      'rounded p-0.5 transition-colors',
                      navigationView === 'timeline'
                        ? 'bg-[var(--surface-elevated)] text-primary shadow-sm'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                    )}
                    title="Timeline View"
                  >
                    <GanttChart size={12} />
                  </button>
                </div>

                {/* Search toggle */}
                <button
                  onClick={() => {
                    setIsSearching(!isSearching)
                    if (!isSearching) {
                      setTimeout(() => searchInputRef.current?.focus(), 0)
                    } else {
                      setSearchQuery('')
                    }
                  }}
                  className={cn(
                    'rounded p-1 transition-colors',
                    isSearching
                      ? 'bg-primary/5 text-primary'
                      : 'text-[var(--text-muted)] hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]',
                  )}
                  title="Search (press /)"
                >
                  <Search size={12} />
                </button>

                <button
                  onClick={() => clearExecution()}
                  className="rounded p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
                  title={t('workspace.clearTrace', { defaultValue: 'Clear Trace' })}
                >
                  <Trash2 size={12} />
                </button>
                <button
                  onClick={() => toggleExecutionPanel(false)}
                  className="flex items-center gap-0.5 rounded border border-transparent px-1.5 py-0.5 text-[var(--text-muted)] transition-colors hover:border-[var(--status-error-border)] hover:bg-[var(--status-error-bg)] hover:text-[var(--status-error)]"
                  title={t('workspace.closePanel', { defaultValue: 'Close Panel' })}
                >
                  <ChevronDown size={12} />
                  <span className="text-micro font-medium">
                    {t('workspace.close', { defaultValue: 'Close' })}
                  </span>
                </button>
              </div>
            </div>

            {/* Search Bar */}
            {isSearching && (
              <div className="flex h-8 shrink-0 items-center gap-2 border-b border-[var(--border)] bg-[var(--surface-elevated)] px-3">
                <Search size={12} className="shrink-0 text-[var(--text-muted)]" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search steps..."
                  className="flex-1 bg-transparent font-mono text-app-xs text-[var(--text-secondary)] outline-none placeholder:text-[var(--text-subtle)]"
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                      setIsSearching(false)
                      setSearchQuery('')
                    }
                  }}
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="p-0.5 text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                  >
                    <X size={10} />
                  </button>
                )}
              </div>
            )}

            {/* View Content */}
            <div className="min-h-0 flex-1">
              {navigationView === 'tree' ? (
                <ExecutionTree searchQuery={searchQuery} />
              ) : (
                <ExecutionTimelineView />
              )}
            </div>
          </div>
        </Panel>

        {/* Resize Handle */}
        <PanelResizeHandle className="relative w-px bg-[var(--border)] transition-colors after:absolute after:inset-y-0 after:-left-0.5 after:w-1.5 after:content-[''] hover:bg-primary/30 data-[resize-handle-state=drag]:bg-primary/50" />

        {/* Right Panel: Details or Interrupt */}
        <Panel defaultSize={65} minSize={40}>
          <div className="h-full min-w-0 bg-[var(--surface-2)]">
            {firstInterrupt ? (
              <div className="h-full overflow-auto p-4">
                <InterruptPanel interrupt={firstInterrupt} onClose={() => {}} />
              </div>
            ) : (
              <ExecutionDetailPanel />
            )}
          </div>
        </Panel>
      </PanelGroup>
    </div>
  )
}

// ============ Main Exported Component ============

export function ExecutionPanelNew() {
  const { steps, isExecuting, treeRoots, treeNodeMap } = useExecutionStore()

  return (
    <ExecutionSelectionProvider>
      <ExecutionSelectionConsumerWrapper
        steps={steps}
        isExecuting={isExecuting}
        treeRoots={treeRoots}
        treeNodeMap={treeNodeMap}
      />
    </ExecutionSelectionProvider>
  )
}

/**
 * Wrapper that reads collapsedIds from SelectionContext
 * to pass into DataProvider.
 */
function ExecutionSelectionConsumerWrapper({
  steps,
  isExecuting,
  treeRoots,
  treeNodeMap,
}: {
  steps: any[]
  isExecuting: boolean
  treeRoots: any[]
  treeNodeMap: Map<string, any>
}) {
  const { collapsedIds } = useExecutionSelection()

  return (
    <ExecutionDataProvider
      steps={steps}
      treeRoots={treeRoots}
      nodeMap={treeNodeMap}
      isExecuting={isExecuting}
      collapsedIds={collapsedIds}
    >
      <ExecutionViewPreferencesProvider>
        <ExecutionPanelContent />
      </ExecutionViewPreferencesProvider>
    </ExecutionDataProvider>
  )
}
