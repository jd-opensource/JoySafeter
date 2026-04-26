'use client'

import { ArrowRight, Bot, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useTranslation } from '@/lib/i18n'
import type { Agent } from '@/types/agent'

import { AgentStatusIndicator } from './agent-status'

interface AgentCardProps {
  agent: Agent
  onClick: (agent: Agent) => void
  onDelete?: (agent: Agent) => void
}

function formatRelativeTime(dateStr: string): string {
  const now = Date.now()
  const date = new Date(dateStr).getTime()
  const diff = now - date
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString()
}

function getActionHint(agent: Agent, t: (key: string, opts?: { defaultValue?: string }) => string) {
  if (agent.active_release_id) {
    return t('agents.card.hintPublished', { defaultValue: 'View usage & manage' })
  }
  if (agent.current_draft_version_id) {
    return t('agents.card.hintBuilding', { defaultValue: 'Continue building' })
  }
  return t('agents.card.hintNew', { defaultValue: 'Start building' })
}

export function AgentCard({ agent, onClick, onDelete }: AgentCardProps) {
  const { t } = useTranslation()
  const hasRelease = Boolean(agent.active_release_id)

  return (
    <Card
      className="group flex cursor-pointer flex-col border-[var(--border)] bg-[var(--surface-1)] p-5 transition-all hover:border-[var(--skill-brand-200)] hover:shadow-md"
      onClick={() => onClick(agent)}
    >
      {/* Header */}
      <div className="mb-3 flex items-start justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--skill-brand-50)] text-[var(--skill-brand-600)]">
            <Bot className="h-4.5 w-4.5" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-[var(--text-primary)]">
              {agent.name}
            </h3>
            <p className="truncate text-xs text-[var(--text-muted)]">{agent.slug}</p>
          </div>
        </div>
        <AgentStatusIndicator status={agent.status} />
      </div>

      {/* Description */}
      <p className="mb-4 line-clamp-2 min-h-[2.5rem] text-sm text-[var(--text-muted)]">
        {agent.description || t('agents.noDescription', { defaultValue: 'No description yet' })}
      </p>

      {/* Meta */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <Badge variant={hasRelease ? 'default' : 'outline'} className="text-[10px]">
          {hasRelease
            ? t('agents.card.published', { defaultValue: 'Published' })
            : t('agents.card.draft', { defaultValue: 'Draft' })}
        </Badge>
        <span className="text-[10px] text-[var(--text-muted)]">
          {formatRelativeTime(agent.updated_at)}
        </span>
      </div>

      {/* Footer: action hint + delete */}
      <div className="mt-auto flex items-center justify-between border-t border-[var(--border)] pt-3">
        <span className="flex items-center gap-1 text-xs font-medium text-[var(--skill-brand-600)] opacity-0 transition-opacity group-hover:opacity-100">
          {getActionHint(agent, t)}
          <ArrowRight className="h-3 w-3" />
        </span>
        {onDelete && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 text-[var(--text-muted)] opacity-0 transition-opacity hover:text-[var(--error-text)] group-hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation()
              onDelete(agent)
            }}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        )}
      </div>
    </Card>
  )
}
