'use client'

import { useState } from 'react'
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Rocket,
  Undo2,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  usePublishAgent,
  useReleaseHistory,
  useRetireRelease,
  useRollbackAgent,
} from '@/hooks/queries/agentPublish'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'
import type { AgentRelease } from '@/types/agent-release'

import { hasVersionContent } from './agent-build-types'
import type { StageProps } from './agent-build-types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Hero shown when the agent has never been published. */
function UnpublishedHero({
  onPublish,
  canPublish,
  isPending,
  t,
}: {
  onPublish: () => void
  canPublish: boolean
  isPending: boolean
  t: (key: string, opts?: Record<string, string>) => string
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-6 py-20 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--accent-muted)]">
        <Rocket className="h-8 w-8 text-[var(--accent)]" />
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold text-[var(--text-primary)]">
          {t('agents.build.release.title', { defaultValue: 'Publish your Agent' })}
        </h2>
        <p className="mx-auto max-w-md text-sm text-[var(--text-secondary)]">
          {t('agents.build.release.subtitle', {
            defaultValue: 'Publish to enable chat, tasks, and API access',
          })}
        </p>
      </div>
      <Button size="lg" onClick={onPublish} disabled={!canPublish || isPending}>
        {isPending ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <Rocket className="mr-2 h-4 w-4" />
        )}
        {t('agents.build.release.publish', { defaultValue: 'Publish' })}
      </Button>
    </div>
  )
}

/** Green status card shown when the agent is published. */
function PublishedCard({
  activeRelease,
  onPublishNew,
  canPublish,
  isPending,
  t,
}: {
  activeRelease: AgentRelease | undefined
  onPublishNew: () => void
  canPublish: boolean
  isPending: boolean
  t: (key: string, opts?: Record<string, string>) => string
}) {
  return (
    <Card className="border-green-500/40 bg-green-50/50 p-5 dark:bg-green-950/20">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {t('agents.build.release.currentActive', { defaultValue: 'Currently published' })}
            </p>
            {activeRelease && (
              <p className="text-xs text-[var(--text-muted)]">
                {`版本 ${activeRelease.release_number} · 发布于 ${formatDate(activeRelease.published_at)}`}
              </p>
            )}
          </div>
        </div>
        <Button onClick={onPublishNew} disabled={!canPublish || isPending}>
          {isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Rocket className="mr-2 h-4 w-4" />
          )}
          {t('agents.build.release.publishNew', { defaultValue: 'Publish new version' })}
        </Button>
      </div>
    </Card>
  )
}

