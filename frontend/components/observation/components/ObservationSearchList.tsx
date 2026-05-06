'use client'

import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import { useObservationData } from '../contexts/ObservationDataContext'
import { useObservationSelection } from '../contexts/ObservationSelectionContext'
import { ItemBadge } from './ItemBadge'
import { formatIntervalSeconds } from '../lib/helpers'

export function ObservationSearchList() {
  const { searchItems } = useObservationData()
  const { searchQuery, selectedNodeId, selectNode, setSearchQueryImmediate } =
    useObservationSelection()

  const results = useMemo(() => {
    if (!searchQuery.trim()) return []
    const q = searchQuery.toLowerCase()
    return searchItems.filter(
      (item) =>
        item.node.type.toLowerCase().includes(q) ||
        item.node.name.toLowerCase().includes(q) ||
        item.node.id.toLowerCase().includes(q),
    )
  }, [searchItems, searchQuery])

  if (results.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No results for &quot;{searchQuery}&quot;
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto">
      {results.map((item) => (
        <div
          key={item.observationId}
          className={cn(
            'flex cursor-pointer items-center gap-2 px-3 py-2 hover:bg-muted/50',
            item.observationId === selectedNodeId && 'bg-muted',
          )}
          onClick={() => {
            selectNode(item.observationId)
            setSearchQueryImmediate('')
          }}
        >
          <ItemBadge type={item.node.type} />
          <span className="truncate text-sm">{item.node.name}</span>
          {item.node.latency != null && (
            <span className="shrink-0 text-xs text-muted-foreground">
              {formatIntervalSeconds(item.node.latency)}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
