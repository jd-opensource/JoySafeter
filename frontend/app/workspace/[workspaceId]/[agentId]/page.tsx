'use client'

import { useParams } from 'next/navigation'

import AgentBuilder from './AgentBuilder'

/**
 * Agent 详情页
 *
 * 这是 agent 的主页面，用于显示和编辑 agent 配置
 *
 * 路由: /workspace/[workspaceId]/[agentId]
 */
export default function AgentPage() {
  const params = useParams()
  const agentId = params.agentId as string

  return <AgentBuilder key={agentId} />
}
