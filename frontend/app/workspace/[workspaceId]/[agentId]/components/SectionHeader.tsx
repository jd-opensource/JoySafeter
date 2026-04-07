'use client'

import React from 'react'
import { AlertCircle } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

export const SectionHeader = ({
  icon: Icon,
  title,
  tooltip,
}: {
  icon: React.ElementType
  title: string
  tooltip?: string
}) => (
  <div className="mb-3 mt-2 flex items-center gap-2">
    <Icon size={14} className="text-[var(--text-muted)]" />
    <div className="flex items-center gap-1.5">
      <h4 className="text-app-xs font-bold uppercase tracking-[0.1em] text-[var(--text-muted)]">{title}</h4>
      {tooltip && (
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <AlertCircle size={11} className="cursor-help text-[var(--text-muted)]" />
            </TooltipTrigger>
            <TooltipContent
              side="top"
              className="max-w-[200px] text-app-xs font-normal normal-case leading-relaxed tracking-normal text-[var(--text-secondary)]"
            >
              {tooltip}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
    </div>
    <div className="ml-1 h-[1px] flex-1 bg-[var(--surface-2)]" />
  </div>
)
