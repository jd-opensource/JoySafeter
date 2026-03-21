/**
 * CopilotChat - Chat messages display component
 */

import { Sparkles, Zap, Check, Copy, Workflow, Database, GitBranch } from 'lucide-react'
import React, { useState } from 'react'

import type { CopilotMessage } from '@/hooks/copilot/useCopilotMessages'
import { useTranslation } from '@/lib/i18n'
import { copyToClipboard } from '@/lib/utils/clipboard'
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
      <div className="flex flex-col items-center pb-2 pt-4 text-center">
        <div className="mb-3 flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-purple-100 bg-gradient-to-br from-purple-100 to-blue-50 text-purple-600">
          <Sparkles size={24} />
        </div>
        <p className="mb-6 px-2 text-sm font-medium text-gray-700">
          {t('workspace.copilotEmptyHeading')}
        </p>

        <p className="mb-3 w-full px-1 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
          {t('workspace.copilotStartWithBlueprint')}
        </p>
        <div className="w-full space-y-3">
          {BLUEPRINT_KEYS.map((bp, i) => {
            const Icon = bp.icon
            const prompt = t(bp.promptKey)
            return (
              <button
                key={i}
                type="button"
                onClick={() => onBlueprintSelect?.(prompt)}
                className="group w-full rounded-xl border border-gray-200 bg-gray-50/80 p-3 text-left transition-all hover:border-purple-200 hover:bg-gray-100"
              >
                <div className="mb-1 flex items-center gap-2">
                  <Icon
                    size={16}
                    className="shrink-0 text-purple-500 group-hover:text-purple-600"
                  />
                  <span className="text-sm font-semibold text-gray-800">{t(bp.titleKey)}</span>
                </div>
                <p className="line-clamp-2 text-xs text-gray-500">{t(bp.descKey)}</p>
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
        <div
          key={i}
          className={`flex gap-2 ${m.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
        >
          <div
            className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full shadow-sm ${m.role === 'model' ? 'border border-purple-100 bg-gradient-to-br from-purple-100 to-blue-50 text-purple-600' : 'bg-gray-100 text-gray-600'} `}
          >
            {m.role === 'model' ? (
              <Sparkles size={16} />
            ) : (
              <div className="h-2 w-2 rounded-full bg-gray-400" />
            )}
          </div>

          <div className="flex max-w-[85%] flex-col gap-2">
            {/* Message content */}
            <div
              className={`group relative rounded-2xl text-xs leading-relaxed shadow-sm ${
                m.role === 'user'
                  ? 'rounded-br-none bg-blue-600 text-white'
                  : 'rounded-bl-none border border-gray-100 bg-white text-gray-800'
              } `}
            >
              {/* Copy button */}
              <button
                onClick={async (e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  try {
                    await copyToClipboard(m.text)
                    setCopiedMessageId(i)
                    setTimeout(() => setCopiedMessageId(null), 2000)
                  } catch (err) {
                    console.error('Failed to copy:', err)
                  }
                }}
                className="absolute right-1 top-1 z-10 rounded p-1.5 opacity-0 transition-opacity hover:bg-black/10 group-hover:opacity-100"
                title="复制"
              >
                {copiedMessageId === i ? (
                  <Check
                    size={12}
                    className={m.role === 'user' ? 'text-green-300' : 'text-green-600'}
                  />
                ) : (
                  <Copy
                    size={12}
                    className={m.role === 'user' ? 'text-white/80' : 'text-gray-500'}
                  />
                )}
              </button>
              {/* Scrollable content */}
              <div className="custom-scrollbar max-h-64 overflow-y-auto p-3 pr-5">
                <div className="whitespace-pre-wrap break-words">{m.text}</div>
              </div>
            </div>

            {/* Thought steps */}
            {m.thoughtSteps && m.thoughtSteps.length > 0 && (
              <div className="space-y-2 rounded-xl border border-indigo-100 bg-indigo-50 p-3 duration-300 animate-in fade-in slide-in-from-top-2">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-indigo-700">
                  <Sparkles size={10} className="fill-current" /> {t('workspace.thinkingProcess')}
                </div>
                <div className="space-y-1.5">
                  {m.thoughtSteps.map((step, idx) => (
                    <div
                      key={idx}
                      className="flex gap-2 rounded-lg border border-indigo-100/50 bg-white/80 p-2"
                    >
                      <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[10px] font-bold text-indigo-600">
                        {step.index}
                      </div>
                      <p className="flex-1 text-[10px] leading-relaxed text-gray-700">
                        {step.content}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Actions */}
            {m.actions && m.actions.length > 0 && (
              <div className="space-y-2 rounded-xl border border-purple-100 bg-purple-50 p-3 duration-300 animate-in fade-in slide-in-from-top-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-purple-700">
                    <Zap size={10} className="fill-current" /> {t('workspace.actionsExecuted')}
                    {m.actions.length > 0 && (
                      <span className="rounded bg-purple-100/50 px-1.5 py-0.5 text-[9px] font-normal normal-case text-purple-600">
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
                    <div className="flex gap-2 rounded-lg border border-purple-100/50 bg-white/80 p-2">
                      <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-purple-100 text-[10px] font-bold text-purple-600">
                        {idx + 1}
                      </div>
                      <p className="flex-1 text-[10px] leading-relaxed text-gray-700">
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
