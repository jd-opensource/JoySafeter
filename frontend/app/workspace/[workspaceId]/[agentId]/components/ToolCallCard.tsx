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

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import type { ExecutionStep, ToolExecutionData } from '@/types'

interface ToolCallCardProps {
  step: ExecutionStep
  defaultCollapsed?: boolean
  showHeader?: boolean
}

/**
 * Format JSON for better display of string values containing newlines
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
        return <Loader2 size={12} className="animate-spin text-[var(--brand-secondary)]" />
      case 'success':
        return <CheckCircle2 size={12} className="text-[var(--status-success)]" />
      case 'error':
        return <AlertCircle size={12} className="text-[var(--status-error)]" />
      default:
        return <Wrench size={12} className="text-[var(--text-muted)]" />
    }
  }

  // Get status color
  const getStatusColor = () => {
    switch (step.status) {
      case 'running':
        return 'border-[color-mix(in_srgb,var(--brand-secondary)_20%,transparent)] bg-[color-mix(in_srgb,var(--brand-secondary)_5%,transparent)]'
      case 'success':
        return 'border-[var(--status-success-border)] bg-[var(--status-success-bg)]'
      case 'error':
        return 'border-[var(--status-error-border)] bg-[var(--status-error-bg)]'
      default:
        return 'border-[var(--border)] bg-[var(--surface-2)]'
    }
  }

  return (
    <div className={cn('rounded-lg border transition-all duration-200', getStatusColor())}>
      {showHeader && (
        <div
          className="flex cursor-pointer items-center justify-between px-3 py-2 transition-colors hover:bg-[var(--surface-elevated)]"
          onClick={() => setIsCollapsed(!isCollapsed)}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {isCollapsed ? (
              <ChevronRight size={14} className="shrink-0 text-[var(--text-muted)]" />
            ) : (
              <ChevronDown size={14} className="shrink-0 text-[var(--text-muted)]" />
            )}
            <div className="flex min-w-0 flex-1 items-center gap-1.5">
              {getStatusIcon()}
              <span className="truncate text-sm font-semibold text-[var(--text-secondary)]">{step.title}</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {duration !== undefined && (
              <div className="flex items-center gap-1 text-xs text-[var(--text-tertiary)]">
                <Clock size={10} />
                <span className="font-mono">{duration}ms</span>
              </div>
            )}
            <div
              className={cn(
                'rounded px-1.5 py-0.5 text-xs font-medium',
                step.status === 'running' && 'bg-[color-mix(in_srgb,var(--brand-secondary)_10%,transparent)] text-[var(--brand-secondary)]',
                step.status === 'success' && 'bg-[var(--status-success-bg)] text-[var(--status-success)]',
                step.status === 'error' && 'bg-[var(--status-error-bg)] text-[var(--status-error)]',
                step.status === 'pending' && 'bg-[var(--surface-3)] text-[var(--text-secondary)]',
              )}
            >
              {step.status}
            </div>
          </div>
        </div>
      )}

      {!isCollapsed && (
        <div className="space-y-3 border-t border-[var(--border)] bg-[var(--surface-elevated)] p-3">
          {/* Input Section */}
          {input !== undefined && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-widest text-[var(--status-warning)]">
                  {t('workspace.input', { defaultValue: 'Input' })}
                </span>
                <div className="h-[1px] flex-1 bg-[var(--status-warning-border)]" />
              </div>
              <div className="overflow-hidden rounded-md border border-[var(--status-warning-border)]">
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
                    background: 'var(--status-warning-bg)',
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
                  <span className="text-xs font-bold uppercase tracking-widest text-[var(--status-success)]">
                    {t('workspace.output', { defaultValue: 'Output' })}
                  </span>
                  <div className="h-[1px] flex-1 bg-[var(--status-success-border)]" />
                </div>
                {shouldAutoCollapse && (
                  <button
                    onClick={() => setOutputCollapsed(!outputCollapsed)}
                    className="rounded px-2 py-0.5 text-xs font-medium text-[var(--status-success)] transition-colors hover:bg-[var(--status-success-bg)] hover:text-[var(--status-success-hover)]"
                    aria-label={outputCollapsed ? 'Expand output' : 'Collapse output'}
                  >
                    {outputCollapsed
                      ? t('tool.expand', { defaultValue: 'Expand' })
                      : t('tool.collapse', { defaultValue: 'Collapse' })}
                  </button>
                )}
              </div>
              {outputCollapsed ? (
                <div className="rounded-md border border-[var(--status-success-border)] bg-[var(--status-success-bg)] p-2">
                  <p className="line-clamp-3 font-mono text-xs text-[var(--status-success-strong)]">
                    {outputString.slice(0, 200)}...
                  </p>
                  <button
                    onClick={() => setOutputCollapsed(false)}
                    className="mt-1 text-xs font-medium text-[var(--status-success)] hover:text-[var(--status-success-hover)]"
                    aria-label="Expand full output"
                  >
                    {t('tool.clickToExpand', { defaultValue: 'Click to expand full output' })}
                  </button>
                </div>
              ) : (
                <div className="overflow-hidden rounded-md border border-[var(--status-success-border)]">
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
                      background: 'var(--status-success-bg)',
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
            <div className="flex items-center gap-2 py-2 text-[var(--text-muted)]">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--brand-secondary)]" />
              <span className="font-mono text-xs">
                {t('workspace.waitingForResponse', { defaultValue: 'Waiting for response...' })}
              </span>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
