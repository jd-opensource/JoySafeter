'use client'

import { useId } from 'react'
import { cn } from '@/lib/utils'
import { AreaChart, Area, ResponsiveContainer } from 'recharts'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
import { HelpCircle } from 'lucide-react'

interface StatTileProps {
  label: string
  value: string
  tooltip?: string
  delta?: string | null
  deltaDirection?: 'up' | 'down' | 'neutral'
  deltaInverse?: boolean
  sparklineData?: number[]
  loading?: boolean
}

function getDeltaColor(direction: 'up' | 'down' | 'neutral', inverse: boolean) {
  if (direction === 'neutral') return 'text-muted-foreground'

  const isPositive = inverse ? direction === 'down' : direction === 'up'
  return isPositive ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'
}

function getDeltaArrow(direction: 'up' | 'down' | 'neutral') {
  if (direction === 'up') return '↑'
  if (direction === 'down') return '↓'
  return ''
}

export function StatTile({
  label,
  value,
  tooltip,
  delta,
  deltaDirection = 'neutral',
  deltaInverse = false,
  sparklineData,
  loading = false,
}: StatTileProps) {
  const gradientId = useId()

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <div className="h-3 w-20 animate-pulse rounded bg-muted" />
        <div className="mt-3 h-7 w-24 animate-pulse rounded bg-muted" />
        <div className="mt-2 h-3 w-16 animate-pulse rounded bg-muted" />
      </div>
    )
  }

  const chartData = sparklineData?.map((v, i) => ({ i, v }))

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-center gap-1">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        {tooltip && (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <HelpCircle className="h-3 w-3 shrink-0 cursor-help text-muted-foreground/60" />
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-[240px] text-xs">
                {tooltip}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
      <p className="mt-1.5 text-2xl font-semibold text-foreground">{value}</p>
      <div className="mt-2 flex items-center gap-3">
        {delta && (
          <span className={cn('text-xs font-medium', getDeltaColor(deltaDirection, deltaInverse))}>
            {getDeltaArrow(deltaDirection)} {delta}
          </span>
        )}
        {chartData && chartData.length > 1 && (
          <div className="h-8 w-20">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.1} />
                    <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="v"
                  stroke="var(--chart-1)"
                  strokeWidth={1.5}
                  fill={`url(#${gradientId})`}
                  dot={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}
