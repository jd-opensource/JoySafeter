'use client'

import { BrainCircuit } from 'lucide-react'
import React from 'react'

import { cn } from '@/lib/core/utils/cn'
import type { ExecutionStep } from '@/types'

interface ThoughtContentProps {
  step: ExecutionStep
  showHeader?: boolean
}

export const ThoughtContent: React.FC<ThoughtContentProps> = ({
  step,
  showHeader = true,
}) => {
  const isStreaming = step.status === 'running'
  const content = step.content || ''

  return (
    <div className="space-y-2">
      {showHeader && (
        <div className="flex items-center gap-2">
          <BrainCircuit size={14} className="text-purple-500" />
          <span className="text-[11px] font-semibold text-purple-600">
            {step.title}
          </span>
          {isStreaming && (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse" />
              <span className="text-[9px] text-purple-500 font-medium">
                Thinking...
              </span>
            </div>
          )}
        </div>
      )}

      <div className="prose prose-sm max-w-none">
        <div className={cn(
          'text-xs leading-7 text-gray-700 font-mono whitespace-pre-wrap',
          'bg-purple-50/50 border border-purple-100 rounded-lg p-3'
        )}>
          {content || (
            <span className="text-gray-400 italic">Thinking...</span>
          )}
          {isStreaming && (
            <span className="inline-block w-2 h-4 bg-purple-500 animate-pulse ml-1 align-middle" />
          )}
        </div>
      </div>
    </div>
  )
}
