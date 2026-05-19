'use client'

import {
  Archive,
  ChevronDown,
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Pencil,
  Save,
  Undo2,
} from 'lucide-react'
import { useState } from 'react'

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
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useAgent, useUpdateAgent } from '@/hooks/queries/agents'
import { useReleaseHistory, useRollbackAgent, useRetireRelease } from '@/hooks/queries/agentPublish'
import { useVersion } from '@/hooks/queries/agentVersions'
import { useTranslation } from '@/lib/i18n'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import { useUserPermissionsContext } from '@/providers/workspace-permissions-provider'
import { canRetire, canRollback } from '@/types/agent-release'

interface AgentSettingsTabProps {
  agentId: string
}

export function AgentSettingsTab({ agentId }: AgentSettingsTabProps) {
  const { t } = useTranslation()

  const { workspaceId } = useCurrentWorkspace()
  const { canEdit, canAdmin } = useUserPermissionsContext()

  const { data: agent } = useAgent(agentId, workspaceId)
  const updateAgent = useUpdateAgent()

  const draftVersionId = agent?.current_draft_version_id || ''
  const { data: draftVersion } = useVersion(agentId, draftVersionId, workspaceId, {
    enabled: Boolean(draftVersionId),
  })

  const isPublished = Boolean(agent?.active_release_id)
  const { data: releases = [], isLoading: releasesLoading } = useReleaseHistory(
    agentId,
    workspaceId,
    {
      enabled: isPublished,
    },
  )
  const rollbackAgent = useRollbackAgent()
  const retireRelease = useRetireRelease()

  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [avatar, setAvatar] = useState('')

  const [releasesOpen, setReleasesOpen] = useState(false)

  if (!agent) return null

  const startEditing = () => {
    setName(agent.name)
    setDescription(agent.description || '')
    setAvatar(agent.avatar || '')
    setEditing(true)
  }

  const handleSave = async () => {
    try {
      await updateAgent.mutateAsync({
        agentId,
        workspaceId,
        name: name.trim() || agent.name,
        description: description.trim() || undefined,
        avatar: avatar.trim() || undefined,
      })
      setEditing(false)
    } catch {
      // Global error handler shows toast
    }
  }

  const ENGINE_KIND_LABELS: Record<string, string> = {
    langgraph_visual: t('agents.graph.label'),
    langgraph_code: t('agents.code.label'),
    claude_code: t('agents.claudeCode.label'),
    codex: t('agents.codex.label'),
    openclaw: t('agents.openclaw.label'),
  }

  return (
    <div className="space-y-6 px-8 py-6">
      {/* Section 1: Basic Info */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {t('agents.detail.basicInfo')}
          </h2>
          {!editing && canEdit && (
            <Button variant="outline" size="sm" onClick={startEditing}>
              <Pencil className="mr-1.5 h-3.5 w-3.5" />
              {t('settings.edit')}
            </Button>
          )}
        </div>

        {editing ? (
          <div className="mt-4 space-y-3">
            <div>
              <label className="mb-1 block text-xs text-[var(--text-muted)]">
                {t('settings.name')}
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={agent.name}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--text-muted)]">
                {t('tasks.description')}
              </label>
              <Textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={t('tasks.description')}
                rows={3}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-[var(--text-muted)]">
                {t('agents.avatar')}
              </label>
              <Input
                value={avatar}
                onChange={(e) => setAvatar(e.target.value)}
                placeholder={t('agents.avatarPlaceholder')}
              />
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={handleSave} disabled={updateAgent.isPending}>
                {updateAgent.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                )}
                {t('settings.save')}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                {t('common.cancel')}
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            <div className="text-sm text-[var(--text-primary)]">{agent.name}</div>
            <div className="text-sm text-[var(--text-muted)]">
              {agent.description || t('agents.detail.noActivity')}
            </div>
            {agent.avatar && (
              <div className="text-xs text-[var(--text-muted)]">
                {t('agents.avatar')}: {agent.avatar}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Section 2: Definition Method */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <h2 className="text-sm font-semibold text-[var(--text-primary)]">
          {t('agents.detail.definitionMethod')}
        </h2>
        {draftVersion ? (
          <div className="mt-3 flex items-center gap-3 text-sm text-[var(--text-muted)]">
            <Badge variant="outline">
              {ENGINE_KIND_LABELS[draftVersion.engine_kind] || draftVersion.engine_kind}
            </Badge>
            <span>v{draftVersion.version_number}</span>
            <Badge variant="secondary">
              {draftVersion.status === 'frozen'
                ? t('agents.detail.versionStatus.frozen')
                : t('agents.detail.versionStatus.draft')}
            </Badge>
          </div>
        ) : (
          <p className="mt-3 text-sm text-[var(--text-muted)]">{t('agents.detail.noActivity')}</p>
        )}
      </Card>

      {/* Section 3: Release History (collapsible) */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)]">
        <div
          onClick={() => setReleasesOpen(!releasesOpen)}
          className="flex w-full cursor-pointer items-center justify-between p-5 text-left"
        >
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {t('agents.detail.releaseHistory', { defaultValue: 'Release History' })}
          </h2>
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--text-muted)]">
              {t('agents.detail.goToPublish', { defaultValue: 'Go to publish' })}
            </span>
            {releasesOpen ? (
              <ChevronDown className="h-4 w-4 text-[var(--text-muted)]" />
            ) : (
              <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />
            )}
          </div>
        </div>
        {releasesOpen && (
          <div className="border-t border-[var(--border)] px-5 py-4">
            {releasesLoading ? (
              <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('common.loading')}
              </div>
            ) : releases.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">{t('agents.detail.noActivity')}</p>
            ) : (
              <div className="space-y-2">
                {releases.map((rel) => {
                  const isActive = rel.status === 'active'

                  return (
                    <div
                      key={rel.id}
                      className={`flex items-center justify-between rounded-lg border p-3 ${
                        isActive
                          ? 'bg-[var(--status-success)]/5 border-[var(--status-success)]'
                          : 'border-[var(--border)] bg-[var(--surface-2)]'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--text-primary)]">
                          {t('agents.detail.releaseVersion', {
                            defaultValue: 'Version {{number}}',
                            number: rel.release_number,
                          })}
                        </span>
                        <span className="text-xs text-[var(--text-muted)]">
                          {rel.published_at
                            ? t('agents.detail.publishedAt', {
                                defaultValue: 'published {{date}}',
                                date: new Date(rel.published_at).toLocaleDateString(),
                              })
                            : '-'}
                        </span>
                        <ReleaseStatusBadge status={rel.status} />
                      </div>
                      <div className="flex items-center gap-2">
                        {!isActive && canRollback(rel.status) && canAdmin && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              rollbackAgent.mutate({
                                agentId,
                                releaseId: rel.id,
                                workspaceId,
                              })
                            }
                            disabled={rollbackAgent.isPending}
                          >
                            <Undo2 className="mr-1.5 h-3 w-3" />
                            {t('agents.detail.rollbackToVersion', {
                              defaultValue: 'Rollback to this version',
                            })}
                          </Button>
                        )}
                        {canAdmin && canRetire(rel.status) && (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                                <MoreHorizontal className="h-4 w-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem
                                onClick={() =>
                                  retireRelease.mutate({
                                    agentId,
                                    releaseId: rel.id,
                                    workspaceId,
                                  })
                                }
                                className="text-destructive"
                              >
                                <Archive className="mr-2 h-4 w-4" />
                                {t('agents.detail.retireRelease', {
                                  defaultValue: 'Retire',
                                })}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
