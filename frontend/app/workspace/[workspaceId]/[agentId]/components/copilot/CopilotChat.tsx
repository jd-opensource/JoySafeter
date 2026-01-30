/**
 * CopilotChat - Chat messages display component
 */

import { Sparkles, Zap, Check, Copy, Workflow, Database, GitBranch } from 'lucide-react'
import React, { useState } from 'react'

import type { CopilotMessage } from '@/hooks/copilot/useCopilotMessages'
import { useTranslation } from '@/lib/i18n'
import type { GraphAction } from '@/types/copilot'

import { CollapsibleList } from './CollapsibleList'


interface CopilotChatProps {
  messages: CopilotMessage[]
  loadingHistory: boolean
  expandedItems: Set<string | number>
  onToggleExpand: (key: string | number) => void
  formatActionContent: (action: GraphAction) => string
  /** When user clicks a blueprint card, send this prompt immediately */
  onBlueprintSelect?: (prompt: string) => void
}

const BLUEPRINT_KEYS = [
  {
    titleKey: 'workspace.copilotBlueprintRagTitle',
    descKey: 'workspace.copilotBlueprintRagDesc',
    promptKey: 'workspace.copilotBlueprintRagPrompt',
    icon: Workflow,
  },
  {
    titleKey: 'workspace.copilotBlueprintDebateTitle',
    descKey: 'workspace.copilotBlueprintDebateDesc',
    promptKey: 'workspace.copilotBlueprintDebatePrompt',
    icon: GitBranch,
  },
  {
    titleKey: 'workspace.copilotBlueprintPipelineTitle',
    descKey: 'workspace.copilotBlueprintPipelineDesc',
    promptKey: 'workspace.copilotBlueprintPipelinePrompt',
    icon: Database,
  },
] as const

