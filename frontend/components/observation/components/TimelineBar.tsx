import { cn } from '@/lib/utils'
import { ItemBadge } from './ItemBadge'
import { formatIntervalSeconds, usdFormatter, heatMapTextColor } from '../lib/helpers'
import type { ObservationNode, TimelineMetrics } from '../lib/types'

interface TimelineBarProps {
  node: ObservationNode
  metrics: TimelineMetrics
  isSelected: boolean
  onSelect: () => void
  showCostTokens: boolean
  colorCodeMetrics: boolean
  parentTotalCost?: number
}

export function TimelineBar({
  node,
  metrics,
  isSelected,
  onSelect,
  showCostTokens,
  colorCodeMetrics,
  parentTotalCost,
}: TimelineBarProps) {
  const { startOffset, itemWidth, firstTokenTimeOffset } = metrics

  if (firstTokenTimeOffset != null && itemWidth > 0) {
    const firstTokenWidth = firstTokenTimeOffset - startOffset
    const completionWidth = itemWidth - firstTokenWidth

    return (
      <div
        className={cn('flex cursor-pointer', isSelected && 'ring-3 ring-primary-accent rounded-sm')}
        style={{ marginLeft: `${startOffset}px` }}
        onClick={onSelect}
      >
        <div
          className="flex h-8 items-center rounded-l-sm border-r border-gray-400 bg-muted opacity-60"
          style={{ width: `${Math.max(firstTokenWidth, 2)}px` }}
        />
        <div
          className="flex h-8 items-center gap-1 overflow-hidden rounded-r-sm bg-muted px-1"
          style={{ width: `${Math.max(completionWidth, 2)}px` }}
        >
          <ItemBadge type={node.type} isSmall />
          <span className="truncate text-xs">{node.name}</span>
        </div>
      </div>
    )
  }

  const barWidth = itemWidth || 10
  const isDashed = !itemWidth

  return (
    <div
      className={cn(
        'flex h-8 cursor-pointer items-center gap-1 overflow-hidden rounded-sm bg-muted px-1',
        isDashed && 'border border-dashed',
        isSelected && 'ring-3 ring-primary-accent',
      )}
      style={{
        marginLeft: `${startOffset}px`,
        width: `${barWidth}px`,
      }}
      onClick={onSelect}
    >
      <ItemBadge type={node.type} isSmall />
      <span className="truncate text-xs">{node.name}</span>
      {metrics.latency != null && (
        <span className="shrink-0 text-xs text-muted-foreground">
          {formatIntervalSeconds(metrics.latency)}
        </span>
      )}
      {showCostTokens && node.totalCost > 0 && (
        <span
          className={cn(
            'shrink-0 text-xs text-muted-foreground',
            colorCodeMetrics &&
              parentTotalCost &&
              heatMapTextColor({ max: parentTotalCost, value: node.totalCost }),
          )}
        >
          {usdFormatter(node.totalCost)}
        </span>
      )}
    </div>
  )
}
