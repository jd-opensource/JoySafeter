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

export const RunInputModal: React.FC<RunInputModalProps> = ({
  isOpen,
  input,
  onInputChange,
  onStart,
  onClose,
}) => {
  const { t } = useTranslation()

  if (!isOpen) return null

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && input.trim()) {
      onStart()
    }
  }

  return (
    <div className="fixed right-[12px] top-[68px] z-[100] w-[380px] pointer-events-none">
      <div className="bg-white/95 backdrop-blur-xl rounded-2xl shadow-2xl border border-gray-200 overflow-hidden pointer-events-auto animate-in slide-in-from-top-4 duration-300">
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between bg-white/50">
          <div className="flex items-center gap-2">
            <div className="p-1 rounded-md bg-blue-600 text-white">
              <Activity size={14} />
            </div>
            <h3 className="text-[11px] font-bold text-gray-900 uppercase tracking-wider">
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
        <div className="p-4 space-y-4">
          {/* Info Banner */}
          <div className="p-3 bg-blue-50/50 rounded-xl border border-blue-100 flex items-start gap-3">
            <Sparkles className="text-blue-500 shrink-0 mt-0.5" size={16} />
            <p className="text-[10px] text-blue-700 leading-relaxed font-medium">
              {t('workspace.enterPrompt')}
            </p>
          </div>

          {/* Input and Run Button */}
          <div className="flex gap-2">
            <Input
              placeholder={t('workspace.simulateUserInput')}
              className="h-9 text-[11px] bg-white border-gray-200 focus-visible:ring-blue-100"
              value={input}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              autoFocus
            />
            <Button
              size="sm"
              className="bg-blue-600 hover:bg-blue-700 h-9 px-4 gap-2 text-[11px] font-bold"
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