export function CopilotChat({
  messages,
  loadingHistory,
  expandedItems,
  onToggleExpand,
  formatActionContent,
  onBlueprintSelect,
}: CopilotChatProps) {
  const { t } = useTranslation()
  const [copiedMessageId, setCopiedMessageId] = useState<number | null>(null)

  if (loadingHistory) {
    return (
      <div className="flex items-center justify-center py-4">
        <span className="text-xs text-gray-500">{t('workspace.loadingHistory')}</span>
      </div>
    )
  }

  // Show welcome / blueprint empty state when there are no messages
  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center text-center pt-4 pb-2">
        <div className="w-12 h-12 rounded-full flex items-center justify-center shrink-0 mb-3 bg-gradient-to-br from-purple-100 to-blue-50 text-purple-600 border border-purple-100">
          <Sparkles size={24} />
        </div>
        <p className="text-sm font-medium text-gray-700 mb-6 px-2">
          {t('workspace.copilotEmptyHeading')}
        </p>

        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 w-full text-left px-1">
          {t('workspace.copilotStartWithBlueprint')}
        </p>
        <div className="space-y-3 w-full">
          {BLUEPRINT_KEYS.map((bp, i) => {
            const Icon = bp.icon
            const prompt = t(bp.promptKey)
            return (
              <button
                key={i}
                type="button"
                onClick={() => onBlueprintSelect?.(prompt)}
                className="w-full text-left p-3 rounded-xl border border-gray-200 bg-gray-50/80 hover:bg-gray-100 hover:border-purple-200 transition-all group"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Icon size={16} className="text-purple-500 group-hover:text-purple-600 shrink-0" />
                  <span className="text-sm font-semibold text-gray-800">{t(bp.titleKey)}</span>
                </div>
                <p className="text-xs text-gray-500 line-clamp-2">{t(bp.descKey)}</p>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  // Filter out empty messages to avoid displaying empty bubbles
  const filteredMessages = messages.filter((m) => m.text && m.text.trim().length > 0)

  return (
    <>
      {filteredMessages.map((m, i) => (
        <div key={i} className={`flex gap-2 ${m.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
          <div
            className={`
              w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1 shadow-sm
              ${m.role === 'model' ? 'bg-gradient-to-br from-purple-100 to-blue-50 text-purple-600 border border-purple-100' : 'bg-gray-100 text-gray-600'}
            `}
          >
            {m.role === 'model' ? (
              <Sparkles size={16} />
            ) : (
              <div className="w-2 h-2 bg-gray-400 rounded-full" />
            )}
          </div>

          <div className="flex flex-col gap-2 max-w-[85%]">
            {/* Message content */}
            <div
              className={`
                relative group rounded-2xl text-xs leading-relaxed shadow-sm
                ${
                  m.role === 'user'
                    ? 'bg-blue-600 text-white rounded-br-none'
                    : 'bg-white border border-gray-100 text-gray-800 rounded-bl-none'
                }
              `}
            >
              {/* Copy button */}
              <button
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(m.text)
                    setCopiedMessageId(i)
                    setTimeout(() => setCopiedMessageId(null), 2000)
                  } catch (err) {
                    console.error('Failed to copy:', err)
                  }
                }}
                className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded hover:bg-black/10 z-10"
                title="复制"
              >
                {copiedMessageId === i ? (
                  <Check size={12} className={m.role === 'user' ? 'text-green-300' : 'text-green-600'} />
                ) : (
                  <Copy size={12} className={m.role === 'user' ? 'text-white/80' : 'text-gray-500'} />
                )}
              </button>
              {/* Scrollable content */}
              <div className="p-3 pr-5 max-h-64 overflow-y-auto custom-scrollbar">
                <div className="whitespace-pre-wrap break-words">
                  {m.text}
                </div>
              </div>
            </div>

            {/* Thought steps */}
            {m.thoughtSteps && m.thoughtSteps.length > 0 && (
              <div className="bg-indigo-50 rounded-xl border border-indigo-100 p-3 space-y-2 animate-in fade-in slide-in-from-top-2 duration-300">
                <div className="flex items-center gap-1.5 text-[10px] font-bold text-indigo-700 uppercase tracking-wider">
                  <Sparkles size={10} className="fill-current" /> {t('workspace.thinkingProcess')}
                </div>
                <div className="space-y-1.5">
                  {m.thoughtSteps.map((step, idx) => (
                    <div
                      key={idx}
                      className="flex gap-2 bg-white/80 p-2 rounded-lg border border-indigo-100/50"
                    >
                      <div className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-600 flex items-center justify-center text-[10px] font-bold">
                        {step.index}
                      </div>
                      <p className="text-[10px] text-gray-700 leading-relaxed flex-1">
                        {step.content}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Actions */}
            {m.actions && m.actions.length > 0 && (
              <div className="bg-purple-50 rounded-xl border border-purple-100 p-3 space-y-2 animate-in fade-in slide-in-from-top-2 duration-300">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-[10px] font-bold text-purple-700 uppercase tracking-wider">
                    <Zap size={10} className="fill-current" /> {t('workspace.actionsExecuted')}
                    {m.actions.length > 0 && (
                      <span className="text-[9px] text-purple-600 font-normal normal-case bg-purple-100/50 px-1.5 py-0.5 rounded">
                        {m.actions.length} 项
                      </span>
                    )}
                  </div>
                </div>
                <CollapsibleList
                  items={m.actions}
                  expandedKeys={expandedItems}
                  onToggle={onToggleExpand}
                  expandKey={`actions-${i}`}
                  defaultVisibleCount={2}
                  getKey={(action, idx) => `action-${i}-${idx}`}
                  renderItem={(action, idx) => (
                    <div className="flex gap-2 bg-white/80 p-2 rounded-lg border border-purple-100/50">
                      <div className="flex-shrink-0 w-5 h-5 rounded-full bg-purple-100 text-purple-600 flex items-center justify-center text-[10px] font-bold">
                        {idx + 1}
                      </div>
                      <p className="text-[10px] text-gray-700 leading-relaxed flex-1">
                        {formatActionContent(action)}
                      </p>
                    </div>
                  )}
                  className="space-y-1.5"
                />
              </div>
            )}
          </div>
        </div>
      ))}
    </>
  )
}
