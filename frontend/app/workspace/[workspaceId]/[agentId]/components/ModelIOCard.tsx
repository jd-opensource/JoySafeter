'use client'

import { ChevronDown, ChevronRight, Brain, MessageSquare, ArrowRight } from 'lucide-react'
import React, { useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/utils'
import type { ExecutionStep } from '@/types'

interface ModelIOCardProps {
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

/** JSON Data Section Component */
function DataSection({
  title,
  data,
  icon,
  iconColor,
  bgColor,
  defaultCollapsed = false,
}: {
  title: string
  data: any
  icon: React.ReactNode
  iconColor: string
  bgColor: string
  defaultCollapsed?: boolean
}) {
  const dataString = JSON.stringify(data)
  const shouldAutoCollapse = dataString.length > 2000
  const [collapsed, setCollapsed] = useState(defaultCollapsed || shouldAutoCollapse)

  return (
    <div className={cn('overflow-hidden rounded border', bgColor)}>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex w-full items-center justify-between p-2 transition-colors hover:bg-[var(--surface-3)]"
      >
        <div className="flex items-center gap-2">
          <span className={iconColor}>{icon}</span>
          <span className="text-[10px] font-semibold uppercase text-[var(--text-secondary)]">{title}</span>
        </div>
        {collapsed ? (
          <ChevronRight size={12} className="text-[var(--text-muted)]" />
        ) : (
          <ChevronDown size={12} className="text-[var(--text-muted)]" />
        )}
      </button>

      {!collapsed && (
        <div className="border-t border-[var(--border)] bg-[var(--surface-elevated)]">
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
              background: 'transparent',
              fontSize: '10px',
              lineHeight: '1.5',
              fontFamily: 'JetBrains Mono, monospace',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              overflowWrap: 'break-word',
              maxWidth: '100%',
            }}
            wrapLongLines={true}
          >
            {formatJsonWithNewlines(data)}
          </SyntaxHighlighter>
        </div>
      )}
    </div>
  )
}

export function ModelIOCard({
  step,
  defaultCollapsed = false,
  showHeader = true,
}: ModelIOCardProps) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed)

  const modelData = step.data as any
  const modelName = modelData?.model_name || 'unknown'
  const modelProvider = modelData?.model_provider || 'unknown'
  const messages = modelData?.messages
  const output = modelData?.output
  const usageMetadata = modelData?.usage_metadata

  const hasInput = messages && messages.length > 0
  const hasOutput = output !== undefined
  const isRunning = step.status === 'running'

  if (!showHeader) {
    // Full screen view in ExecutionPanel
    return (
      <div className="custom-scrollbar h-full overflow-auto bg-[var(--surface-elevated)] p-4">
        <div className="space-y-4">
          {/* Model Info Header */}
          <div className="flex items-center gap-2 border-b border-[var(--border)] pb-2">
            <Brain size={14} className="text-purple-600" />
            <span className="text-xs font-semibold text-[var(--text-secondary)]">Model I/O</span>
            <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
              ({modelProvider}/{modelName})
            </span>
            {isRunning && (
              <span className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                Awaiting output...
              </span>
            )}
          </div>

          {/* Input Section */}
          {hasInput && (
            <DataSection
              title="Input Messages"
              data={{ messages }}
              icon={<MessageSquare size={12} />}
              iconColor="text-blue-600"
              bgColor="border-blue-200"
            />
          )}

          {/* Output Section */}
          {hasOutput && (
            <DataSection
              title="Output"
              data={{ output, usage_metadata: usageMetadata }}
              icon={<Brain size={12} />}
              iconColor="text-purple-600"
              bgColor="border-purple-200"
            />
          )}

          {/* No output yet */}
          {!hasOutput && hasInput && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
              <div className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
              <span className="text-xs text-amber-700">Awaiting model response...</span>
            </div>
          )}
        </div>
      </div>
    )
  }

  // Collapsible card view
  return (
    <div
      className={cn(
        'rounded-lg border transition-all',
        hasOutput ? 'border-green-200 bg-green-50/50' : 'border-amber-200 bg-amber-50/50',
      )}
    >
      {/* Header */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="flex w-full items-center justify-between p-3 transition-colors hover:bg-opacity-80"
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {isCollapsed ? (
            <ChevronRight size={14} className="shrink-0 text-[var(--text-tertiary)]" />
          ) : (
            <ChevronDown size={14} className="shrink-0 text-[var(--text-tertiary)]" />
          )}
          <Brain size={14} className="shrink-0 text-purple-600" />
          <span className="truncate text-xs font-semibold text-[var(--text-secondary)]">Model I/O</span>
          <span className="truncate font-mono text-[10px] text-[var(--text-tertiary)]">
            {modelProvider}/{modelName}
          </span>

          {/* Status indicator */}
          <div className="ml-auto flex items-center gap-1">
            {hasInput && (
              <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[9px] font-medium text-blue-700">
                IN
              </span>
            )}
            {hasInput && hasOutput && <ArrowRight size={10} className="text-[var(--text-muted)]" />}
            {hasOutput ? (
              <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[9px] font-medium text-purple-700">
                OUT
              </span>
            ) : (
              hasInput && (
                <span className="animate-pulse rounded bg-amber-100 px-1.5 py-0.5 text-[9px] font-medium text-amber-700">
                  ...
                </span>
              )
            )}
          </div>
        </div>
      </button>

      {/* Content */}
      {!isCollapsed && (
        <div className="space-y-2 border-t border-[var(--border)] bg-[var(--surface-elevated)] p-3">
          {/* Input Section */}
          {hasInput && (
            <DataSection
              title="Input"
              data={{ messages }}
              icon={<MessageSquare size={12} />}
              iconColor="text-blue-600"
              bgColor="border-blue-200"
              defaultCollapsed={hasOutput} // Collapse input if output exists
            />
          )}

          {/* Output Section */}
          {hasOutput && (
            <DataSection
              title="Output"
              data={{ output, usage_metadata: usageMetadata }}
              icon={<Brain size={12} />}
              iconColor="text-purple-600"
              bgColor="border-purple-200"
            />
          )}

          {/* Waiting indicator */}
          {!hasOutput && hasInput && (
            <div className="flex items-center gap-2 rounded border border-amber-200 bg-amber-50 p-2">
              <div className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
              <span className="text-[10px] text-amber-700">Awaiting model response...</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
