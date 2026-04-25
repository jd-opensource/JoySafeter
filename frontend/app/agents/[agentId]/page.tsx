'use client'

import { Loader2 } from 'lucide-react'
import { useParams, useSearchParams, useRouter } from 'next/navigation'

import { AgentBuildShell } from '@/components/agents/agent-build/agent-build-shell'
import { BuilderSurfaceContext } from '@/components/agents/agent-build/builder-surface-context'
import { resolveBuilderSurface } from '@/components/agents/agent-build/builder-surface-registry'
import { AgentSettingsTab } from '@/components/agents/agent-settings-tab'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { useAgent } from '@/hooks/queries/agents'
import { useVersion } from '@/hooks/queries/agentVersions'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

export default function AgentDetailPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const router = useRouter()
  const agentId = params.agentId as string
  const tab = searchParams.get('tab')
  const threadId = searchParams.get('thread') || undefined
  const { workspaceId } = useCurrentWorkspace()

  const { data: agent, isLoading: isAgentLoading } = useAgent(agentId, workspaceId)
  const draftVersionId = agent?.current_draft_version_id || ''
  const { data: version, isLoading: isVersionLoading } = useVersion(
    agentId,
    draftVersionId,
    workspaceId,
    { enabled: Boolean(agent && draftVersionId && workspaceId) },
  )

  if (tab === 'chat') {
    return (
      <ChatPanel
        agentId={agentId}
        workspaceId={workspaceId}
        threadId={threadId}
        onThreadChange={(id) => {
          router.push(`/agents/${agentId}?tab=chat&thread=${id}`)
        }}
      />
    )
  }

  if (tab === 'settings') {
    return <AgentSettingsTab agentId={agentId} />
  }

  if (isAgentLoading || (draftVersionId && isVersionLoading)) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-muted)]">
        Agent not found
      </div>
    )
  }

  const surface = resolveBuilderSurface(version?.definition_kind)

  return (
    <BuilderSurfaceContext.Provider value={surface}>
      <AgentBuildShell agent={agent} version={version ?? null} />
    </BuilderSurfaceContext.Provider>
  )
}
