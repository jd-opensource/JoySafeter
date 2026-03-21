'use client'

import { X, Loader2, CheckCircle2, Sparkles, Zap, ChevronRight, Activity } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useBuilderStore } from '../stores/builderStore'

interface ExecutionModalProps {
  onClose: () => void
}

export function ExecutionModal({ onClose }: ExecutionModalProps) {
  const { t } = useTranslation()
  const {
    startExecution,
    isExecuting,
    executionLogs,
    stopExecution,
    activeExecutionNodeId,
    nodes,
  } = useBuilderStore()
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
    <div className="pointer-events-none absolute bottom-4 left-4 z-[100] flex w-[380px] flex-col">
      <div className="pointer-events-auto flex max-h-[500px] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white/90 shadow-2xl backdrop-blur-xl duration-300 animate-in slide-in-from-left-4">
        {/* Compact Header */}
        <div className="flex items-center justify-between border-b border-gray-100 bg-white/50 px-4 py-3">
          <div className="flex items-center gap-2">
            <div
              className={cn(
                'rounded-md p-1 text-white transition-colors duration-500',
                isExecuting ? 'animate-pulse bg-blue-600' : 'bg-gray-400',
              )}
            >
              <Activity size={14} />
            </div>
            <div>
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-gray-900">
                {isExecuting ? t('workspace.liveExecution') : t('workspace.readyToStart')}
              </h3>
              {isExecuting && activeNode && (
                <p className="flex items-center gap-1 font-mono text-[9px] text-blue-600">
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
            className="h-6 w-6 rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-900"
          >
            <X size={16} />
          </Button>
        </div>

        {/* Content Area */}
        <div className="flex flex-1 flex-col space-y-4 overflow-hidden p-4">
          {!isExecuting && executionLogs.length === 0 ? (
            <div className="space-y-4">
              <div className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/50 p-3">
                <Sparkles className="mt-0.5 shrink-0 text-blue-500" size={16} />
                <p className="text-[10px] font-medium leading-relaxed text-blue-700">
                  {t('workspace.enterPrompt')}
                </p>
              </div>
              <div className="flex gap-2">
                <Input
                  placeholder={t('workspace.simulateUserInput')}
                  className="h-9 border-gray-200 bg-white text-[11px] focus-visible:ring-blue-100"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleStart()}
                  autoFocus
                />
                <Button
                  size="sm"
                  className="h-9 gap-2 bg-blue-600 px-4 text-[11px] font-bold hover:bg-blue-700"
                  onClick={handleStart}
                  disabled={!input.trim()}
                >
                  <Zap size={12} className="fill-current" />
                  {t('workspace.run')}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 flex-col overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-inner">
              {/* Log Stream */}
              <div className="custom-scrollbar flex-1 space-y-2 overflow-y-auto scroll-smooth p-3 font-mono text-[9px]">
                {executionLogs.map((log, i) => (
                  <div key={i} className="flex gap-2 border-b border-white/5 pb-1 last:border-0">
                    <span className="shrink-0 text-gray-600">
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
                        'w-16 shrink-0 truncate font-bold uppercase',
                        log.status === 'success'
                          ? 'text-green-500'
                          : log.status === 'error'
                            ? 'text-red-500'
                            : 'text-blue-400',
                      )}
                    >
                      {log.nodeLabel}
                    </span>
                    <span className="italic text-gray-300">{log.message}</span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>

              {/* Status Bottom Bar */}
              <div className="flex items-center justify-between border-t border-white/5 bg-black/40 px-3 py-2">
                <div className="flex items-center gap-2">
                  {isExecuting ? (
                    <div className="flex items-center gap-1.5">
                      <Loader2 size={10} className="animate-spin text-blue-400" />
                      <span className="text-[9px] font-bold tracking-tighter text-blue-400">
                        {t('workspace.agentActive')}
                      </span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      <CheckCircle2 size={10} className="text-green-500" />
                      <span className="text-[9px] font-bold tracking-tighter text-green-500">
                        {t('workspace.flowFinished')}
                      </span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {isExecuting && (
                    <button
                      onClick={stopExecution}
                      className="text-[9px] font-bold text-red-400 underline underline-offset-2 hover:text-red-300"
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
