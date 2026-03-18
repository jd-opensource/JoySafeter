'use client'

import { Sparkles, Minimize2 } from 'lucide-react'
import React, { useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

import { CopilotPanel } from './CopilotPanel'


interface CopilotDrawerProps {
  className?: string
}

export const CopilotDrawer: React.FC<CopilotDrawerProps> = ({ className }) => {
  const { t } = useTranslation()
  const [isOpen, setIsOpen] = useState(false)

  return (
    <>
      {/* Floating AI Button */}
      <div className={cn('fixed z-30', className)}>
        <Button
          onClick={() => setIsOpen(true)}
          className={cn(
            'h-10 gap-2 px-4 rounded-full shadow-md',
            'bg-[linear-gradient(180deg,var(--brand-400),var(--brand-500))] hover:bg-[linear-gradient(180deg,var(--brand-400),var(--brand-600))]',
            'text-white font-medium text-xs',
            'transition-all duration-200 hover:shadow-lg',
            'border border-[var(--border-strong)]',
            isOpen && 'opacity-0 pointer-events-none'
          )}
        >
          <Sparkles size={14} />
          <span>{t('workspace.aiAssistant')}</span>
        </Button>
      </div>

      {/* Copilot Panel - Fixed position, no overlay */}
      <div
        className={cn(
          'fixed top-2 bottom-2 z-40 w-[380px] flex flex-col',
          'bg-[var(--surface-elevated)] rounded-[22px] overflow-hidden',
          'border border-[var(--border)] shadow-[0_24px_60px_rgba(15,23,42,0.12)]',
          'transition-all duration-300 ease-out',
          isOpen
            ? 'right-[290px] opacity-100 translate-x-0'
            : 'right-[290px] opacity-0 translate-x-4 pointer-events-none'
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--divider)] bg-[rgba(255,255,255,0.58)]">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-[linear-gradient(180deg,var(--brand-400),var(--brand-500))] flex items-center justify-center shadow-sm">
              <Sparkles size={14} className="text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text-primary)] leading-tight">
                {t('workspace.copilot', { defaultValue: 'Copilot' })}
              </h3>
              <p className="text-[10px] text-[var(--text-secondary)] leading-tight">
                {t('workspace.copilotSubtitle')}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsOpen(false)}
            className="h-7 w-7 rounded-md hover:bg-[var(--surface-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            <Minimize2 size={14} />
          </Button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden bg-[rgba(255,255,255,0.32)]">
          <CopilotPanel />
        </div>
      </div>
    </>
  )
}
