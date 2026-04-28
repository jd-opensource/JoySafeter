'use client'

import { cn } from '@/lib/utils'
import { useObservationData } from '../contexts/ObservationDataContext'
import { useObservationSelection } from '../contexts/ObservationSelectionContext'
import { ItemBadge } from './ItemBadge'
import { IOPreview } from './IOPreview'
import {
  formatIntervalSeconds,
  usdFormatter,
  formatTokenCounts,
} from '../lib/helpers'
import type { ObservationNode } from '../lib/types'

function TraceSummaryView() {
  const { roots } = useObservationData()

  if (roots.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No trace data. Run a debug execution or select a historical trace.
      </div>
    )
  }

  const totalCost = roots.reduce((sum, r) => sum + r.totalCost, 0)
  const totalDuration = Math.max(...roots.map((r) => r.latency ?? 0))

  return (
    <div className="space-y-2 p-4">
      <h3 className="text-sm font-medium">Trace Summary</h3>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="text-muted-foreground">Duration</div>
        <div>{formatIntervalSeconds(totalDuration)}</div>
        <div className="text-muted-foreground">Total Cost</div>
        <div>{usdFormatter(totalCost)}</div>
      </div>
    </div>
  )
}

function ObservationHeader({ node }: { node: ObservationNode }) {
  return (
    <div className="space-y-2 border-b px-4 py-3">
      <div className="flex items-center gap-2">
        <ItemBadge type={node.type} showLabel />
        <span className="truncate text-sm font-medium">{node.name}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {node.latency != null && (
          <span className="rounded bg-muted px-2 py-0.5 text-xs">
            {formatIntervalSeconds(node.latency)}
          </span>
        )}
        {node.totalCost > 0 && (
          <span className="rounded bg-muted px-2 py-0.5 text-xs" title="Total cost (including children)">
            {node.children.length > 0 ? '∑ ' : ''}
            {usdFormatter(node.totalCost)}
          </span>
        )}
        {(node.totalUsage ?? node.inputUsage ?? node.outputUsage) != null && (
          <span className="rounded bg-muted px-2 py-0.5 text-xs">
            {formatTokenCounts(node.inputUsage, node.outputUsage, node.totalUsage)}
          </span>
        )}
        {node.model && (
          <span className="rounded bg-muted px-2 py-0.5 text-xs">
            {node.model}
          </span>
        )}
        {node.level !== 'DEFAULT' && (
          <span
            className={cn(
              'rounded px-2 py-0.5 text-xs',
              node.level === 'ERROR' && 'bg-red-100 text-red-700',
              node.level === 'WARNING' && 'bg-yellow-100 text-yellow-700',
              node.level === 'DEBUG' && 'bg-gray-100 text-gray-600',
            )}
          >
            {node.level}
          </span>
        )}
      </div>
    </div>
  )
}

function ObservationDetail({ node }: { node: ObservationNode }) {
  const { viewPref } = useObservationSelection()

  return (
    <div className="h-full overflow-auto">
      <ObservationHeader node={node} />
      <IOPreview
        input={node.input}
        output={node.output}
        metadata={node.metadata}
        observationName={node.name}
        currentView={viewPref === 'formatted' ? 'pretty' : 'json'}
      />
    </div>
  )
}

export function ObservationDetailPanel() {
  const { nodeMap } = useObservationData()
  const { selectedNodeId } = useObservationSelection()

  const selectedNode = selectedNodeId ? nodeMap.get(selectedNodeId) : null

  if (!selectedNode) return <TraceSummaryView />
  return <ObservationDetail node={selectedNode} />
}
