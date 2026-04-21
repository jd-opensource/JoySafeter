'use client'

import { Lock, Loader2 } from 'lucide-react'
import { useParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAgent } from '@/hooks/queries/agents'
import { useVersions, useFreezeVersion } from '@/hooks/queries/agentVersions'
import { useWorkspaces } from '@/hooks/queries/workspaces'

export default function AgentVersionsPage() {
  const params = useParams()
  const agentId = params.agentId as string

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)
  const { data: versions = [], isLoading } = useVersions(agentId, workspaceId)
  const freezeMutation = useFreezeVersion()

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-6 py-6 text-sm text-[var(--text-muted)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading versions...
      </div>
    )
  }

  if (versions.length === 0) {
    return (
      <div className="px-6 py-6">
        <p className="text-sm text-[var(--text-muted)]">No versions yet.</p>
      </div>
    )
  }

  const sortedVersions = [...versions].sort((a, b) => b.version_number - a.version_number)

  return (
    <div className="space-y-3 px-6 py-6">
      {sortedVersions.map((version) => {
        const isFrozen = version.status === 'frozen'
        const isDraft = version.id === agent?.current_draft_version_id

        return (
          <Card
            key={version.id}
            className="flex items-center justify-between border-[var(--border)] bg-[var(--surface-1)] p-4"
          >
            <div className="flex items-center gap-3">
              {isFrozen && <Lock className="h-3.5 w-3.5 text-[var(--text-muted)]" />}
              <span className="text-sm font-medium text-[var(--text-primary)]">
                v{version.version_number}
              </span>
              <Badge variant="outline">{version.definition_kind}</Badge>
              {isDraft && <Badge variant="default">Current Draft</Badge>}
              {isFrozen && <Badge variant="secondary">Frozen</Badge>}
              <span className="text-xs text-[var(--text-muted)]">
                {new Date(version.created_at).toLocaleDateString()}
              </span>
            </div>

            <div className="flex items-center gap-2">
              {!isFrozen && (
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={() =>
                    freezeMutation.mutate({ agentId, versionId: version.id, workspaceId })
                  }
                  disabled={freezeMutation.isPending}
                >
                  {freezeMutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Lock className="h-3.5 w-3.5" />
                  )}
                  Freeze
                </Button>
              )}
            </div>
          </Card>
        )
      })}
    </div>
  )
}
