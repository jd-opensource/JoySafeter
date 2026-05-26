'use client'

import { Bot, Settings, History } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import type { AgentProfile } from '@/types/agents'
import { RUNTIME_TYPE_LABELS } from '@/types/agents'

import { AgentStatusIndicator } from './agent-status'

interface AgentCardProps {
  agent: AgentProfile
  onConfigure: (agent: AgentProfile) => void
  onHistory: (agent: AgentProfile) => void
}

export function AgentCard({ agent, onConfigure, onHistory }: AgentCardProps) {
  const skillCount = agent.skill_ids?.length ?? 0

  return (
    <Card className="flex flex-col border-[var(--border)] bg-[var(--surface-1)] p-5 transition-shadow hover:shadow-md">
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
          </div>
        </div>
        <AgentStatusIndicator status={agent.status} />
      </div>

      {/* Runtime badge */}
      <div className="mb-2">
        <Badge
          variant="outline"
          className="border-[var(--border)] bg-[var(--surface-2)] text-xs text-[var(--text-secondary)]"
        >
          {RUNTIME_TYPE_LABELS[agent.runtime_type]}
        </Badge>
      </div>

      {/* Description */}
      <p className="mb-4 line-clamp-2 min-h-[2.5rem] text-sm text-[var(--text-muted)]">
        {agent.description || 'No description'}
      </p>

      {/* Meta */}
      <div className="mb-4 flex items-center gap-4 text-xs text-[var(--text-muted)]">
        <span>Skills: {skillCount}</span>
        <span>Max tasks: {agent.max_concurrent_tasks}</span>
      </div>

      {/* Actions */}
      <div className="mt-auto flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="flex-1 gap-1.5"
          onClick={() => onConfigure(agent)}
        >
          <Settings className="h-3.5 w-3.5" />
          Configure
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="flex-1 gap-1.5"
          onClick={() => onHistory(agent)}
        >
          <History className="h-3.5 w-3.5" />
          History
        </Button>
      </div>
    </Card>
  )
}
