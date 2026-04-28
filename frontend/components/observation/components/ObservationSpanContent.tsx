import { cn } from '@/lib/utils'
import { useObservationViewPrefs } from '../contexts/ObservationViewPrefsContext'
import {
  heatMapTextColor,
  formatIntervalSeconds,
  formatTokenCounts,
  usdFormatter,
} from '../lib/helpers'
import type { ObservationNode } from '../lib/types'

interface ObservationSpanContentProps {
  node: ObservationNode
  parentTotalCost?: number
  parentTotalDuration?: number
}

export function ObservationSpanContent({
  node,
  parentTotalCost,
  parentTotalDuration,
}: ObservationSpanContentProps) {
  const { showDuration, showCostTokens, colorCodeMetrics } =
    useObservationViewPrefs()

  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="truncate text-sm">{node.name}</span>

      {showDuration && node.latency != null && (
        <span
          className={cn(
            'shrink-0 text-xs text-muted-foreground',
            colorCodeMetrics &&
              parentTotalDuration &&
              heatMapTextColor({
                max: parentTotalDuration,
                value: node.latency,
              }),
          )}
        >
          {formatIntervalSeconds(node.latency)}
        </span>
      )}

      {showCostTokens && node.totalCost > 0 && (
        <span
          className={cn(
            'shrink-0 text-xs text-muted-foreground',
            colorCodeMetrics &&
              parentTotalCost &&
              heatMapTextColor({
                max: parentTotalCost,
                value: node.totalCost,
              }),
          )}
        >
          {node.children.length > 0 ? '∑ ' : ''}
          {usdFormatter(node.totalCost)}
        </span>
      )}

      {showCostTokens && (node.totalUsage ?? node.inputUsage ?? node.outputUsage) != null && (
        <span className="shrink-0 text-xs text-muted-foreground">
          {formatTokenCounts(node.inputUsage, node.outputUsage, node.totalUsage)}
        </span>
      )}
    </div>
  )
}
