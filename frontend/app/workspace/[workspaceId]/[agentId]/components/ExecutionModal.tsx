'use client'

import { X, Loader2, CheckCircle2, Sparkles, Zap, ChevronRight, Activity } from 'lucide-react'
import React, { useState, useRef, useEffect } from 'react'


import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

import { useBuilderStore } from '../stores/builderStore'

interface ExecutionModalProps {
  onClose: () => void
}

export const ExecutionModal: React.FC<ExecutionModalProps> = ({ onClose }) => {
  const { t } = useTranslation()
  const { startExecution, isExecuting, executionLogs, stopExecution, activeExecutionNodeId, nodes } =
    useBuilderStore()
  const [input, setInput] = useState('')
  const logEndRef = useRef<HTMLDivElement>(null)

  const activeNode = nodes.find((n) => n.id === activeExecutionNodeId)

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [executionLogs])

  const handleStart = () => {
    if (!input.trim() || isExecuting) return
    startExecution(input)
  }

  return (
    <div className="absolute bottom-4 left-4 z-[100] w-[380px] flex flex-col pointer-events-none">
      <div className="bg-white/90 backdrop-blur-xl rounded-2xl shadow-2xl border border-gray-200 overflow-hidden flex flex-col max-h-[500px] pointer-events-auto animate-in slide-in-from-left-4 duration-300">
        {/* Compact Header */}
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between bg-white/50">
          <div className="flex items-center gap-2">
            <div
              className={cn(
                'p-1 rounded-md text-white transition-colors duration-500',
                isExecuting ? 'bg-blue-600 animate-pulse' : 'bg-gray-400'
              )}
            >
              <Activity size={14} />
            </div>
            <div>
              <h3 className="text-[11px] font-bold text-gray-900 uppercase tracking-wider">
                {isExecuting ? t('workspace.liveExecution') : t('workspace.readyToStart')}
              </h3>
              {isExecuting && activeNode && (
                <p className="text-[9px] text-blue-600 font-mono flex items-center gap-1">
                  <ChevronRight size={10} /> {t('workspace.processing')}:{' '}
                  {(activeNode.data as { label?: string })?.label}
                </p>
              )}
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-6 w-6 rounded-md text-gray-400 hover:text-gray-900 hover:bg-gray-100"
          >
            <X size={16} />
          </Button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-hidden flex flex-col p-4 space-y-4">
          {!isExecuting && executionLogs.length === 0 ? (
            <div className="space-y-4">
              <div className="p-3 bg-blue-50/50 rounded-xl border border-blue-100 flex items-start gap-3">
                <Sparkles className="text-blue-500 shrink-0 mt-0.5" size={16} />
                <p className="text-[10px] text-blue-700 leading-relaxed font-medium">
                  {t('workspace.enterPrompt')}
                </p>
              </div>
              <div className="flex gap-2">
                <Input
                  placeholder={t('workspace.simulateUserInput')}
                  className="h-9 text-[11px] bg-white border-gray-200 focus-visible:ring-blue-100"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleStart()}
                  autoFocus
                />
                <Button
                  size="sm"
                  className="bg-blue-600 hover:bg-blue-700 h-9 px-4 gap-2 text-[11px] font-bold"
                  onClick={handleStart}
                  disabled={!input.trim()}
                >
                  <Zap size={12} className="fill-current" />
                  {t('workspace.run')}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex-1 bg-gray-900 rounded-xl flex flex-col overflow-hidden shadow-inner border border-gray-800">
              {/* Log Stream */}
              <div className="flex-1 overflow-y-auto p-3 space-y-2 font-mono text-[9px] custom-scrollbar scroll-smooth">
                {executionLogs.map((log, i) => (
                  <div key={i} className="flex gap-2 border-b border-white/5 pb-1 last:border-0">
                    <span className="text-gray-600 shrink-0">
                      [
                      {new Date(log.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                      ]
                    </span>
                    <span
                      className={cn(
                        'font-bold shrink-0 uppercase w-16 truncate',
                        log.status === 'success'
                          ? 'text-green-500'
                          : log.status === 'error'
                            ? 'text-red-500'
                            : 'text-blue-400'
                      )}
                    >
                      {log.nodeLabel}
                    </span>
                    <span className="text-gray-300 italic">{log.message}</span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>

              {/* Status Bottom Bar */}
              <div className="px-3 py-2 bg-black/40 flex items-center justify-between border-t border-white/5">
                <div className="flex items-center gap-2">
                  {isExecuting ? (
                    <div className="flex items-center gap-1.5">
                      <Loader2 size={10} className="text-blue-400 animate-spin" />
                      <span className="text-[9px] font-bold text-blue-400 tracking-tighter">
                        {t('workspace.agentActive')}
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      <CheckCircle2 size={10} className="text-green-500" />
                      <span className="text-[9px] font-bold text-green-500 tracking-tighter">
                        {t('workspace.flowFinished')}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {isExecuting && (
                    <button
                      onClick={stopExecution}
                      className="text-[9px] font-bold text-red-400 hover:text-red-300 underline underline-offset-2"
                    >
                      {t('workspace.terminate')}
                    </button>
                  )}
                  {!isExecuting && (
                    <button
                      onClick={() => {
                        setInput('')
                        useBuilderStore.setState({ executionLogs: [] })
                      }}
                      className="text-[9px] font-bold text-gray-400 hover:text-white"
                    >
                      {t('workspace.clearLogs')}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
