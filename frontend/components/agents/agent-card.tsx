'use client'

import { ArrowRight, Bot, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useTranslation } from '@/lib/i18n'
import { formatRelativeTime } from '@/lib/utils/dateHelpers'
import type { Agent } from '@/types/agent'

import { AgentStatusIndicator } from './agent-status'

const DEFINITION_LABEL_KEYS: Record<string, { labelKey: string; defaultLabel: string }> = {
  langgraph_visual: { labelKey: 'agents.graph.shortLabel', defaultLabel: 'Graph' },
  langgraph_code: { labelKey: 'agents.code.shortLabel', defaultLabel: 'Code' },
  claude_code: { labelKey: 'agents.claudeCode.shortLabel', defaultLabel: 'Claude Code' },
  codex: { labelKey: 'agents.codex.shortLabel', defaultLabel: 'Codex' },
  openclaw: { labelKey: 'agents.openclaw.shortLabel', defaultLabel: 'OpenClaw' },
}

interface AgentCardProps {
  agent: Agent
  onClick: (agent: Agent) => void
  onDelete?: (agent: Agent) => void
}

export function AgentCard({ agent, onClick, onDelete }: AgentCardProps) {
  const { t } = useTranslation()
  const actionHint = agent.active_release_id
    ? t('agents.card.hintPublished', { defaultValue: 'View usage & manage' })
    : agent.current_draft_version_id
      ? t('agents.card.hintBuilding', { defaultValue: 'Continue building' })
      : t('agents.card.hintNew', { defaultValue: 'Start building' })

  const timeText = agent.updated_at ? formatRelativeTime(agent.updated_at, t) : ''
  const definitionLabel = agent.engine_kind ? DEFINITION_LABEL_KEYS[agent.engine_kind] : null

  return (
    <Card
      className="group flex cursor-pointer flex-col border-[var(--border)] bg-[var(--surface-1)] p-4 transition-all hover:border-[var(--skill-brand-200)] hover:shadow-md"
      onClick={() => onClick(agent)}
    >
      {/* Header */}
      <div className="mb-2 flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--skill-brand-50)] text-[var(--skill-brand-600)]">
            <Bot className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-[var(--text-primary)]">
              {agent.name}
            </h3>
          </div>
        </div>
        <AgentStatusIndicator status={agent.status} />
      </div>

      {/* Description */}
      <p className="mb-3 line-clamp-2 min-h-[2rem] text-xs text-[var(--text-muted)]">
        {agent.description || t('agents.noDescription', { defaultValue: 'No description yet' })}
      </p>

      {/* Meta + Action — single compact row */}
      <div className="mt-auto flex items-center justify-between pt-2">
        <div className="flex items-center gap-1.5">
          {definitionLabel && (
            <span className="inline-flex h-5 items-center rounded-md border border-[var(--border)] px-1.5 text-[10px] text-[var(--text-muted)]">
              {t(definitionLabel.labelKey, { defaultValue: definitionLabel.defaultLabel })}
            </span>
          )}
          {timeText && (
            <span className="text-[10px] text-[var(--text-muted)]">{timeText}</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <span className="flex items-center gap-0.5 text-[10px] font-medium text-[var(--skill-brand-600)] opacity-0 transition-opacity group-hover:opacity-100">
            {actionHint}
            <ArrowRight className="h-2.5 w-2.5" />
          </span>
          {onDelete && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0 text-[var(--text-muted)] opacity-0 transition-opacity hover:text-[var(--error-text)] group-hover:opacity-100"
              aria-label={t('agents.card.delete', { defaultValue: 'Delete agent' })}
              onClick={(e) => {
                e.stopPropagation()
                onDelete(agent)
              }}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}
