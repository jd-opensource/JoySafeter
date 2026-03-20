'use client'

import {
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Wrench,
} from 'lucide-react'
import { useState, useMemo } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/utils'
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
    },
  )
}

export function ToolCallCard({
  step,
  defaultCollapsed = true,
  showHeader = true,
}: ToolCallCardProps) {
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
        return <Loader2 size={12} className="animate-spin text-cyan-500" />
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
    <div className={cn('rounded-lg border transition-all duration-200', getStatusColor())}>
      {showHeader && (
        <div
          className="flex cursor-pointer items-center justify-between px-3 py-2 transition-colors hover:bg-white/50"
          onClick={() => setIsCollapsed(!isCollapsed)}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {isCollapsed ? (
              <ChevronRight size={14} className="shrink-0 text-gray-400" />
            ) : (
              <ChevronDown size={14} className="shrink-0 text-gray-400" />
            )}
            <div className="flex min-w-0 flex-1 items-center gap-1.5">
              {getStatusIcon()}
              <span className="truncate text-[11px] font-semibold text-gray-700">{step.title}</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {duration !== undefined && (
              <div className="flex items-center gap-1 text-[9px] text-gray-500">
                <Clock size={10} />
                <span className="font-mono">{duration}ms</span>
              </div>
            )}
            <div
              className={cn(
                'rounded px-1.5 py-0.5 text-[9px] font-medium',
                step.status === 'running' && 'bg-cyan-100 text-cyan-700',
                step.status === 'success' && 'bg-emerald-100 text-emerald-700',
                step.status === 'error' && 'bg-red-100 text-red-700',
                step.status === 'pending' && 'bg-gray-100 text-gray-700',
              )}
            >
              {step.status}
            </div>
          </div>
        </div>
      )}

      {!isCollapsed && (
        <div className="space-y-3 border-t border-gray-200 bg-white p-3">
          {/* Input Section */}
          {input !== undefined && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-amber-600">
                  {t('workspace.input', { defaultValue: 'Input' })}
                </span>
                <div className="h-[1px] flex-1 bg-amber-100" />
              </div>
              <div className="overflow-hidden rounded-md border border-amber-200">
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
                <div className="flex flex-1 items-center gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-emerald-600">
                    {t('workspace.output', { defaultValue: 'Output' })}
                  </span>
                  <div className="h-[1px] flex-1 bg-emerald-100" />
                </div>
                {shouldAutoCollapse && (
                  <button
                    onClick={() => setOutputCollapsed(!outputCollapsed)}
                    className="rounded px-2 py-0.5 text-[9px] font-medium text-emerald-600 transition-colors hover:bg-emerald-50 hover:text-emerald-700"
                  >
                    {outputCollapsed
                      ? t('tool.expand', { defaultValue: '展开' })
                      : t('tool.collapse', { defaultValue: '折叠' })}
                  </button>
                )}
              </div>
              {outputCollapsed ? (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-2">
                  <p className="line-clamp-3 font-mono text-[10px] text-emerald-700">
                    {outputString.slice(0, 200)}...
                  </p>
                  <button
                    onClick={() => setOutputCollapsed(false)}
                    className="mt-1 text-[9px] font-medium text-emerald-600 hover:text-emerald-700"
                  >
                    {t('tool.clickToExpand', { defaultValue: '点击展开查看完整输出' })}
                  </button>
                </div>
              ) : (
                <div className="overflow-hidden rounded-md border border-emerald-200">
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
            <div className="flex items-center gap-2 py-2 text-gray-400">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-500" />
              <span className="font-mono text-[10px]">
                {t('workspace.waitingForResponse', { defaultValue: 'Waiting for response...' })}
              </span>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
