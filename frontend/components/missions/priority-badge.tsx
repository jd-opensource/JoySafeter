'use client'

import { cn } from '@/lib/utils'
import type { MissionPriority } from '@/types/missions'
import { MISSION_PRIORITY_LABELS } from '@/types/missions'

const PRIORITY_STYLES: Record<MissionPriority, string> = {
  urgent: 'bg-red-100 text-red-700 border-red-200',
  high: 'bg-orange-100 text-orange-700 border-orange-200',
  medium: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  low: 'bg-blue-100 text-blue-700 border-blue-200',
  none: 'bg-gray-100 text-gray-600 border-gray-200',
}

interface PriorityBadgeProps {
  priority: MissionPriority
  className?: string
}

export function PriorityBadge({ priority, className }: PriorityBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        PRIORITY_STYLES[priority],
        className,
      )}
    >
      {MISSION_PRIORITY_LABELS[priority]}
    </span>
  )
}
