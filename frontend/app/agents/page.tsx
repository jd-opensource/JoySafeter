'use client'

import { Bot, Loader2, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { AgentCard } from '@/components/agents/agent-card'
import { CreateAgentDialog } from '@/components/agents/agent-form-dialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useAgents, useCreateAgent, useDeleteAgent } from '@/hooks/queries/agents'
import { useTranslation } from '@/lib/i18n'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'
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

  function handleCreate() {
    setDialogOpen(true)
  }

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

  function handleDelete(agent: Agent) {
    setDeletingAgent(agent)
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
      <div className="mx-auto max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-[var(--text-primary)]">
              {t('agents.title')}
            </h1>
            <p className="mt-1 text-sm text-[var(--text-muted)]">{t('agents.subtitle')}</p>
          </div>
          {canEdit && (
            <Button onClick={handleCreate} className="gap-1.5">
              <Plus className="h-4 w-4" />
              {t('agents.newAgent')}
            </Button>
          )}
        </div>

        {agents.length === 0 ? (
          <Card className="flex flex-col items-center justify-center gap-4 border-dashed p-12 text-center">
            <Bot className="h-10 w-10 text-[var(--text-muted)]" />
            <div>
              <h3 className="text-sm font-medium text-[var(--text-primary)]">
                {t('agents.emptyTitle')}
              </h3>
              <p className="mt-1 text-sm text-[var(--text-muted)]">{t('agents.emptySubtitle')}</p>
            </div>
            {canEdit && (
              <Button onClick={handleCreate} variant="outline" className="gap-1.5">
                <Plus className="h-4 w-4" />
                {t('agents.newAgent')}
              </Button>
            )}
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onClick={handleNavigate}
                onDelete={canEdit ? handleDelete : undefined}
              />
            ))}
          </div>
        )}
      </div>

      <CreateAgentDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSubmit={handleSubmit}
        isPending={createMutation.isPending}
      />

      <ConfirmDialog
        open={Boolean(deletingAgent)}
        onOpenChange={(open) => !open && setDeletingAgent(null)}
        title={t('agents.deleteConfirmTitle')}
        description={t('agents.deleteConfirmDescription', { name: deletingAgent?.name })}
        onConfirm={confirmDelete}
        loading={deleteMutation.isPending}
        variant="destructive"
      />
    </div>
  )
}