/** A single row in the release history list. */
function ReleaseRow({
  release,
  isActive,
  canAdmin,
  agentId,
  workspaceId,
  t,
}: {
  release: AgentRelease
  isActive: boolean
  canAdmin: boolean
  agentId: string
  workspaceId: string
  t: (key: string, opts?: Record<string, string>) => string
}) {
  const rollbackAgent = useRollbackAgent()
  const retireRelease = useRetireRelease()

  return (
    <div
      className={`flex flex-col gap-3 rounded-xl border p-3 md:flex-row md:items-center md:justify-between ${
        isActive
          ? 'border-green-500/40 bg-green-50/30 dark:bg-green-950/10'
          : 'border-[var(--border)] bg-[var(--surface-2)]'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-[var(--text-primary)]">
          {`版本 ${release.release_number}`}
        </span>
        <span className="text-xs text-[var(--text-muted)]">
          {`· 发布于 ${formatDate(release.published_at)}`}
        </span>
        {isActive && (
          <Badge className="bg-green-600 text-white hover:bg-green-700">
            {t('agents.build.release.currentActive', { defaultValue: 'Currently published' })}
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-2">
        {/* Rollback button — only for non-active, ready releases */}
        {!isActive && release.status === 'ready' && canAdmin && (
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              rollbackAgent.mutate({ agentId, releaseId: release.id, workspaceId })
            }
            disabled={rollbackAgent.isPending}
          >
            {rollbackAgent.isPending ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Undo2 className="mr-1.5 h-3.5 w-3.5" />
            )}
            {t('agents.build.release.rollback', { defaultValue: 'Roll back to this version' })}
          </Button>
        )}

        {/* Overflow menu with retire action */}
        {canAdmin && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="ghost" className="h-8 w-8 p-0">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() =>
                  retireRelease.mutate({ agentId, releaseId: release.id, workspaceId })
                }
                disabled={retireRelease.isPending}
                className="text-destructive"
              >
                {retireRelease.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : null}
                退役
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AgentReleaseStage({ agent, version, workspaceId }: StageProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const { canAdmin } = useUserPermissionsContext()

  const canPublishDraft = version ? hasVersionContent(version) : false
  const canPublish = canAdmin && canPublishDraft

  const publishAgent = usePublishAgent()
  const { data: releases = [], isLoading: isLoadingHistory } = useReleaseHistory(
    agent.id,
    workspaceId,
  )

  const [historyOpen, setHistoryOpen] = useState(false)

  const isPublished = Boolean(agent.active_release_id)
  const activeRelease = releases.find((r) => r.id === agent.active_release_id)

  const handlePublish = () => {
    publishAgent.mutate(
      { agentId: agent.id, workspaceId },
      {
        onSuccess: () => {
          toast({
            title: t('agents.build.release.publish', { defaultValue: 'Publish' }),
            description: t('agents.build.release.publishSuccess', {
              defaultValue: 'Agent published successfully',
            }),
            variant: 'success',
          })
        },
        onError: (error) => {
          toast({
            title: t('agents.build.release.publishFailed', {
              defaultValue: 'Publish failed',
            }),
            description: error instanceof Error ? error.message : String(error),
            variant: 'destructive',
          })
        },
      },
    )
  }

  return (
    <div className="h-full overflow-y-auto bg-[var(--surface-1)] p-6">
      <div className="mx-auto max-w-3xl space-y-5">
        {/* State 1: Unpublished — hero with centered publish button */}
        {!isPublished && (
          <UnpublishedHero
            onPublish={handlePublish}
            canPublish={canPublish}
            isPending={publishAgent.isPending}
            t={t}
          />
        )}

        {/* State 2: Published — green status card + publish new version */}
        {isPublished && (
          <>
            <PublishedCard
              activeRelease={activeRelease}
              onPublishNew={handlePublish}
              canPublish={canPublish}
              isPending={publishAgent.isPending}
              t={t}
            />

            {/* Collapsible release history */}
            <div>
              <button
                type="button"
                className="flex w-full items-center gap-2 py-2 text-sm font-semibold text-[var(--text-primary)] hover:text-[var(--text-secondary)]"
                onClick={() => setHistoryOpen((prev) => !prev)}
              >
                {historyOpen ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                {t('agents.build.release.history', { defaultValue: 'Version history' })}
                {releases.length > 0 && (
                  <Badge variant="outline" className="ml-1 text-xs">
                    {releases.length}
                  </Badge>
                )}
              </button>

              {historyOpen && (
                <div className="mt-2 space-y-2">
                  {isLoadingHistory ? (
                    <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-muted)]">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      {t('common.loading', { defaultValue: 'Loading...' })}
                    </div>
                  ) : releases.length === 0 ? (
                    <p className="py-4 text-center text-sm text-[var(--text-muted)]">
                      {t('agents.build.release.empty', { defaultValue: 'No releases yet.' })}
                    </p>
                  ) : (
                    releases.map((release) => (
                      <ReleaseRow
                        key={release.id}
                        release={release}
                        isActive={agent.active_release_id === release.id}
                        canAdmin={canAdmin}
                        agentId={agent.id}
                        workspaceId={workspaceId}
                        t={t}
                      />
                    ))
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
