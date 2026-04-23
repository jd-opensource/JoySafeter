'use client'

import { ChevronDown, ChevronRight, Loader2, Pencil, Rocket, Save } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useAgent, useUpdateAgent } from '@/hooks/queries/agents'
import { useVersions, useVersion } from '@/hooks/queries/agentVersions'
import { useReleases, usePublishRelease, useActivateRelease, useRetireRelease } from '@/hooks/queries/agentReleases'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { useTranslation } from '@/lib/i18n'

interface AgentSettingsTabProps {
  agentId: string
}

export function AgentSettingsTab({ agentId }: AgentSettingsTabProps) {
  const { t } = useTranslation()

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)
  const updateAgent = useUpdateAgent()

  const draftVersionId = agent?.current_draft_version_id || ''
  const { data: draftVersion } = useVersion(agentId, draftVersionId, workspaceId, {
    enabled: Boolean(draftVersionId),
  })

  const { data: versions = [], isLoading: versionsLoading } = useVersions(agentId, workspaceId)
  const { data: releases = [], isLoading: releasesLoading } = useReleases(agentId, workspaceId, {
    enabled: Boolean(workspaceId),
  })

  const publishRelease = usePublishRelease()
  const activateRelease = useActivateRelease()
  const retireRelease = useRetireRelease()

  // Basic info editing state
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  // Collapsible sections
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [releasesOpen, setReleasesOpen] = useState(false)

  if (!agent) return null

  const startEditing = () => {
    setName(agent.name)
    setDescription(agent.description || '')
    setEditing(true)
  }

  const handleSave = async () => {
    try {
      await updateAgent.mutateAsync({
        agentId,
        workspaceId,
        name: name.trim() || agent.name,
        description: description.trim() || undefined,
      })
      setEditing(false)
    } catch {
      // Global error handler shows toast
    }
  }

  const DEFINITION_KIND_LABELS: Record<string, string> = {
    prompt: 'Prompt',
    graph: 'Graph',
    code: 'Code',
    hybrid: 'Hybrid',
  }

  return (
    <div className="space-y-6 px-8 py-6">
      {/* Section 1: Basic Info */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {t('agents.detail.basicInfo')}
          </h2>
          {!editing && (
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
              {DEFINITION_KIND_LABELS[draftVersion.definition_kind] || draftVersion.definition_kind}
            </Badge>
            <span>v{draftVersion.version_number}</span>
            <Badge variant="secondary">
              {draftVersion.status === 'frozen' ? t('workspace.deployed') : t('workspace.currentDraft')}
            </Badge>
          </div>
        ) : (
          <p className="mt-3 text-sm text-[var(--text-muted)]">
            {t('agents.detail.noActivity')}
          </p>
        )}
      </Card>

      {/* Section 3: Version Management (collapsible) */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)]">
        <button
          onClick={() => setVersionsOpen(!versionsOpen)}
          className="flex w-full items-center justify-between p-5 text-left"
        >
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {t('agents.detail.versionManagement')}
          </h2>
          {versionsOpen ? (
            <ChevronDown className="h-4 w-4 text-[var(--text-muted)]" />
          ) : (
            <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />
          )}
        </button>
        {versionsOpen && (
          <div className="border-t border-[var(--border)] px-5 py-4">
            {versionsLoading ? (
              <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('common.loading')}
              </div>
            ) : versions.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">
                {t('agents.detail.noActivity')}
              </p>
            ) : (
              <div className="space-y-2">
                {versions.map((v) => (
                  <div
                    key={v.id}
                    className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        v{v.version_number}
                      </span>
                      <Badge variant="outline">
                        {DEFINITION_KIND_LABELS[v.definition_kind] || v.definition_kind}
                      </Badge>
                      <Badge variant={v.status === 'frozen' ? 'default' : 'secondary'}>
                        {v.status === 'frozen' ? t('workspace.deployed') : t('workspace.currentDraft')}
                      </Badge>
                    </div>
                    <span className="text-xs text-[var(--text-muted)]">
                      {new Date(v.created_at).toLocaleDateString()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Section 4: Release Management (collapsible) */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)]">
        <button
          onClick={() => setReleasesOpen(!releasesOpen)}
          className="flex w-full items-center justify-between p-5 text-left"
        >
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            {t('agents.detail.releaseManagement')}
          </h2>
          {releasesOpen ? (
            <ChevronDown className="h-4 w-4 text-[var(--text-muted)]" />
          ) : (
            <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />
          )}
        </button>
        {releasesOpen && (
          <div className="border-t border-[var(--border)] px-5 py-4">
            {releasesLoading ? (
              <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('common.loading')}
              </div>
            ) : releases.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">
                {t('agents.detail.noActivity')}
              </p>
            ) : (
              <div className="space-y-2">
                {releases.map((rel) => (
                  <div
                    key={rel.id}
                    className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3"
                  >
                    <div className="flex items-center gap-2">
                      <Rocket className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                      <span className="text-sm font-medium text-[var(--text-primary)]">
                        #{rel.release_number}
                      </span>
                      <Badge
                        variant={rel.status === 'ready' ? 'default' : 'secondary'}
                      >
                        {rel.status}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {rel.runtime_kind}
                      </Badge>
                      {agent.active_release_id === rel.id && (
                        <Badge variant="default" className="bg-[var(--status-success)] text-white">
                          {t('workspace.active')}
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {rel.status === 'ready' && agent.active_release_id !== rel.id && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            activateRelease.mutate({
                              agentId,
                              releaseId: rel.id,
                              workspaceId,
                            })
                          }
                          disabled={activateRelease.isPending}
                        >
                          {t('workspace.deploy')}
                        </Button>
                      )}
                      {agent.active_release_id === rel.id && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            retireRelease.mutate({
                              agentId,
                              releaseId: rel.id,
                              workspaceId,
                            })
                          }
                          disabled={retireRelease.isPending}
                        >
                          {t('workspace.undeploy')}
                        </Button>
                      )}
                      <span className="text-xs text-[var(--text-muted)]">
                        {rel.published_at
                          ? new Date(rel.published_at).toLocaleDateString()
                          : '-'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
