'use client'

import { useParams, useSearchParams } from 'next/navigation'

import { AgentBuilderTab } from '@/components/agents/agent-builder-tab'
import { AgentOverviewTab } from '@/components/agents/agent-overview-tab'
import { AgentChatTab } from '@/components/agents/agent-chat-tab'
import { AgentSettingsTab } from '@/components/agents/agent-settings-tab'

export default function AgentDetailPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const agentId = params.agentId as string

  const tab = searchParams.get('tab') || 'overview'
  const threadId = searchParams.get('thread') || undefined

  switch (tab) {
    case 'builder':
      return <AgentBuilderTab agentId={agentId} />
    case 'chat':
      return <AgentChatTab agentId={agentId} threadId={threadId} />
    case 'settings':
      return <AgentSettingsTab agentId={agentId} />
    default:
      return <AgentOverviewTab agentId={agentId} />
  }
}
