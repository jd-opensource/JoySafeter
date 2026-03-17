/**
 * CollapsibleList - Reusable collapsible list component
 */

import { ChevronDown, ChevronUp } from 'lucide-react'
import React from 'react'

export interface CollapsibleListProps<T> {
  items: T[]
  expandedKeys: Set<string | number>
  onToggle: (key: string | number) => void
  renderItem: (item: T, index: number) => React.ReactNode
  getKey: (item: T, index: number) => string | number
  defaultVisibleCount?: number
  expandKey: string | number
  className?: string
  buttonClassName?: string
  expandText?: string
  collapseText?: string
}

export function CollapsibleList<T>({
  items,
  expandedKeys,
  onToggle,
  renderItem,
  getKey,
  defaultVisibleCount = 2,
  expandKey,
  className = '',
  buttonClassName = 'flex items-center gap-1.5 text-[9px] text-purple-600 hover:text-purple-700 hover:bg-purple-100/50 px-2 py-1 rounded transition-colors w-full text-left',
  expandText,
  collapseText,
}: CollapsibleListProps<T>) {
  const isExpanded = expandedKeys.has(expandKey)
  const hasMultiple = items.length > defaultVisibleCount
  const visibleItems = hasMultiple && !isExpanded ? items.slice(0, defaultVisibleCount) : items
  const hiddenCount = hasMultiple && !isExpanded ? items.length - defaultVisibleCount : 0

  if (items.length === 0) return null

  return (
    <div className={className}>
      {visibleItems.map((item, idx) => (
        <div key={getKey(item, idx)}>
          {renderItem(item, idx)}
        </div>
      ))}
      {hiddenCount > 0 && (
        <button
          onClick={() => onToggle(expandKey)}
          className={buttonClassName}
        >
          <ChevronDown size={10} />
          <span>{expandText || `展开 ${hiddenCount} 个已折叠的项`}</span>
        </button>
      )}
      {isExpanded && hasMultiple && (
        <button
          onClick={() => onToggle(expandKey)}
          className={buttonClassName}
        >
          <ChevronUp size={10} />
          <span>{collapseText || '折叠列表'}</span>
        </button>
      )}
    </div>
  )
}
