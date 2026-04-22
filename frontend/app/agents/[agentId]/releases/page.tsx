'use client'

import { useState } from 'react'
import { Loader2, Plus, Rocket, XCircle, CheckCircle2, Clock, AlertTriangle } from 'lucide-react'
import { useParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ReleaseManager } from '@/components/agents/release-manager'
import { useAgent } from '@/hooks/queries/agents'
import { useReleases, useActivateRelease, useRetireRelease } from '@/hooks/queries/agentReleases'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import type { AgentRelease } from '@/types/agent-release'

const STATUS_CONFIG: Record<
  AgentRelease['status'],
  { label: string; variant: 'default' | 'secondary' | 'outline' | 'destructive'; icon: React.ElementType }
> = {
  building: { label: 'Building', variant: 'outline', icon: Clock },
  ready: { label: 'Ready', variant: 'secondary', icon: CheckCircle2 },
  failed: { label: 'Failed', variant: 'destructive', icon: AlertTriangle },
  retired: { label: 'Retired', variant: 'outline', icon: XCircle },
}

const RUNTIME_LABELS: Record<AgentRelease['runtime_kind'], string> = {
  graph: 'Graph',
  sandbox: 'Sandbox',
  hosted: 'Hosted',
  external: 'External',
}

export default function AgentReleasesPage() {
  const params = useParams()
  const agentId = params.agentId as string

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)
  const { data: releases = [], isLoading } = useReleases(agentId, workspaceId)
  const activateMutation = useActivateRelease()
  const retireMutation = useRetireRelease()

  const [publishDialogOpen, setPublishDialogOpen] = useState(false)

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-6 py-6 text-sm text-[var(--text-muted)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading releases...
      </div>
    )
  }

  const sortedReleases = [...releases].sort((a, b) => b.release_number - a.release_number)

  return (
    <div className="space-y-4 px-6 py-6">
      {/* Header with action */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[var(--text-secondary)]">
          Releases ({releases.length})
        </h2>
        <Button size="sm" className="gap-1.5" onClick={() => setPublishDialogOpen(true)}>
          <Plus className="h-3.5 w-3.5" />
          Publish New Release
        </Button>
      </div>

      {/* Empty state */}
      {sortedReleases.length === 0 && (
        <div className="rounded-lg border border-dashed border-[var(--border)] p-8 text-center">
          <Rocket className="mx-auto mb-2 h-8 w-8 text-[var(--text-muted)]" />
          <p className="text-sm text-[var(--text-muted)]">
            No releases yet. Publish a release from a frozen version.
          </p>
        </div>
      )}

      {/* Release list */}
      {sortedReleases.map((release) => {
        const statusCfg = STATUS_CONFIG[release.status]
        const StatusIcon = statusCfg.icon
        const isActive = release.id === agent?.active_release_id
        const canActivate = release.status === 'ready' && !isActive
        const canRetire = release.status === 'ready' || release.status === 'building'

        return (
          <Card
            key={release.id}
            className="flex items-center justify-between border-[var(--border)] bg-[var(--surface-1)] p-4"
          >
            <div className="flex items-center gap-3">
              <StatusIcon className="h-3.5 w-3.5 text-[var(--text-muted)]" />
              <span className="text-sm font-medium text-[var(--text-primary)]">
                #{release.release_number}
              </span>
              <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
              <Badge variant="outline">{RUNTIME_LABELS[release.runtime_kind]}</Badge>
              {isActive && (
                <Badge className="bg-green-600 text-white hover:bg-green-700">Active</Badge>
              )}
              {release.published_at && (
                <span className="text-xs text-[var(--text-muted)]">
                  {new Date(release.published_at).toLocaleDateString()}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2">
              {canActivate && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5 border-green-600 text-green-600 hover:bg-green-50 hover:text-green-700"
                  onClick={() =>
                    activateMutation.mutate({
                      agentId,
                      releaseId: release.id,
                      workspaceId,
                    })
                  }
                  disabled={activateMutation.isPending}
                >
                  {activateMutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  )}
                  Activate
                </Button>
              )}
              {canRetire && !isActive && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={() =>
                    retireMutation.mutate({
                      agentId,
                      releaseId: release.id,
                      workspaceId,
                    })
                  }
                  disabled={retireMutation.isPending}
                >
                  {retireMutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" />
                  )}
                  Retire
                </Button>
              )}
            </div>
          </Card>
        )
      })}

      {/* Publish dialog */}
      <ReleaseManager
        open={publishDialogOpen}
        onOpenChange={setPublishDialogOpen}
        agentId={agentId}
        workspaceId={workspaceId}
      />
    </div>
  )
}
