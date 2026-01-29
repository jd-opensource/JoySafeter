'use client'

import { format } from 'date-fns'
import DOMPurify from 'dompurify'
import { X, CheckCircle2, AlertCircle, Loader2, Wrench, Copy, Check } from 'lucide-react'
import React, { useState, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import { useToolPanelStore } from '@/lib/stores/tool-panel-store'

import { ToolCall } from '../types'

import ToolNavigation from './ToolNavigation'

interface ToolExecutionPanelProps {
  isOpen: boolean
  onClose: () => void
  toolCall: ToolCall | null
  messages: Array<{ role: string; content: string; tool_calls?: ToolCall[] }>
  toolCalls?: ToolCall[]
  agentStatus?: 'idle' | 'running' | 'connecting' | 'error'
}

const ToolExecutionPanel: React.FC<ToolExecutionPanelProps> = ({
  isOpen,
  onClose,
  toolCall,
  messages,
  toolCalls = [],
  agentStatus = 'idle',
}) => {
  const { t } = useTranslation()
  const {
    selectedToolIndex,
    setSelectedToolIndex,
  } = useToolPanelStore()
  
  const [copiedInput, setCopiedInput] = useState(false)
  const [copiedOutput, setCopiedOutput] = useState(false)

  // Use provided toolCalls or extract from messages
  const allToolCalls = toolCalls.length > 0 ? toolCalls : (() => {
    const extracted: ToolCall[] = []
    messages.forEach((msg) => {
      if (msg.tool_calls) {
        extracted.push(...msg.tool_calls)
      }
    })
    return extracted
  })()

  // If a specific tool call is selected, show it; otherwise show the latest
  const displayToolCall = toolCall || allToolCalls[selectedToolIndex] || allToolCalls[allToolCalls.length - 1]

  // Get tool names for navigation
  const toolNames = useMemo(() => {
    return allToolCalls.map(tc =>
      tc.name.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
    )
  }, [allToolCalls])

  // Format tool name for display
  const formatToolName = (name: string): string => {
    return name.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
  }

  if (!isOpen) return null

  const getStatusIcon = (status?: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 size={16} className="text-green-500" />
      case 'failed':
        return <AlertCircle size={16} className="text-red-500" />
      case 'running':
        return <Loader2 size={16} className="text-blue-500 animate-spin" />
      default:
        return <Loader2 size={16} className="text-gray-400 animate-spin" />
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
      <div className="h-full bg-white flex flex-col">
        <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
          No tool execution data
        </div>
      </div>
    )
  }

  return (
    <div className="h-full bg-white flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50 flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Wrench size={18} className="text-gray-700 flex-shrink-0" />
          <span className="text-sm font-medium text-gray-900 truncate">
            {displayToolCall.name ? formatToolName(displayToolCall.name) : t('chat.initializingTools')}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {displayToolCall.status && (
            <div className={cn(
              "flex items-center gap-2 px-2 py-1 rounded-md border",
              getStatusColor(displayToolCall.status)
            )}>
              {getStatusIcon(displayToolCall.status)}
              <span className="text-xs font-medium">{getStatusText(displayToolCall.status)}</span>
            </div>
          )}
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-gray-200 transition-colors flex-shrink-0"
            aria-label="Close panel"
          >
            <X size={16} className="text-gray-500" />
          </button>
        </div>
      </div>

      {/* Content - Input and Output */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Input Section */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold text-amber-600 uppercase tracking-widest">{t('chat.input')}</span>
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
              className="text-gray-500 hover:text-gray-700 transition-colors flex items-center justify-center w-6 h-6 rounded hover:bg-gray-100"
              title={t('chat.copyToClipboard')}
            >
              {copiedInput ? (
                <Check size={14} className="text-green-600" />
              ) : (
                <Copy size={14} />
              )}
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
              <span className="text-[10px] font-bold text-blue-600 uppercase tracking-widest">{t('chat.output')}</span>
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
                className="text-gray-500 hover:text-gray-700 transition-colors flex items-center justify-center w-6 h-6 rounded hover:bg-gray-100"
                title={t('chat.copyToClipboard')}
              >
                {copiedOutput ? (
                  <Check size={14} className="text-green-600" />
                ) : (
                  <Copy size={14} />
                )}
              </button>
            </div>
            <div className="relative max-h-[500px] overflow-auto">
              {(() => {
                const formatted = formatToolResult(displayToolCall.result)
                // Check if result is JSON that can be parsed
                let parsedResult: any = null
                try {
                  parsedResult = typeof displayToolCall.result === 'string' ? JSON.parse(displayToolCall.result) : displayToolCall.result
                } catch {
                  // Not valid JSON, treat as string
                }

                // If it's a valid JSON object, use syntax highlighter
                if (parsedResult && typeof parsedResult === 'object' && !Array.isArray(parsedResult)) {
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
                    <div className="bg-gray-50 border border-gray-200 rounded-md p-3 prose prose-sm max-w-none">
                      <ReactMarkdown
                        components={{
                          h2: ({ children }) => (
                            <h2 className="text-sm font-bold mt-4 mb-2 first:mt-0 text-gray-900">{children}</h2>
                          ),
                          h3: ({ children }) => (
                            <h3 className="text-xs font-semibold mt-3 mb-1.5 text-gray-800">{children}</h3>
                          ),
                          p: ({ children }) => (
                            <p className="text-xs mb-2 leading-relaxed text-gray-700">{children}</p>
                          ),
                          ul: ({ children }) => (
                            <ul className="list-disc list-inside text-xs mb-2 space-y-1 text-gray-700">{children}</ul>
                          ),
                          li: ({ children }) => (
                            <li className="text-xs text-gray-700">{children}</li>
                          ),
                          code: ({ children }) => (
                            <code className="bg-gray-100 px-1 py-0.5 rounded text-xs font-mono text-gray-800">{children}</code>
                          ),
                        }}
                      >
                        {DOMPurify.sanitize(formatted, {
                          ALLOWED_TAGS: [
                            'p', 'br', 'strong', 'em', 'code', 'pre', 'blockquote',
                            'ul', 'ol', 'li', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                            'hr', 'div', 'span'
                          ],
                          ALLOWED_ATTR: ['href', 'class', 'id'],
                          ALLOW_DATA_ATTR: false,
                          ALLOW_UNKNOWN_PROTOCOLS: false,
                          ADD_ATTR: ['rel'],
                          FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'input', 'button'],
                          FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur'],
                        })}
                      </ReactMarkdown>
                    </div>
                  )
                }

                // Default: plain text with monospace font
                return (
                  <div className="bg-gray-50 border border-gray-200 rounded-md p-3">
                    <pre className="whitespace-pre-wrap break-words font-mono text-xs text-gray-800 leading-relaxed">
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
      <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50 flex-shrink-0">
        <button className="text-xs font-medium text-gray-600 hover:text-gray-900 transition-colors">
          {t('chat.tool')}
        </button>
        {displayToolCall.startTime && (
          <div className="text-xs text-gray-400 font-mono">
            {format(new Date(displayToolCall.startTime), 'yyyy/MM/dd HH:mm:ss')}
          </div>
        )}
      </div>
    </div>
  )
}

export default ToolExecutionPanel
