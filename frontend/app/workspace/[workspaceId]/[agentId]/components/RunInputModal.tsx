'use client'

import { Activity, Sparkles, Zap, X } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'

interface RunInputModalProps {
  isOpen: boolean
  input: string
  onInputChange: (value: string) => void
  onStart: () => void
  onClose: () => void
}

export function RunInputModal({
  isOpen,
  input,
  onInputChange,
  onStart,
  onClose,
}: RunInputModalProps) {
  const { t } = useTranslation()

  if (!isOpen) return null

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && input.trim()) {
      onStart()
    }
  }

  return (
    <div className="pointer-events-none fixed right-[12px] top-[68px] z-[100] w-[380px]">
      <div className="pointer-events-auto overflow-hidden rounded-2xl border border-gray-200 bg-white/95 shadow-2xl backdrop-blur-xl duration-300 animate-in slide-in-from-top-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 bg-white/50 px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="rounded-md bg-blue-600 p-1 text-white">
              <Activity size={14} />
            </div>
            <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-900">
              {t('workspace.readyToStart')}
            </h3>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-6 w-6 text-gray-400 hover:text-gray-900"
          >
            <X size={12} />
          </Button>
        </div>

        {/* Content */}
        <div className="space-y-4 p-4">
          {/* Info Banner */}
          <div className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/50 p-3">
            <Sparkles className="mt-0.5 shrink-0 text-blue-500" size={16} />
            <p className="text-[10px] font-medium leading-relaxed text-blue-700">
              {t('workspace.enterPrompt')}
            </p>
          </div>

          {/* Input and Run Button */}
          <div className="flex gap-2">
            <Input
              placeholder={t('workspace.simulateUserInput')}
              className="h-9 border-gray-200 bg-white text-[11px] focus-visible:ring-blue-100"
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              autoFocus
            />
            <Button
              size="sm"
              className="h-9 gap-2 bg-blue-600 px-4 text-[11px] font-bold hover:bg-blue-700"
              onClick={onStart}
              disabled={!input.trim()}
            >
              <Zap size={12} className="fill-current" />
              {t('workspace.run')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
