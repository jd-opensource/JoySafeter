import { cn } from '@/lib/utils'

interface PulsingDotProps {
  size?: 'sm' | 'md'
  className?: string
}

const SIZE_CLASSES = {
  sm: 'h-1.5 w-1.5',
  md: 'h-2 w-2',
} as const

export function PulsingDot({ size = 'md', className }: PulsingDotProps) {
  const sizeClass = SIZE_CLASSES[size]
  return (
    <span className={cn('relative flex', sizeClass, className)}>
      <span className={cn('absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75')} />
      <span className={cn('relative inline-flex rounded-full bg-current', sizeClass)} />
    </span>
  )
}
