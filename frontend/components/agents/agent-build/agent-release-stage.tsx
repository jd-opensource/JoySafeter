'use client'

import { Loader2, Rocket } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { agentKeys } from '@/hooks/queries/agents'
import {
  releaseKeys,
  useReleases,
  useActivateRelease,
  useRetireRelease,
} from '@/hooks/queries/agentReleases'
import { versionKeys } from '@/hooks/queries/agentVersions'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'
import type { RuntimeKind } from '@/types/agent-release'

import { hasVersionContent } from './agent-build-types'
import type { StageProps } from './agent-build-types'
import { agentReleaseAdapter } from './agent-release-adapter'

function deriveRuntimeKind(definitionKind: string | undefined): RuntimeKind {
  switch (definitionKind) {
    case 'graph': return 'graph'
    case 'hybrid': return 'graph'
    case 'code': return 'sandbox'
    default: return 'graph'
  }
}

export function AgentReleaseStage({ agent, version, workspaceId }: StageProps) {
  const versionId = version?.id
  const runtimeKind = deriveRuntimeKind(version?.definition_kind)
  const canPublishDraft = version ? hasVersionContent(version) : false
  const { t } = useTranslation()
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const { canAdmin } = useUserPermissionsContext()
  const { data: releases = [], isLoading } = useReleases(agent.id, workspaceId, {
    enabled: Boolean(workspaceId),
  })
  const activateRelease = useActivateRelease()
  const retireRelease = useRetireRelease()
  const [isPublishing, setIsPublishing] = useState(false)

  const canPublish = canAdmin && Boolean(versionId) && canPublishDraft && !isPublishing

  const handlePublish = async () => {
    if (!versionId || !canPublish) return
    setIsPublishing(true)
    try {
      await agentReleaseAdapter.publish(agent.id, versionId, workspaceId, runtimeKind)
      await queryClient.invalidateQueries({ queryKey: versionKeys.all(agent.id, workspaceId) })
      await queryClient.invalidateQueries({ queryKey: releaseKeys.all(agent.id, workspaceId) })
      await queryClient.invalidateQueries({ queryKey: agentKeys.detail(agent.id, workspaceId) })
      toast({
        title: t('workspace.deploySuccess', { defaultValue: 'Published' }),
        variant: 'success',
      })
    } catch (error) {
      toast({
        title: t('workspace.deployFailed', { defaultValue: 'Publish failed' }),
        description: error instanceof Error ? error.message : String(error),
        variant: 'destructive',
      })
    } finally {
      setIsPublishing(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-[var(--surface-1)] p-6">
      <div className="mx-auto max-w-5xl space-y-5">
        <div className="flex flex-col gap-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-5 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
              {t('agents.build.release.kicker', { defaultValue: 'Release lifecycle' })}
            </p>
            <h2 className="mt-1 text-2xl font-semibold text-[var(--text-primary)]">
              {t('agents.build.release.title', { defaultValue: 'Publish and manage releases' })}
            </h2>
            <p className="mt-2 max-w-2xl text-sm text-[var(--text-secondary)]">
              {t('agents.build.release.subtitle', {
                defaultValue:
                  'Release freezes the current draft into a business-ready version. Active releases power chat, tasks, and API usage.',
              })}
            </p>
          </div>
          <Button onClick={handlePublish} disabled={!canPublish}>
            {isPublishing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Rocket className="mr-2 h-4 w-4" />
            )}
            {t('agents.build.release.publishDraft', { defaultValue: 'Publish Draft' })}
          </Button>
        </div>

        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              {t('agents.build.release.releases', { defaultValue: 'Release History' })}
            </h3>
            <Badge variant={agent.active_release_id ? 'default' : 'outline'}>
              {agent.active_release_id
                ? t('agents.build.status.published', { defaultValue: 'Published' })
                : t('agents.build.status.notPublished', { defaultValue: 'Not Published' })}
            </Badge>
          </div>

          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('common.loading', { defaultValue: 'Loading...' })}
            </div>
          ) : releases.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--text-muted)]">
              {t('agents.build.release.empty', { defaultValue: 'No releases yet.' })}
            </div>
          ) : (
            <div className="space-y-2">
              {releases.map((release) => {
                const isActive = agent.active_release_id === release.id
                return (
                  <div
                    key={release.id}
                    className="flex flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3 md:flex-row md:items-center md:justify-between"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-[var(--text-primary)]">
                        #{release.release_number}
                      </span>
                      <Badge variant={release.status === 'ready' ? 'default' : 'secondary'}>
                        {release.status}
                      </Badge>
                      <Badge variant="outline">{release.runtime_kind}</Badge>
                      {isActive && (
                        <Badge className="bg-[var(--status-success)] text-white">
                          {t('workspace.active', { defaultValue: 'Active' })}
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {!isActive && release.status === 'ready' && canAdmin && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            activateRelease.mutate({
                              agentId: agent.id,
                              releaseId: release.id,
                              workspaceId,
                            })
                          }
                          disabled={activateRelease.isPending}
                        >
                          {t('workspace.deploy', { defaultValue: 'Activate' })}
                        </Button>
                      )}
                      {isActive && canAdmin && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            retireRelease.mutate({
                              agentId: agent.id,
                              releaseId: release.id,
                              workspaceId,
                            })
                          }
                          disabled={retireRelease.isPending}
                        >
                          {t('workspace.undeploy', { defaultValue: 'Retire' })}
                        </Button>
                      )}
                      <span className="text-xs text-[var(--text-muted)]">
                        {release.published_at
                          ? new Date(release.published_at).toLocaleDateString()
                          : '-'}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
