'use client'

import { useMemo, useState } from 'react'
import {
  Archive,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Rocket,
  Undo2,
  XCircle,
} from 'lucide-react'

import { ReleaseStatusBadge } from '@/components/agents/release-status-badge'
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
  useUnpublishAgent,
} from '@/hooks/queries/agentPublish'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/permissions-provider'
import type { AgentRelease } from '@/types/agent-release'
import { canRetire, canRollback } from '@/types/agent-release'

import { hasVersionContent } from './agent-build-types'
import type { StageProps } from './agent-build-types'

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

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

function PublishedCard({
  activeRelease,
  onPublishNew,
  onUnpublish,
  canPublish,
  canAdmin,
  isPublishing,
  isUnpublishing,
  t,
}: {
  activeRelease: AgentRelease | undefined
  onPublishNew: () => void
  onUnpublish: () => void
  canPublish: boolean
  canAdmin: boolean
  isPublishing: boolean
  isUnpublishing: boolean
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
                {`${t('agents.build.release.releaseVersion', { defaultValue: 'Version {{version}}', version: String(activeRelease.release_number) })} · ${t('agents.build.release.publishedAt', { defaultValue: 'Published' })} ${formatDate(activeRelease.published_at)}`}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {canAdmin && (
            <Button variant="outline" onClick={onUnpublish} disabled={isUnpublishing}>
              {isUnpublishing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <XCircle className="mr-2 h-4 w-4" />
              )}
              {t('agents.build.release.unpublish', { defaultValue: 'Unpublish' })}
            </Button>
          )}
          <Button onClick={onPublishNew} disabled={!canPublish || isPublishing}>
            {isPublishing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Rocket className="mr-2 h-4 w-4" />
            )}
            {t('agents.build.release.publishNew', { defaultValue: 'Publish new version' })}
          </Button>
        </div>
      </div>
    </Card>
  )
}

function ReleaseRow({
  release,
  isAdmin,
  onRollback,
  isRollingBack,
  onRetire,
  isRetiring,
  t,
}: {
  release: AgentRelease
  isAdmin: boolean
  onRollback: (releaseId: string) => void
  isRollingBack: boolean
  onRetire: (releaseId: string) => void
  isRetiring: boolean
  t: (key: string, opts?: Record<string, string>) => string
}) {
  const isActive = release.status === 'active'

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
          {t('agents.build.release.releaseVersion', {
            defaultValue: 'Version {{version}}',
            version: String(release.release_number),
          })}
        </span>
        <span className="text-xs text-[var(--text-muted)]">
          {`· ${t('agents.build.release.publishedAt', { defaultValue: 'Published' })} ${formatDate(release.published_at)}`}
        </span>
        <ReleaseStatusBadge status={release.status} />
      </div>

      <div className="flex items-center gap-2">
        {!isActive && canRollback(release.status) && isAdmin && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onRollback(release.id)}
            disabled={isRollingBack}
          >
            {isRollingBack ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Undo2 className="mr-1.5 h-3.5 w-3.5" />
            )}
            {t('agents.build.release.rollback', { defaultValue: 'Roll back to this version' })}
          </Button>
        )}

        {isAdmin && canRetire(release.status) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="ghost" className="h-8 w-8 p-0">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => onRetire(release.id)}
                disabled={isRetiring}
                className="text-destructive"
              >
                {isRetiring ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Archive className="mr-2 h-4 w-4" />
                )}
                {t('agents.build.release.retireRelease', { defaultValue: 'Retire' })}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  )
}

export function AgentReleaseStage({ agent, version, projectId }: StageProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const { canAdmin } = useUserPermissionsContext()

  const canPublishDraft = version ? hasVersionContent(version) : false
  const canPublishFlag = canAdmin && canPublishDraft

  const isPublished = Boolean(agent.active_release_id)

  const publishAgent = usePublishAgent()
  const rollbackAgent = useRollbackAgent()
  const retireRelease = useRetireRelease()
  const unpublishAgent = useUnpublishAgent()
  const { data: releases = [], isLoading: isLoadingHistory } = useReleaseHistory(
    agent.id,
    projectId,
    { enabled: isPublished },
  )

  const [historyOpen, setHistoryOpen] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [pendingRollbackId, setPendingRollbackId] = useState<string | null>(null)
  const [pendingRetireId, setPendingRetireId] = useState<string | null>(null)

  const activeRelease = useMemo(() => releases.find((r) => r.status === 'active'), [releases])
  const { visibleReleases, archivedCount } = useMemo(() => {
    const archived = releases.filter((r) => r.status === 'retired')
    return {
      visibleReleases: showArchived ? releases : releases.filter((r) => r.status !== 'retired'),
      archivedCount: archived.length,
    }
  }, [releases, showArchived])

  const handlePublish = () => {
    publishAgent.mutate(
      { agentId: agent.id, projectId: projectId },
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

  const handleUnpublish = () => {
    unpublishAgent.mutate({ agentId: agent.id, projectId: projectId })
  }

  return (
    <div className="h-full overflow-y-auto bg-[var(--surface-1)] p-6">
      <div className="mx-auto max-w-3xl space-y-5">
        {!isPublished && (
          <UnpublishedHero
            onPublish={handlePublish}
            canPublish={canPublishFlag}
            isPending={publishAgent.isPending}
            t={t}
          />
        )}

        {isPublished && (
          <PublishedCard
            activeRelease={activeRelease}
            onPublishNew={handlePublish}
            onUnpublish={handleUnpublish}
            canPublish={canPublishFlag}
            canAdmin={canAdmin}
            isPublishing={publishAgent.isPending}
            isUnpublishing={unpublishAgent.isPending}
            t={t}
          />
        )}

        {releases.length > 0 && (
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
              <Badge variant="outline" className="ml-1 text-xs">
                {releases.length}
              </Badge>
            </button>

            {historyOpen && (
              <div className="mt-2 space-y-2">
                {isLoadingHistory ? (
                  <div className="flex items-center gap-2 py-4 text-sm text-[var(--text-muted)]">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t('common.loading', { defaultValue: 'Loading...' })}
                  </div>
                ) : (
                  <>
                    {visibleReleases.map((release) => (
                      <ReleaseRow
                        key={release.id}
                        release={release}
                        isAdmin={canAdmin}
                        onRollback={(releaseId) => {
                          setPendingRollbackId(releaseId)
                          rollbackAgent.mutate(
                            { agentId: agent.id, releaseId, projectId: projectId },
                            { onSettled: () => setPendingRollbackId(null) },
                          )
                        }}
                        isRollingBack={pendingRollbackId === release.id}
                        onRetire={(releaseId) => {
                          setPendingRetireId(releaseId)
                          retireRelease.mutate(
                            { agentId: agent.id, releaseId, projectId: projectId },
                            { onSettled: () => setPendingRetireId(null) },
                          )
                        }}
                        isRetiring={pendingRetireId === release.id}
                        t={t}
                      />
                    ))}

                    {archivedCount > 0 && (
                      <button
                        type="button"
                        className="mt-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                        onClick={() => setShowArchived((prev) => !prev)}
                      >
                        {showArchived
                          ? t('agents.build.release.hideArchived', {
                              defaultValue: 'Hide archived',
                            })
                          : t('agents.build.release.showArchived', {
                              defaultValue: `Show ${archivedCount} archived`,
                              num: String(archivedCount),
                            })}
                      </button>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
