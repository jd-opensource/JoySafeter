'use client'

import { ChevronDown, ChevronRight, Brain, MessageSquare, ArrowRight } from 'lucide-react'
import React, { useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import type { ExecutionStep } from '@/types'

interface ModelIOCardProps {
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

/** JSON Data Section Component */
const DataSection: React.FC<{
  title: string
  data: any
  icon: React.ReactNode
  iconColor: string
  bgColor: string
  defaultCollapsed?: boolean
}> = ({ title, data, icon, iconColor, bgColor, defaultCollapsed = false }) => {
  const dataString = JSON.stringify(data)
  const shouldAutoCollapse = dataString.length > 2000
  const [collapsed, setCollapsed] = useState(defaultCollapsed || shouldAutoCollapse)

  return (
    <div className={cn("rounded border overflow-hidden", bgColor)}>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between p-2 hover:bg-gray-100/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className={iconColor}>{icon}</span>
          <span className="text-[10px] font-semibold text-gray-600 uppercase">
            {title}
          </span>
        </div>
        {collapsed ? (
          <ChevronRight size={12} className="text-gray-400" />
        ) : (
          <ChevronDown size={12} className="text-gray-400" />
        )}
      </button>

      {!collapsed && (
        <div className="border-t border-gray-200 bg-white">
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

export const ModelIOCard: React.FC<ModelIOCardProps> = ({
  step,
  defaultCollapsed = false,
  showHeader = true,
}) => {
  const { t } = useTranslation()
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
      <div className="h-full overflow-auto custom-scrollbar bg-white p-4">
        <div className="space-y-4">
          {/* Model Info Header */}
          <div className="flex items-center gap-2 pb-2 border-b border-gray-200">
            <Brain size={14} className="text-purple-600" />
            <span className="text-xs font-semibold text-gray-700">
              Model I/O
            </span>
            <span className="text-[10px] text-gray-500 font-mono">
              ({modelProvider}/{modelName})
            </span>
            {isRunning && (
              <span className="ml-2 px-2 py-0.5 text-[10px] font-medium bg-amber-100 text-amber-700 rounded">
                等待输出...
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
            <div className="flex items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg">
              <div className="animate-pulse w-2 h-2 bg-amber-500 rounded-full" />
              <span className="text-xs text-amber-700">等待模型响应...</span>
            </div>
          )}
        </div>
      </div>
    )
  }

  // Collapsible card view
  return (
    <div className={cn(
      "border rounded-lg transition-all",
      hasOutput ? "border-green-200 bg-green-50/50" : "border-amber-200 bg-amber-50/50"
    )}>
      {/* Header */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="w-full flex items-center justify-between p-3 hover:bg-opacity-80 transition-colors"
      >
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {isCollapsed ? (
            <ChevronRight size={14} className="text-gray-500 shrink-0" />
          ) : (
            <ChevronDown size={14} className="text-gray-500 shrink-0" />
          )}
          <Brain size={14} className="text-purple-600 shrink-0" />
          <span className="text-xs font-semibold text-gray-700 truncate">
            Model I/O
          </span>
          <span className="text-[10px] text-gray-500 font-mono truncate">
            {modelProvider}/{modelName}
          </span>

          {/* Status indicator */}
          <div className="flex items-center gap-1 ml-auto">
            {hasInput && (
              <span className="px-1.5 py-0.5 text-[9px] font-medium bg-blue-100 text-blue-700 rounded">
                IN
              </span>
            )}
            {hasInput && hasOutput && (
              <ArrowRight size={10} className="text-gray-400" />
            )}
            {hasOutput ? (
              <span className="px-1.5 py-0.5 text-[9px] font-medium bg-purple-100 text-purple-700 rounded">
                OUT
              </span>
            ) : hasInput && (
              <span className="px-1.5 py-0.5 text-[9px] font-medium bg-amber-100 text-amber-700 rounded animate-pulse">
                ...
              </span>
            )}
          </div>
        </div>
      </button>

      {/* Content */}
      {!isCollapsed && (
        <div className="border-t border-gray-200 bg-white p-3 space-y-2">
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
            <div className="flex items-center gap-2 p-2 bg-amber-50 border border-amber-200 rounded">
              <div className="animate-pulse w-2 h-2 bg-amber-500 rounded-full" />
              <span className="text-[10px] text-amber-700">等待模型响应...</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
