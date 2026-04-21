'use client'

import { Bot, Pencil } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import type { Agent } from '@/types/agent'

import { AgentStatusIndicator } from './agent-status'

interface AgentCardProps {
  agent: Agent
  onClick: (agent: Agent) => void
  onEdit: (agent: Agent) => void
}

export function AgentCard({ agent, onClick, onEdit }: AgentCardProps) {
  return (
    <Card
      className="flex cursor-pointer flex-col border-[var(--border)] bg-[var(--surface-1)] p-5 transition-shadow hover:shadow-md"
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
        {agent.description || 'No description'}
      </p>

      {/* Actions */}
      <div className="mt-auto flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={(e) => {
            e.stopPropagation()
            onEdit(agent)
          }}
        >
          <Pencil className="h-3.5 w-3.5" />
          Edit
        </Button>
      </div>
    </Card>
  )
}
