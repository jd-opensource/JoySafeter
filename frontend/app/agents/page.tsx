'use client'

import { Bot, Loader2, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { AgentCard } from '@/components/agents/agent-card'
import { AgentFormDialog } from '@/components/agents/agent-form-dialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAgents, useCreateAgent, useUpdateAgent } from '@/hooks/queries/agents'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'
import type { Agent, CreateAgentRequest } from '@/types/agent'

export default function AgentsPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agents = [], isLoading } = useAgents(workspaceId)
  const createMutation = useCreateAgent()
  const updateMutation = useUpdateAgent()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)

  function handleCreate() {
    setEditingAgent(null)
    setDialogOpen(true)
  }

  function handleEdit(agent: Agent) {
    setEditingAgent(agent)
    setDialogOpen(true)
  }

  function handleNavigate(agent: Agent) {
    router.push(`/agents/${agent.id}`)
  }

  function handleSubmit(data: CreateAgentRequest) {
    if (editingAgent) {
      const { definition_kind, definition_payload, capability_manifest, ...rest } = data
      updateMutation.mutate(
        { agentId: editingAgent.id, workspaceId, ...rest },
        { onSuccess: () => setDialogOpen(false) },
      )
    } else {
      createMutation.mutate(
        { ...data, workspace_id: workspaceId },
        { onSuccess: () => setDialogOpen(false) },
      )
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      {/* Header */}
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">{t('agents.title')}</h1>
          </div>
          <Button size="sm" className="gap-1.5" onClick={handleCreate}>
            <Plus className="h-4 w-4" />
            {t('agents.newAgent')}
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('agents.loading')}
          </div>
        ) : agents.length === 0 ? (
          <Card className="border-dashed border-[var(--border)] bg-[var(--surface-1)] p-8 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--surface-3)] text-[var(--text-muted)]">
              <Bot className="h-5 w-5" />
            </div>
            <h2 className="mt-4 text-sm font-semibold text-[var(--text-primary)]">
              {t('agents.emptyTitle')}
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">{t('agents.emptyDescription')}</p>
            <Button size="sm" className="mt-4 gap-1.5" onClick={handleCreate}>
              <Plus className="h-4 w-4" />
              {t('agents.newAgent')}
            </Button>
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onClick={handleNavigate}
                onEdit={handleEdit}
              />
            ))}
          </div>
        )}
      </div>

      {/* Dialog */}
      <AgentFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        agent={editingAgent}
        workspaceId={workspaceId}
        onSubmit={handleSubmit}
        isPending={isPending}
      />
    </div>
  )
}
