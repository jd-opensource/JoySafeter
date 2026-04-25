'use client'

import { MessageSquare, Plug, Terminal } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useTranslation } from '@/lib/i18n'
import type { StageProps } from './agent-build-types'
import { AgentApiAccessDialog } from './agent-api-access-dialog'

export function AgentUsageStage({ agent, workspaceId }: StageProps) {
  const { t } = useTranslation()
  const [apiAccessOpen, setApiAccessOpen] = useState(false)
  const hasActiveRelease = Boolean(agent.active_release_id)

  return (
    <div className="h-full overflow-y-auto bg-[var(--surface-1)] p-6">
      <div className="mx-auto max-w-5xl space-y-5">
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-5">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
            {t('agents.build.usage.kicker', { defaultValue: 'Business usage' })}
          </p>
          <h2 className="mt-1 text-2xl font-semibold text-[var(--text-primary)]">
            {t('agents.build.usage.title', {
              defaultValue: 'Use this Agent in business scenarios',
            })}
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-[var(--text-secondary)]">
            {hasActiveRelease
              ? t('agents.build.usage.subtitleReady', {
                  defaultValue:
                    'The active release can now be connected to chat, tasks, API calls, and business workflows.',
                })
              : t('agents.build.usage.subtitleNoRelease', {
                  defaultValue:
                    'Publish and activate a release before connecting this Agent to business usage.',
                })}
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
            <MessageSquare className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <h3 className="mt-3 text-sm font-semibold text-[var(--text-primary)]">
              {t('agents.build.usage.chat', { defaultValue: 'Chat' })}
            </h3>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              {t('agents.build.usage.chatDesc', {
                defaultValue: 'Start conversations against the active release.',
              })}
            </p>
          </Card>
          <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
            <Plug className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <h3 className="mt-3 text-sm font-semibold text-[var(--text-primary)]">
              {t('agents.build.usage.tasks', { defaultValue: 'Tasks and workflows' })}
            </h3>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              {t('agents.build.usage.tasksDesc', {
                defaultValue: 'Attach this Agent to task execution and operational flows.',
              })}
            </p>
          </Card>
          <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
            <Terminal className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <h3 className="mt-3 text-sm font-semibold text-[var(--text-primary)]">
              {t('workspace.apiAccess', { defaultValue: 'API Access' })}
            </h3>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              {t('workspace.apiAccessDescription', {
                defaultValue: 'Generate tokens and call this Agent from external systems.',
              })}
            </p>
            <Button
              className="mt-4"
              variant="outline"
              onClick={() => setApiAccessOpen(true)}
              disabled={!hasActiveRelease}
            >
              {t('workspace.accessApi', { defaultValue: 'Access API' })}
            </Button>
          </Card>
        </div>
      </div>

      <AgentApiAccessDialog
        open={apiAccessOpen}
        onOpenChange={setApiAccessOpen}
        agentId={agent.id}
        workspaceId={workspaceId}
      />
    </div>
  )
}
