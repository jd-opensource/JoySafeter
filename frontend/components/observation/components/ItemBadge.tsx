import { cn } from '@/lib/utils'
import { OBSERVATION_ICON_MAP, OBSERVATION_COLOR_MAP } from '../lib/constants'
import type { ObservationType } from '../lib/types'
import { ListTree } from 'lucide-react'

interface ItemBadgeProps {
  type: ObservationType
  isSmall?: boolean
  showLabel?: boolean
  className?: string
}

export function ItemBadge({ type, isSmall, showLabel, className }: ItemBadgeProps) {
  const Icon = OBSERVATION_ICON_MAP[type] ?? ListTree
  const color = OBSERVATION_COLOR_MAP[type] ?? 'text-muted-foreground'

  return (
    <span className={cn('inline-flex items-center gap-1', className)}>
      <Icon className={cn(color, isSmall ? 'h-3 w-3' : 'h-4 w-4')} />
      {showLabel && (
        <span className="text-xs text-muted-foreground">{type}</span>
      )}
    </span>
  )
}
