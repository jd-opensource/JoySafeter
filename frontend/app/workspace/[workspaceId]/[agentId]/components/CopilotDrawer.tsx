'use client'

import { Sparkles, X, Minimize2 } from 'lucide-react'
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
            'h-9 gap-2 px-3 rounded-lg shadow-md',
            'bg-gradient-to-r from-violet-500 to-purple-500 hover:from-violet-600 hover:to-purple-600',
            'text-white font-medium text-xs',
            'transition-all duration-200 hover:shadow-lg',
            'border border-violet-400/30',
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
          'bg-white rounded-xl overflow-hidden',
          'border border-gray-200/80 shadow-2xl shadow-black/10',
          'transition-all duration-300 ease-out',
          isOpen
            ? 'right-[290px] opacity-100 translate-x-0'
            : 'right-[290px] opacity-0 translate-x-4 pointer-events-none'
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-gradient-to-r from-violet-50/80 to-purple-50/80 backdrop-blur-sm">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-purple-500 flex items-center justify-center shadow-sm">
              <Sparkles size={14} className="text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900 leading-tight">
                {t('workspace.copilot', { defaultValue: 'Copilot' })}
              </h3>
              <p className="text-[10px] text-gray-500 leading-tight">
                {t('workspace.aiPoweredAssistant')}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setIsOpen(false)}
            className="h-7 w-7 rounded-md hover:bg-gray-100 text-gray-500 hover:text-gray-700"
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
