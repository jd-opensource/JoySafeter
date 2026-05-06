import { cn } from '@/lib/utils'
import { ChevronRight } from 'lucide-react'
import { ItemBadge } from './ItemBadge'
import type { ObservationFlatItem, ObservationType } from '../lib/types'
import type { ReactNode } from 'react'

interface ObservationNodeWrapperProps {
  metadata: ObservationFlatItem
  nodeType: ObservationType
  hasChildren: boolean
  isCollapsed: boolean
  onToggleCollapse: () => void
  isSelected: boolean
  onSelect: () => void
  isError: boolean
  children: ReactNode
}

export function ObservationNodeWrapper({
  metadata,
  nodeType,
  hasChildren,
  isCollapsed,
  onToggleCollapse,
  isSelected,
  onSelect,
  isError,
  children,
}: ObservationNodeWrapperProps) {
  const { depth, treeLines, isLastSibling } = metadata

  return (
    <div
      className={cn(
        'flex w-full cursor-pointer items-center pr-1',
        isSelected && 'ring-primary-accent rounded-sm bg-muted/50 ring-2',
        isError && 'border-l-2 border-red-500',
      )}
      onClick={onSelect}
    >
      {treeLines.map((hasLine, i) => (
        <div key={i} className="relative w-5 shrink-0 self-stretch">
          {hasLine && <div className="absolute bottom-0 left-3 top-0 w-px bg-border" />}
        </div>
      ))}

      {depth > 0 && (
        <div className="relative w-[5px] shrink-0 self-stretch">
          <div
            className={cn(
              'absolute left-3 top-0 w-px bg-border',
              isLastSibling ? 'h-3' : 'bottom-0',
            )}
          />
          <div className="absolute left-3 top-3 h-px w-2 bg-border" />
        </div>
      )}

      <div className="relative flex w-6 shrink-0 items-center justify-center self-stretch">
        <ItemBadge type={nodeType} />
        {hasChildren && !isCollapsed && (
          <div className="absolute bottom-0 left-1/2 top-3 w-px bg-border" />
        )}
      </div>

      <div className="min-w-0 flex-1 py-1">{children}</div>

      {hasChildren && (
        <button
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm hover:bg-muted"
          onClick={(e) => {
            e.stopPropagation()
            onToggleCollapse()
          }}
        >
          <ChevronRight
            className={cn(
              'h-4 w-4 text-muted-foreground transition-transform duration-200 ease-in-out',
              !isCollapsed && 'rotate-90',
            )}
          />
        </button>
      )}
    </div>
  )
}
