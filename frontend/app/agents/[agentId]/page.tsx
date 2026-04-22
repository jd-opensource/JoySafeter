'use client'

import { Activity, FileText, GitBranch, MessageSquare, Pencil, Play, Plus, Rocket, Target } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAgent } from '@/hooks/queries/agents'
import { useAgentRuns } from '@/hooks/queries/agentRuns'
import { useReleases } from '@/hooks/queries/agentReleases'
import { useVersion } from '@/hooks/queries/agentVersions'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { RUN_STATUS_STYLES } from '@/types/agent-run'

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

export default function AgentDetailPage() {
  const params = useParams()
  const agentId = params.agentId as string

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)

  const draftVersionId = agent?.current_draft_version_id || ''
  const { data: draftVersion } = useVersion(agentId, draftVersionId, workspaceId, {
    enabled: Boolean(draftVersionId),
  })

  const { data: releases = [] } = useReleases(agentId, workspaceId, {
    enabled: Boolean(workspaceId),
  })
  const releaseIds = new Set(releases.map((r) => r.id))

  const { data: allRuns = [] } = useAgentRuns(
    { workspace_id: workspaceId },
    { enabled: Boolean(workspaceId) },
  )
  const recentRuns = allRuns.filter((run) => releaseIds.has(run.release_id)).slice(0, 5)

  if (!agent) return null

  return (
    <div className="space-y-6 px-6 py-6">
      {/* Quick Actions */}
      <div className="flex flex-wrap gap-3">
        <Button size="sm" asChild>
          <Link href={`/agents/${agentId}/threads`}>
            <MessageSquare className="mr-1.5 h-3.5 w-3.5" />
            New Thread
          </Link>
        </Button>
        <Button variant="outline" size="sm" disabled>
          <Play className="mr-1.5 h-3.5 w-3.5" />
          Run Now
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link href={`/agents/${agentId}/tasks`}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Create Task
          </Link>
        </Button>
      </div>

      {/* Description */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <h2 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Description</h2>
        <p className="text-sm text-[var(--text-muted)]">
          {agent.description || 'No description provided.'}
        </p>
      </Card>

      {/* Draft Version Info */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Current Draft</h2>
          <Button variant="outline" size="sm" asChild>
            <Link href={`/agents/${agentId}/edit`}>
              <Pencil className="mr-1.5 h-3.5 w-3.5" />
              Edit Draft
            </Link>
          </Button>
        </div>
        {draftVersion ? (
          <div className="mt-3 flex items-center gap-3 text-sm text-[var(--text-muted)]">
            <Badge variant="outline">{draftVersion.definition_kind}</Badge>
            <span>Version {draftVersion.version_number}</span>
            <Badge variant="secondary">{draftVersion.status}</Badge>
          </div>
        ) : (
          <p className="mt-3 text-sm text-[var(--text-muted)]">No draft version yet.</p>
        )}
      </Card>

      {/* Active Release */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <h2 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">Active Release</h2>
        {agent.active_release_id ? (
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <Rocket className="h-4 w-4" />
            <span>Release {agent.active_release_id}</span>
          </div>
        ) : (
          <p className="text-sm text-[var(--text-muted)]">No active release.</p>
        )}
      </Card>

      {/* Recent Runs */}
      <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">Recent Runs</h2>
          <Button variant="ghost" size="sm" asChild>
            <Link href={`/agents/${agentId}/runs`}>View All</Link>
          </Button>
        </div>
        {recentRuns.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">No runs yet.</p>
        ) : (
          <div className="space-y-2">
            {recentRuns.map((run) => (
              <Link
                key={run.id}
                href={`/runs`}
                className="block rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-colors hover:bg-[var(--surface-3)]"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className={RUN_STATUS_STYLES[run.status]}>
                        {run.status}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {run.trigger_source}
                      </Badge>
                    </div>
                    {run.goal && (
                      <p className="mt-1 truncate text-xs text-[var(--text-primary)]">{run.goal}</p>
                    )}
                  </div>
                  <span className="shrink-0 text-xs text-[var(--text-muted)]">
                    {formatDateTime(run.started_at)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </Card>

      {/* Quick Links */}
      <div className="flex flex-wrap gap-3">
        <Button variant="outline" size="sm" asChild>
          <Link href={`/agents/${agentId}/versions`}>
            <GitBranch className="mr-1.5 h-3.5 w-3.5" />
            Versions
          </Link>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link href={`/agents/${agentId}/tasks`}>
            <Target className="mr-1.5 h-3.5 w-3.5" />
            Tasks
          </Link>
        </Button>
        <Button variant="outline" size="sm" asChild>
          <Link href={`/agents/${agentId}/runs`}>
            <Activity className="mr-1.5 h-3.5 w-3.5" />
            Runs
          </Link>
        </Button>
      </div>
    </div>
  )
}
