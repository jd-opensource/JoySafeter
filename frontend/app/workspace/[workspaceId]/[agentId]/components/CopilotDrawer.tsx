'use client'

import { Sparkles, Minimize2 } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { CopilotPanel } from './CopilotPanel'

interface CopilotDrawerProps {
  className?: string
}

export function CopilotDrawer({ className }: CopilotDrawerProps) {
  const { t } = useTranslation()
  const [isOpen, setIsOpen] = useState(false)

  return (
    <>
      {/* Floating AI Button */}
      <div className={cn('fixed z-30', className)}>
        <Button
          onClick={() => setIsOpen(true)}
          className={cn(
            'h-9 gap-2 rounded-lg px-3 shadow-md',
            'bg-gradient-to-r from-violet-500 to-purple-500 hover:from-violet-600 hover:to-purple-600',
            'text-xs font-medium text-white',
            'transition-all duration-200 hover:shadow-lg',
            'border border-violet-400/30',
            isOpen && 'pointer-events-none opacity-0',
          )}
        >
          <Sparkles size={14} />
          <span>{t('workspace.aiAssistant')}</span>
        </Button>
      </div>

      {/* Copilot Panel - Fixed position, no overlay */}
      <div
        className={cn(
          'fixed bottom-2 top-2 z-40 flex w-[380px] flex-col',
          'overflow-hidden rounded-xl bg-white',
          'border border-gray-200/80 shadow-2xl shadow-black/10',
          'transition-all duration-300 ease-out',
          isOpen
            ? 'right-[290px] translate-x-0 opacity-100'
            : 'pointer-events-none right-[290px] translate-x-4 opacity-0',
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 bg-gradient-to-r from-violet-50/80 to-purple-50/80 px-4 py-3 backdrop-blur-sm">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-purple-500 shadow-sm">
              <Sparkles size={14} className="text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold leading-tight text-gray-900">
                {t('workspace.copilot', { defaultValue: 'Copilot' })}
              </h3>
              <p className="text-[10px] leading-tight text-gray-500">
                {t('workspace.copilotSubtitle')}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsOpen(false)}
            className="h-7 w-7 rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-700"
          >
            <Minimize2 size={14} />
          </Button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden bg-gray-50/30">
          <CopilotPanel />
        </div>
      </div>
    </>
  )
}
