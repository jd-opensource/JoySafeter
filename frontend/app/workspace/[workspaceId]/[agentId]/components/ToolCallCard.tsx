'use client'

import { ChevronDown, ChevronRight, Clock, Loader2, CheckCircle2, AlertCircle, Wrench } from 'lucide-react'
import React, { useState, useMemo } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import type { ExecutionStep, ToolExecutionData } from '@/types'

interface ToolCallCardProps {
  step: ExecutionStep
  defaultCollapsed?: boolean
  showHeader?: boolean
}

/**
 * 格式化JSON以便更好地显示包含换行符的字符串值
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

export const ToolCallCard: React.FC<ToolCallCardProps> = ({
  step,
  defaultCollapsed = true,
  showHeader = true,
}) => {
  const { t } = useTranslation()
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed)

  const toolData = step.data as ToolExecutionData | undefined
  const input = toolData?.request || toolData
  const output = toolData?.response

  // Calculate duration
  const duration = useMemo(() => {
    if (step.endTime && step.startTime) {
      return step.endTime - step.startTime
    }
    return step.duration
  }, [step.endTime, step.startTime, step.duration])

  // Check if output should be auto-collapsed (exceeds threshold)
  const outputString = output ? JSON.stringify(output) : ''
  const shouldAutoCollapse = outputString.length > 1000

  const [outputCollapsed, setOutputCollapsed] = useState(shouldAutoCollapse)

  // Get status icon
  const getStatusIcon = () => {
    switch (step.status) {
      case 'running':
        return <Loader2 size={12} className="text-cyan-500 animate-spin" />
      case 'success':
        return <CheckCircle2 size={12} className="text-emerald-500" />
      case 'error':
        return <AlertCircle size={12} className="text-red-500" />
      default:
        return <Wrench size={12} className="text-gray-400" />
    }
  }

  // Get status color
  const getStatusColor = () => {
    switch (step.status) {
      case 'running':
        return 'border-cyan-200 bg-cyan-50'
      case 'success':
        return 'border-emerald-200 bg-emerald-50'
      case 'error':
        return 'border-red-200 bg-red-50'
      default:
        return 'border-gray-200 bg-gray-50'
    }
  }

  return (
    <div className={cn(
      'border rounded-lg transition-all duration-200',
      getStatusColor()
    )}>
      {showHeader && (
        <div
          className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-white/50 transition-colors"
          onClick={() => setIsCollapsed(!isCollapsed)}
        >
          <div className="flex items-center gap-2 min-w-0 flex-1">
            {isCollapsed ? (
              <ChevronRight size={14} className="text-gray-400 shrink-0" />
            ) : (
              <ChevronDown size={14} className="text-gray-400 shrink-0" />
            )}
            <div className="flex items-center gap-1.5 min-w-0 flex-1">
              {getStatusIcon()}
              <span className="text-[11px] font-semibold text-gray-700 truncate">
                {step.title}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {duration !== undefined && (
              <div className="flex items-center gap-1 text-[9px] text-gray-500">
                <Clock size={10} />
                <span className="font-mono">{duration}ms</span>
              </div>
            )}
            <div className={cn(
              'px-1.5 py-0.5 rounded text-[9px] font-medium',
              step.status === 'running' && 'text-cyan-700 bg-cyan-100',
              step.status === 'success' && 'text-emerald-700 bg-emerald-100',
              step.status === 'error' && 'text-red-700 bg-red-100',
              step.status === 'pending' && 'text-gray-700 bg-gray-100'
            )}>
              {step.status}
            </div>
          </div>
        </div>
      )}

      {!isCollapsed && (
        <div className="p-3 space-y-3 border-t border-gray-200 bg-white">
          {/* Input Section */}
          {input !== undefined && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-bold text-amber-600 uppercase tracking-widest">
                  {t('workspace.input', { defaultValue: 'Input' })}
                </span>
                <div className="flex-1 h-[1px] bg-amber-100" />
              </div>
              <div className="rounded-md overflow-hidden border border-amber-200">
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
                    padding: '0.75rem',
                    background: '#fffbeb',
                    fontSize: '11px',
                    lineHeight: '1.5',
                    fontFamily: 'JetBrains Mono, monospace',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    overflowWrap: 'break-word',
                    maxWidth: '100%',
                  }}
                  wrapLongLines={true}
                >
                  {formatJsonWithNewlines(input)}
                </SyntaxHighlighter>
              </div>
            </div>
          )}

          {/* Output Section */}
          {output !== undefined ? (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 flex-1">
                  <span className="text-[10px] font-bold text-emerald-600 uppercase tracking-widest">
                    {t('workspace.output', { defaultValue: 'Output' })}
                  </span>
                  <div className="flex-1 h-[1px] bg-emerald-100" />
                </div>
                {shouldAutoCollapse && (
                  <button
                    onClick={() => setOutputCollapsed(!outputCollapsed)}
                    className="text-[9px] text-emerald-600 hover:text-emerald-700 font-medium px-2 py-0.5 rounded hover:bg-emerald-50 transition-colors"
                  >
                    {outputCollapsed ? t('tool.expand', { defaultValue: '展开' }) : t('tool.collapse', { defaultValue: '折叠' })}
                  </button>
                )}
              </div>
              {outputCollapsed ? (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-2">
                  <p className="text-[10px] text-emerald-700 font-mono line-clamp-3">
                    {outputString.slice(0, 200)}...
                  </p>
                  <button
                    onClick={() => setOutputCollapsed(false)}
                    className="text-[9px] text-emerald-600 hover:text-emerald-700 font-medium mt-1"
                  >
                    {t('tool.clickToExpand', { defaultValue: '点击展开查看完整输出' })}
                  </button>
                </div>
              ) : (
                <div className="rounded-md overflow-hidden border border-emerald-200">
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
                      padding: '0.75rem',
                      background: '#ecfdf5',
                      fontSize: '11px',
                      lineHeight: '1.5',
                      fontFamily: 'JetBrains Mono, monospace',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      overflowWrap: 'break-word',
                      maxWidth: '100%',
                    }}
                    wrapLongLines={true}
                  >
                    {formatJsonWithNewlines(output)}
                  </SyntaxHighlighter>
                </div>
              )}
            </div>
          ) : step.status === 'running' ? (
            <div className="flex items-center gap-2 text-gray-400 py-2">
              <div className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
              <span className="text-[10px] font-mono">
                {t('workspace.waitingForResponse', { defaultValue: 'Waiting for response...' })}
              </span>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
