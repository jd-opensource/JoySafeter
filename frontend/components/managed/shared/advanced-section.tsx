'use client'

import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export function AdvancedSection({
  open,
  onOpenChange,
  title,
  summary,
  children,
  className,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  summary?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'overflow-hidden rounded-xl border border-dashed border-border bg-muted/20',
        className,
      )}
    >
      <button
        type="button"
        className="flex w-full items-start gap-3 px-3 py-3 text-left transition-colors hover:bg-muted/40"
        onClick={() => onOpenChange(!open)}
      >
        <ChevronRight
          className={cn(
            'mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-90',
          )}
        />
        <span className="min-w-0 flex-1 space-y-0.5">
          <span className="block text-sm font-medium text-foreground">{title}</span>
          {summary && (
            <span className="block text-xs leading-5 text-muted-foreground">{summary}</span>
          )}
        </span>
      </button>
      {open && (
        <div className="border-border/70 flex flex-col gap-6 border-t px-3 py-4">{children}</div>
      )}
    </div>
  )
}
