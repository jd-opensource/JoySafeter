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

import {
  Activity,
  ChevronDown,
  Trash2,
  TreePine,
  GanttChart,
  Search,
  X,
} from 'lucide-react'
import React, { useEffect, useState, useCallback, useRef, useDeferredValue } from 'react'
import {
  PanelGroup,
  Panel,
  PanelResizeHandle,
} from 'react-resizable-panels'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

import { useExecutionStore } from '../../stores/executionStore'

import { ExecutionDataProvider, useExecutionData } from './contexts/ExecutionDataContext'
import { ExecutionSelectionProvider, useExecutionSelection } from './contexts/ExecutionSelectionContext'
import { ExecutionViewPreferencesProvider } from './contexts/ExecutionViewPreferencesContext'
import { ExecutionTree } from './ExecutionTree'
import { ExecutionTimelineView } from './ExecutionTimeline'
import { ExecutionDetailPanel } from './ExecutionDetailPanel'
import { InterruptPanel } from '../InterruptPanel'

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
        .find((s) =>
          s.stepType === 'tool_execution' ||
          s.stepType === 'model_io' ||
          (s.stepType === 'agent_thought' && s.content) ||
          s.stepType === 'code_agent_code' ||
          s.stepType === 'code_agent_observation'
        )
      if (lastInterestingStep) {
        selectNode(lastInterestingStep.id)
      }
    }
  }, [deferredSteps.length, isExecuting, selectNode, deferredSteps])

  // Keyboard navigation
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!flatItems.length) return

    const currentIdx = flatItems.findIndex(item => item.node.id === selectedNodeId)

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
  }, [flatItems, selectedNodeId, selectNode, isSearching])

  // Get the first interrupt (if any)
  const firstInterrupt = pendingInterrupts.size > 0
    ? Array.from(pendingInterrupts.values())[0]
    : null

  return (
    <div
      className="h-[320px] w-[calc(100%-320px)] bg-white border-t border-gray-200 shadow-[0_-4px_20px_rgba(0,0,0,0.05)] flex flex-col shrink-0 z-40 animate-in slide-in-from-bottom-10 duration-300 font-sans"
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      <PanelGroup direction="horizontal" className="flex-1 min-h-0">
        {/* Left Panel: Navigation (Tree / Timeline) */}
        <Panel defaultSize={35} minSize={25} maxSize={60}>
          <div className="h-full flex flex-col border-r border-gray-200 bg-white">
            {/* Panel Header */}
            <div className="h-9 border-b border-gray-200 flex items-center justify-between px-3 bg-gray-50/80 select-none shrink-0 backdrop-blur-sm">
              <div className="flex items-center gap-2">
                <Activity size={13} className="text-blue-600" />
                <span className="text-[10px] font-bold text-gray-700 uppercase tracking-widest">
                  {t('workspace.executionStream', { defaultValue: 'Trace' })}
                </span>
                <div className="w-[1px] h-3 bg-gray-300" />
                <span className="text-[9px] text-gray-500 font-mono">
                  {deferredSteps.length} {t('workspace.ops', { defaultValue: 'OPS' })}
                </span>
                {isExecuting && (
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
                )}
              </div>
              <div className="flex items-center gap-1">
                {/* View Toggle: Tree / Timeline */}
                <div className="flex items-center gap-0.5 bg-gray-100 rounded p-0.5 border border-gray-200">
                  <button
                    onClick={() => setNavigationView('tree')}
                    className={cn(
                      'p-0.5 rounded transition-colors',
                      navigationView === 'tree'
                        ? 'bg-white text-blue-600 shadow-sm'
                        : 'text-gray-400 hover:text-gray-600'
                    )}
                    title="Tree View"
                  >
                    <TreePine size={12} />
                  </button>
                  <button
                    onClick={() => setNavigationView('timeline')}
                    className={cn(
                      'p-0.5 rounded transition-colors',
                      navigationView === 'timeline'
                        ? 'bg-white text-blue-600 shadow-sm'
                        : 'text-gray-400 hover:text-gray-600'
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
                    'p-1 rounded transition-colors',
                    isSearching
                      ? 'bg-blue-50 text-blue-600'
                      : 'text-gray-400 hover:bg-gray-200 hover:text-gray-700'
                  )}
                  title="Search (press /)"
                >
                  <Search size={12} />
                </button>

                <button
                  onClick={() => clearExecution()}
                  className="p-1 hover:bg-gray-200 rounded text-gray-400 hover:text-gray-700 transition-colors"
                  title={t('workspace.clearTrace', { defaultValue: 'Clear Trace' })}
                >
                  <Trash2 size={12} />
                </button>
                <button
                  onClick={() => toggleExecutionPanel(false)}
                  className="flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-red-50 rounded text-gray-400 hover:text-red-600 transition-colors border border-transparent hover:border-red-200"
                  title={t('workspace.closePanel', { defaultValue: 'Close Panel' })}
                >
                  <ChevronDown size={12} />
                  <span className="text-[9px] font-medium">{t('workspace.close', { defaultValue: 'Close' })}</span>
                </button>
              </div>
            </div>

            {/* Search Bar */}
            {isSearching && (
              <div className="h-8 border-b border-gray-200 flex items-center px-3 gap-2 bg-white shrink-0">
                <Search size={12} className="text-gray-400 shrink-0" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search steps..."
                  className="flex-1 text-[11px] bg-transparent outline-none text-gray-700 placeholder:text-gray-300 font-mono"
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
                    className="p-0.5 text-gray-400 hover:text-gray-600"
                  >
                    <X size={10} />
                  </button>
                )}
              </div>
            )}

            {/* View Content */}
            <div className="flex-1 min-h-0">
              {navigationView === 'tree' ? (
                <ExecutionTree searchQuery={searchQuery} />
              ) : (
                <ExecutionTimelineView />
              )}
            </div>
          </div>
        </Panel>

        {/* Resize Handle */}
        <PanelResizeHandle className="w-px bg-gray-200 hover:bg-blue-300 transition-colors data-[resize-handle-state=drag]:bg-blue-400 relative after:absolute after:inset-y-0 after:-left-0.5 after:w-1.5 after:content-['']" />

        {/* Right Panel: Details or Interrupt */}
        <Panel defaultSize={65} minSize={40}>
          <div className="h-full min-w-0 bg-gray-50">
            {firstInterrupt ? (
              <div className="h-full overflow-auto p-4">
                <InterruptPanel
                  interrupt={firstInterrupt}
                  onClose={() => {}}
                />
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

export const ExecutionPanelNew: React.FC = () => {
  const {
    steps,
    isExecuting,
    treeRoots,
    treeNodeMap,
  } = useExecutionStore()

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
