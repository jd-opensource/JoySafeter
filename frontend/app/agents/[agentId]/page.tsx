'use client'

import { Loader2 } from 'lucide-react'
import { useParams, useSearchParams, useRouter } from 'next/navigation'

import { AgentBuilderTab } from '@/components/agents/agent-builder-tab'
import { AgentOverviewTab } from '@/components/agents/agent-overview-tab'
import { AgentSettingsTab } from '@/components/agents/agent-settings-tab'
import { AgentStudioShell } from '@/components/agents/studio/agent-studio-shell'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { useVersionGraphState } from '@/hooks/queries/agentVersions'
import { useAgent } from '@/hooks/queries/agents'
import { useCurrentWorkspace } from '@/providers/workspace-provider'

export default function AgentDetailPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const router = useRouter()
  const agentId = params.agentId as string
  const tab = searchParams.get('tab')
  const stage = searchParams.get('stage')
  const threadId = searchParams.get('thread') || undefined
  const { workspaceId } = useCurrentWorkspace()

  const { data: agent, isLoading: isAgentLoading } = useAgent(agentId, workspaceId)
  const draftVersionId = agent?.current_draft_version_id || undefined
  const { data: graphStateData, isLoading: isGraphLoading } = useVersionGraphState(
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
        onThreadChange={(id) => router.push(`/agents/${agentId}?tab=chat&thread=${id}`)}
      />
    )
  }

  if (tab === 'settings') {
    return <AgentSettingsTab agentId={agentId} />
  }

  if (tab === 'builder') {
    return <AgentBuilderTab agentId={agentId} />
  }

  if (isAgentLoading || (agent && draftVersionId && isGraphLoading)) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" />
      </div>
    )
  }

  if (!agent) {
    return <AgentOverviewTab agentId={agentId} />
  }

  const isVisualAgent = graphStateData?.definitionKind === 'graph'

  if (isVisualAgent) {
    return (
      <AgentStudioShell
        agent={agent}
        initialStage={stage}
        nodesCount={graphStateData?.nodes?.length ?? 0}
      />
    )
  }

  return <AgentOverviewTab agentId={agentId} />
}
