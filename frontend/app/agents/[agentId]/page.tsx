'use client'

import { FileText, GitBranch, Pencil, Rocket } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAgent } from '@/hooks/queries/agents'
import { useVersion } from '@/hooks/queries/agentVersions'
import { useWorkspaces } from '@/hooks/queries/workspaces'

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

  if (!agent) return null

  return (
    <div className="space-y-6 px-6 py-6">
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

      {/* Quick Links */}
      <div className="flex flex-wrap gap-3">
        <Button variant="outline" size="sm" asChild>
          <Link href={`/agents/${agentId}/versions`}>
            <GitBranch className="mr-1.5 h-3.5 w-3.5" />
            Versions
          </Link>
        </Button>
      </div>
    </div>
  )
}
