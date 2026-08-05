'use client'

import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
import { HelpCircle } from 'lucide-react'

interface ChartContainerProps {
  title: string
  subtitle?: string
  tooltip?: string
  loading?: boolean
  fetching?: boolean
  empty?: boolean
  error?: Error | null
  className?: string
  headerRight?: ReactNode
  children: ReactNode
}

function LoadingSkeleton() {
  return (
    <div className="flex h-[200px] flex-col items-center justify-center gap-3">
      <div className="h-3 w-3/4 animate-pulse rounded bg-muted" />
      <div className="h-3 w-1/2 animate-pulse rounded bg-muted" />
      <div className="h-3 w-2/3 animate-pulse rounded bg-muted" />
    </div>
  )
}

function EmptyState() {
  const { t } = useTranslation()

  return (
    <div className="flex h-[200px] items-center justify-center">
      <p className="text-sm text-muted-foreground">{t('analytics.charts.noData')}</p>
    </div>
  )
}

function ErrorState({ error }: { error: Error }) {
  return (
    <div className="flex h-[200px] items-center justify-center">
      <p className="text-sm text-red-600 dark:text-red-400">{error.message}</p>
    </div>
  )
}

export function ChartContainer({
  title,
  subtitle,
  tooltip: tooltipText,
  loading,
  fetching,
  empty,
  error,
  className,
  headerRight,
  children,
}: ChartContainerProps) {
  return (
    <div className={cn('rounded-lg border border-border bg-card', className)}>
      <div className="flex items-center justify-between p-4 pb-0">
        <div>
          <div className="flex items-center gap-1">
            <h3 className="text-sm font-medium text-foreground">{title}</h3>
            {tooltipText && (
              <TooltipProvider delayDuration={200}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <HelpCircle className="h-3 w-3 shrink-0 cursor-help text-muted-foreground/60" />
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-[280px] text-xs">
                    {tooltipText}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
          {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        {headerRight}
      </div>
      <div className={cn('p-4', fetching && !loading && 'opacity-50 transition-opacity')}>
        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <ErrorState error={error} />
        ) : empty ? (
          <EmptyState />
        ) : (
          children
        )}
      </div>
    </div>
  )
}
