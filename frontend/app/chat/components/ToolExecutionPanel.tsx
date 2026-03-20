'use client'

import { format } from 'date-fns'
import DOMPurify from 'dompurify'
import { X, CheckCircle2, AlertCircle, Loader2, Wrench, Copy, Check } from 'lucide-react'
import { useState, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

import { ToolCall } from '../types'

interface ToolExecutionPanelProps {
  isOpen: boolean
  onClose: () => void
  toolCall: ToolCall | null
  messages: Array<{ role: string; content: string; tool_calls?: ToolCall[] }>
  toolCalls?: ToolCall[]
  agentStatus?: 'idle' | 'running' | 'connecting' | 'error'
}

/** Format tool_name → Title Case */
const formatToolName = (name: string): string =>
  name.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())

export default function ToolExecutionPanel({
  isOpen,
  onClose,
  toolCall,
  messages,
  toolCalls = [],
  agentStatus = 'idle',
}: ToolExecutionPanelProps) {
  const { t } = useTranslation()

  const [copiedInput, setCopiedInput] = useState(false)
  const [copiedOutput, setCopiedOutput] = useState(false)

  // Use provided toolCalls or extract from messages
  const allToolCalls = useMemo(() => {
    if (toolCalls.length > 0) return toolCalls
    const extracted: ToolCall[] = []
    messages.forEach((msg) => {
      if (msg.tool_calls) {
        extracted.push(...msg.tool_calls)
      }
    })
    return extracted
  }, [toolCalls, messages])

  // If a specific tool call is selected, show it; otherwise show the latest
  const displayToolCall = toolCall || allToolCalls[allToolCalls.length - 1]

  if (!isOpen) return null

  const getStatusIcon = (status?: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 size={16} className="text-green-500" />
      case 'failed':
        return <AlertCircle size={16} className="text-red-500" />
      case 'running':
        return <Loader2 size={16} className="animate-spin text-blue-500" />
      default:
        return <Loader2 size={16} className="animate-spin text-gray-400" />
    }
  }

  const getStatusText = (status?: string) => {
    switch (status) {
      case 'completed':
        return t('chat.toolExecutedSuccessfully')
      case 'failed':
        return t('chat.toolExecutionFailed')
      case 'running':
        return t('chat.toolExecuting')
      default:
        return t('chat.initializingTools')
    }
  }

  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'completed':
        return 'bg-green-50 border-green-200 text-green-800'
      case 'failed':
        return 'bg-red-50 border-red-200 text-red-800'
      case 'running':
        return 'bg-blue-50 border-blue-200 text-blue-800'
      default:
        return 'bg-gray-50 border-gray-200 text-gray-800'
    }
  }

  // Format tool result for display
  const formatToolResult = (result: any): string => {
    if (typeof result === 'string') {
      return result
    }
    if (result && typeof result === 'object') {
      if (result.guides || result.message || result.status) {
        return JSON.stringify(result, null, 2)
      }
      return JSON.stringify(result, null, 2)
    }
    return String(result)
  }

  if (!displayToolCall) {
    return (
      <div className="flex h-full flex-col bg-white">
        <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
          No tool execution data
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-200 bg-gray-50 px-4 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Wrench size={18} className="flex-shrink-0 text-gray-700" />
          <span className="truncate text-sm font-medium text-gray-900">
            {displayToolCall.name
              ? formatToolName(displayToolCall.name)
              : t('chat.initializingTools')}
          </span>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          {displayToolCall.status && (
            <div
              className={cn(
                'flex items-center gap-2 rounded-md border px-2 py-1',
                getStatusColor(displayToolCall.status),
              )}
            >
              {getStatusIcon(displayToolCall.status)}
              <span className="text-xs font-medium">{getStatusText(displayToolCall.status)}</span>
            </div>
          )}
          <button
            onClick={onClose}
            className="flex-shrink-0 rounded-lg p-1.5 transition-colors hover:bg-gray-200"
            aria-label="Close panel"
          >
            <X size={16} className="text-gray-500" />
          </button>
        </div>
      </div>

      {/* Content - Input and Output */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {/* Input Section */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-widest text-amber-600">
              {t('chat.input')}
            </span>
            <button
              onClick={async () => {
                try {
                  const text = JSON.stringify(displayToolCall.args, null, 2)
                  await navigator.clipboard.writeText(text)
                  setCopiedInput(true)
                  setTimeout(() => setCopiedInput(false), 2000)
                } catch (err) {
                  console.error('Failed to copy:', err)
                }
              }}
              className="flex h-6 w-6 items-center justify-center rounded text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
              title={t('chat.copyToClipboard')}
            >
              {copiedInput ? <Check size={14} className="text-green-600" /> : <Copy size={14} />}
            </button>
          </div>
          <div className="relative">
            <SyntaxHighlighter
              language="json"
              style={oneLight}
              customStyle={{
                margin: 0,
                padding: '0.75rem',
                background: '#f9fafb',
                borderRadius: '0.5rem',
                border: '1px solid #e5e7eb',
                fontSize: '11px',
                lineHeight: '1.5',
                fontFamily: 'JetBrains Mono, monospace',
              }}
              wrapLongLines={true}
            >
              {JSON.stringify(displayToolCall.args, null, 2)}
            </SyntaxHighlighter>
          </div>
        </div>

        {/* Output Section */}
        {displayToolCall.result && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase tracking-widest text-blue-600">
                {t('chat.output')}
              </span>
              <button
                onClick={async () => {
                  try {
                    const text = formatToolResult(displayToolCall.result)
                    // If it's a JSON object, stringify it properly
                    let textToCopy = text
                    if (typeof displayToolCall.result === 'object') {
                      textToCopy = JSON.stringify(displayToolCall.result, null, 2)
                    }
                    await navigator.clipboard.writeText(textToCopy)
                    setCopiedOutput(true)
                    setTimeout(() => setCopiedOutput(false), 2000)
                  } catch (err) {
                    console.error('Failed to copy:', err)
                  }
                }}
                className="flex h-6 w-6 items-center justify-center rounded text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
                title={t('chat.copyToClipboard')}
              >
                {copiedOutput ? <Check size={14} className="text-green-600" /> : <Copy size={14} />}
              </button>
            </div>
            <div className="relative max-h-[500px] overflow-auto">
              {(() => {
                const formatted = formatToolResult(displayToolCall.result)
                // Check if result is JSON that can be parsed
                let parsedResult: any = null
                try {
                  parsedResult =
                    typeof displayToolCall.result === 'string'
                      ? JSON.parse(displayToolCall.result)
                      : displayToolCall.result
                } catch {
                  // Not valid JSON, treat as string
                }

                // If it's a valid JSON object, use syntax highlighter
                if (
                  parsedResult &&
                  typeof parsedResult === 'object' &&
                  !Array.isArray(parsedResult)
                ) {
                  return (
                    <SyntaxHighlighter
                      language="json"
                      style={oneLight}
                      customStyle={{
                        margin: 0,
                        padding: '0.75rem',
                        background: '#f9fafb',
                        borderRadius: '0.5rem',
                        border: '1px solid #e5e7eb',
                        fontSize: '11px',
                        lineHeight: '1.5',
                        fontFamily: 'JetBrains Mono, monospace',
                      }}
                      wrapLongLines={true}
                    >
                      {JSON.stringify(parsedResult, null, 2)}
                    </SyntaxHighlighter>
                  )
                }

                // If it contains markdown headers, render as markdown
                if (formatted.includes('##') || formatted.includes('###')) {
                  return (
                    <div className="prose prose-sm max-w-none rounded-md border border-gray-200 bg-gray-50 p-3">
                      <ReactMarkdown
                        components={{
                          h2: ({ children }) => (
                            <h2 className="mb-2 mt-4 text-sm font-bold text-gray-900 first:mt-0">
                              {children}
                            </h2>
                          ),
                          h3: ({ children }) => (
                            <h3 className="mb-1.5 mt-3 text-xs font-semibold text-gray-800">
                              {children}
                            </h3>
                          ),
                          p: ({ children }) => (
                            <p className="mb-2 text-xs leading-relaxed text-gray-700">{children}</p>
                          ),
                          ul: ({ children }) => (
                            <ul className="mb-2 list-inside list-disc space-y-1 text-xs text-gray-700">
                              {children}
                            </ul>
                          ),
                          li: ({ children }) => (
                            <li className="text-xs text-gray-700">{children}</li>
                          ),
                          code: ({ children }) => (
                            <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-xs text-gray-800">
                              {children}
                            </code>
                          ),
                        }}
                      >
                        {DOMPurify.sanitize(formatted, {
                          ALLOWED_TAGS: [
                            'p',
                            'br',
                            'strong',
                            'em',
                            'code',
                            'pre',
                            'blockquote',
                            'ul',
                            'ol',
                            'li',
                            'a',
                            'h1',
                            'h2',
                            'h3',
                            'h4',
                            'h5',
                            'h6',
                            'hr',
                            'div',
                            'span',
                          ],
                          ALLOWED_ATTR: ['href', 'class', 'id'],
                          ALLOW_DATA_ATTR: false,
                          ALLOW_UNKNOWN_PROTOCOLS: false,
                          ADD_ATTR: ['rel'],
                          FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'input', 'button'],
                          FORBID_ATTR: [
                            'onerror',
                            'onload',
                            'onclick',
                            'onmouseover',
                            'onfocus',
                            'onblur',
                          ],
                        })}
                      </ReactMarkdown>
                    </div>
                  )
                }

                // Default: plain text with monospace font
                return (
                  <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
                    <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-gray-800">
                      {formatted}
                    </pre>
                  </div>
                )
              })()}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex flex-shrink-0 items-center justify-between border-t border-gray-200 bg-gray-50 px-4 py-3">
        <button className="text-xs font-medium text-gray-600 transition-colors hover:text-gray-900">
          {t('chat.tool')}
        </button>
        {displayToolCall.startTime && (
          <div className="font-mono text-xs text-gray-400">
            {format(new Date(displayToolCall.startTime), 'yyyy/MM/dd HH:mm:ss')}
          </div>
        )}
      </div>
    </div>
  )
}
