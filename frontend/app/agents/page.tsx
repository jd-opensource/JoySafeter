'use client'

import { Bot, Loader2, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { AgentCard } from '@/components/agents/agent-card'
import { CreateAgentDialog } from '@/components/agents/agent-form-dialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAgents, useCreateAgent, useDeleteAgent } from '@/hooks/queries/agents'
import {
  AGENT_LIST_ENGINE_FILTERS,
  AGENT_LIST_RUNTIME_FILTERS,
  filterAgentsForList,
  type AgentListEngineFilter,
  type AgentListRuntimeFilter,
} from '@/lib/agents/agent-list-filters'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import type { Agent, CreateAgentRequest } from '@/types/agent'

export default function AgentsPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const { workspaceId } = useCurrentWorkspace()
  const { canEdit } = useUserPermissionsContext()

  const { data: agents = [], isLoading } = useAgents(workspaceId)
  const createMutation = useCreateAgent()
  const deleteMutation = useDeleteAgent()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [deletingAgent, setDeletingAgent] = useState<Agent | null>(null)
  const [engineFilter, setEngineFilter] = useState<AgentListEngineFilter>('all')
  const [runtimeFilter, setRuntimeFilter] = useState<AgentListRuntimeFilter>('all')

  const filteredAgents = filterAgentsForList(agents, {
    engineKind: engineFilter,
    runtimeKind: runtimeFilter,
  })

  async function handleSubmit(data: CreateAgentRequest) {
    try {
      const newAgent = await createMutation.mutateAsync({
        ...data,
        workspace_id: workspaceId,
      })
      setDialogOpen(false)
      router.push(`/agents/${newAgent.id}?stage=brief`)
    } catch {
      // error handled by React Query
    }
  }

  function handleNavigate(agent: Agent) {
    router.push(`/agents/${agent.id}`)
  }

  function confirmDelete() {
    if (!deletingAgent) return
    deleteMutation.mutate(
      { agentId: deletingAgent.id, workspaceId },
      { onSettled: () => setDeletingAgent(null) },
    )
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {t('common.loading')}
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto bg-[var(--bg)] p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">
            {t('agents.title', { defaultValue: 'Agents' })}
          </h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            {t('agents.subtitle', { defaultValue: 'Build and manage your AI agents' })}
          </p>
        </div>
        {canEdit && (
          <Button onClick={() => setDialogOpen(true)} className="gap-1.5">
            <Plus className="h-4 w-4" />
            {t('agents.newAgent', { defaultValue: 'New Agent' })}
          </Button>
        )}
      </div>

      {agents.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <Select
            value={engineFilter}
            onValueChange={(value) => setEngineFilter(value as AgentListEngineFilter)}
          >
            <SelectTrigger className="h-9 w-[190px] bg-[var(--surface-1)]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {AGENT_LIST_ENGINE_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {t(option.labelKey, { defaultValue: option.defaultLabel })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={runtimeFilter}
            onValueChange={(value) => setRuntimeFilter(value as AgentListRuntimeFilter)}
          >
            <SelectTrigger className="h-9 w-[190px] bg-[var(--surface-1)]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {AGENT_LIST_RUNTIME_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {t(option.labelKey, { defaultValue: option.defaultLabel })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {agents.length === 0 ? (
        <Card className="flex flex-col items-center justify-center gap-4 border-dashed p-12 text-center">
          <Bot className="h-10 w-10 text-[var(--text-muted)]" />
          <div>
            <h3 className="text-sm font-medium text-[var(--text-primary)]">
              {t('agents.emptyTitle', { defaultValue: 'No agents yet' })}
            </h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('agents.emptySubtitle', { defaultValue: 'Create your first agent to get started' })}
            </p>
          </div>
          {canEdit && (
            <Button onClick={() => setDialogOpen(true)} variant="outline" className="gap-1.5">
              <Plus className="h-4 w-4" />
              {t('agents.newAgent', { defaultValue: 'New Agent' })}
            </Button>
          )}
        </Card>
      ) : filteredAgents.length === 0 ? (
        <Card className="flex flex-col items-center justify-center gap-3 border-dashed p-10 text-center">
          <Bot className="h-8 w-8 text-[var(--text-muted)]" />
          <div>
            <h3 className="text-sm font-medium text-[var(--text-primary)]">
              {t('agents.filters.emptyTitle', { defaultValue: 'No matching agents' })}
            </h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {t('agents.filters.emptySubtitle', {
                defaultValue: 'Adjust the build type or runtime filters.',
              })}
            </p>
          </div>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filteredAgents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onClick={handleNavigate}
              onDelete={canEdit ? (a) => setDeletingAgent(a) : undefined}
            />
          ))}
        </div>
      )}

      <CreateAgentDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSubmit={handleSubmit}
        isPending={createMutation.isPending}
      />

      <ConfirmDialog
        open={Boolean(deletingAgent)}
        onOpenChange={(open) => { if (!open) setDeletingAgent(null) }}
        title={t('agents.deleteConfirmTitle', { defaultValue: 'Delete agent' })}
        description={t('agents.deleteConfirmDescription', {
          name: deletingAgent?.name,
          defaultValue: `Are you sure you want to delete "${deletingAgent?.name}"?`,
        })}
        onConfirm={confirmDelete}
        loading={deleteMutation.isPending}
        variant="destructive"
      />
    </div>
  )
}
