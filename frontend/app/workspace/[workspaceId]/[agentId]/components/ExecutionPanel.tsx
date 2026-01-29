'use client'

import {
  Trash2,
  ChevronDown,
  Activity,
  Braces,
  AlignLeft,
} from 'lucide-react'
import React, { useState, useEffect, useDeferredValue } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { useTranslation } from '@/lib/i18n'

import { useExecutionStore } from '../stores/executionStore'

import { ExecutionTimeline } from './ExecutionTimeline'
import { InterruptPanel } from './InterruptPanel'
import { ModelIOCard } from './ModelIOCard'
import { ThoughtContent } from './ThoughtContent'
import { ToolCallCard } from './ToolCallCard'


/**
 * Format JSON to better display string values containing newlines
 */
function formatJsonWithNewlines(data: any): string {
  const jsonString = JSON.stringify(data, null, 2)
  
  return jsonString.replace(
    /("(?:[^"\\]|\\.)*")\s*:\s*"((?:[^"\\]|\\.)*)"/g,
    (match, key, escapedValue) => {
      if (escapedValue.includes('\\n')) {
        try {
          const actualValue = JSON.parse(`"${escapedValue}"`)
          
          if (typeof actualValue === 'string' && actualValue.includes('\n')) {
            const indentMatch = jsonString.substring(0, jsonString.indexOf(match)).match(/(\n\s*)$/)
            const baseIndent = indentMatch ? indentMatch[1].replace('\n', '') : ''
            const valueIndent = baseIndent + '    '
            
            const lines = actualValue.split('\n')
            const formattedLines = lines.map((line, index) => {
              const escapedLine = line.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
              return index === 0 ? escapedLine : `\n${valueIndent}${escapedLine}`
            })
            
            return `${key}: "${formattedLines.join('')}"`
          }
        } catch {
          // If parsing fails, return as is
        }
      }
      return match
    }
  )
}

export const ExecutionPanel: React.FC = () => {
  const { t } = useTranslation()
  const { 
    steps: executionSteps, 
    isExecuting, 
    togglePanel: toggleExecutionPanel, 
    clear: clearExecution,
    pendingInterrupts,
    getInterrupt,
  } = useExecutionStore()

  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)

  // Use useDeferredValue to delay steps updates, avoiding flushSync conflicts caused by high-frequency updates
  // React will update deferred values during idle time, not blocking user interaction
  const deferredSteps = useDeferredValue(executionSteps)
  
  // Get the first interrupt (if any)
  const firstInterrupt = pendingInterrupts.size > 0 
    ? Array.from(pendingInterrupts.values())[0]
    : null

  // Auto-select logic for detail panel
  useEffect(() => {
    if (isExecuting && executionSteps.length > 0) {
      const lastInterestingStep = [...executionSteps]
        .reverse()
        .find((s) => 
          s.stepType === 'tool_execution' || 
          s.stepType === 'model_io' ||
          (s.stepType === 'agent_thought' && s.content)
        )
      if (lastInterestingStep) {
        setSelectedStepId(lastInterestingStep.id)
      }
    }
  }, [executionSteps.length, isExecuting])

  const activeStep = executionSteps.find((s) => s.id === selectedStepId)

  return (
    <div className="h-[280px] w-[calc(100%-320px)] bg-white border-t border-gray-200 shadow-[0_-4px_20px_rgba(0,0,0,0.05)] flex shrink-0 z-40 animate-in slide-in-from-bottom-10 duration-300 font-sans">
      {/* Left Panel: Trace View (Timeline) */}
      <div className="w-[450px] flex flex-col border-r border-gray-200 bg-white shrink-0">
        {/* Panel Header */}
        <div className="h-8 border-b border-gray-200 flex items-center justify-between px-4 bg-gray-50/80 select-none shrink-0 backdrop-blur-sm">
          <div className="flex items-center gap-2.5">
            <Activity size={14} className="text-blue-600" />
            <span className="text-[10px] font-bold text-gray-700 uppercase tracking-widest">
              {t('workspace.executionStream', { defaultValue: 'Execution Stream' })}
            </span>
            <div className="w-[1px] h-3 bg-gray-300 mx-1" />
            <span className="text-[9px] text-gray-500 font-mono">{executionSteps.length} {t('workspace.ops', { defaultValue: 'OPS' })}</span>
            {isExecuting && (
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse ml-2" />
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => clearExecution()}
              className="p-1.5 hover:bg-gray-200 rounded-md text-gray-400 hover:text-gray-700 transition-colors"
              title={t('workspace.clearTrace', { defaultValue: 'Clear Trace' })}
            >
              <Trash2 size={14} />
            </button>
            <button
              onClick={() => toggleExecutionPanel(false)}
              className="flex items-center gap-1 px-2 py-1 hover:bg-red-50 rounded-md text-gray-400 hover:text-red-600 transition-colors border border-transparent hover:border-red-200"
              title={t('workspace.closePanel', { defaultValue: 'Close Panel' })}
            >
              <ChevronDown size={14} />
              <span className="text-[9px] font-medium">{t('workspace.close', { defaultValue: 'Close' })}</span>
            </button>
          </div>
        </div>

        {/* Timeline List - Use deferredSteps to avoid flushSync conflicts */}
        <ExecutionTimeline
          steps={deferredSteps}
          selectedStepId={selectedStepId}
          onStepSelect={setSelectedStepId}
          isExecuting={isExecuting}
        />
      </div>

      {/* Right Panel: Details (JSON/Logs) or Interrupt Panel */}
      <div className="flex-1 flex flex-col bg-gray-50 min-w-0">
        {firstInterrupt ? (
          <div className="flex-1 overflow-auto p-4">
            <InterruptPanel 
              interrupt={firstInterrupt}
              onClose={() => {
                // Interrupt will be removed by the panel itself
              }}
            />
          </div>
        ) : activeStep ? (
          <>
            <div className="h-8 border-b border-gray-200 flex items-center px-4 bg-white shrink-0 justify-between">
              <div className="flex items-center gap-2">
                <AlignLeft size={13} className="text-gray-500" />
                <span className="text-[10px] font-bold text-gray-800 uppercase tracking-widest truncate max-w-[300px]">
                  {activeStep.title} <span className="text-gray-400">:: {t('workspace.payload', { defaultValue: 'PAYLOAD' })}</span>
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[9px] text-gray-500 font-mono bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200">
                  {t('workspace.id', { defaultValue: 'ID' })}: {activeStep.id.split('_')[1] || activeStep.id.slice(0, 8)}
                </span>
              </div>
            </div>

            <div className="flex-1 overflow-hidden relative group">
              {/* Render Strategy: Use new components */}
              {activeStep.stepType === 'agent_thought' ? (
                <div className="absolute inset-0 overflow-auto custom-scrollbar p-6 bg-white">
                  <ThoughtContent step={activeStep} showHeader={false} />
                </div>
              ) : activeStep.stepType === 'tool_execution' && activeStep.data ? (
                <div className="absolute inset-0 overflow-auto custom-scrollbar bg-white p-4">
                  <ToolCallCard step={activeStep} defaultCollapsed={false} showHeader={false} />
                </div>
              ) : activeStep.stepType === 'model_io' && activeStep.data ? (
                <div className="absolute inset-0 overflow-auto custom-scrollbar bg-white">
                  <ModelIOCard step={activeStep} defaultCollapsed={false} showHeader={false} />
                </div>
              ) : (
                <div className="absolute inset-0 overflow-auto custom-scrollbar bg-white">
                  <SyntaxHighlighter
                    language="json"
                    style={oneLight}
                    PreTag="div"
                    codeTagProps={{
                      style: {
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        overflowWrap: 'break-word',
                      },
                    }}
                    customStyle={{
                      margin: 0,
                      padding: '1.5rem',
                      background: 'transparent',
                      fontSize: '11px',
                      lineHeight: '1.6',
                      fontFamily: 'JetBrains Mono, monospace',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      overflowWrap: 'break-word',
                      maxWidth: '100%',
                    }}
                    wrapLongLines={true}
                  >
                    {formatJsonWithNewlines(activeStep.data || activeStep)}
                  </SyntaxHighlighter>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-3">
            <Braces size={40} strokeWidth={0.5} className="text-gray-300" />
            <p className="text-xs font-mono">{t('workspace.selectStepToInspectPayload', { defaultValue: 'Select a step to inspect payload' })}</p>
          </div>
        )}
      </div>
    </div>
  )
}

