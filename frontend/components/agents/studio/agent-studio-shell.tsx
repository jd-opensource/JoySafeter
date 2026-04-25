'use client'

import { useCallback } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { AgentBuildShell } from '@/components/agents/agent-build/agent-build-shell'
import { AgentReleaseStage } from '@/components/agents/agent-build/agent-release-stage'
import { AgentUsageStage } from '@/components/agents/agent-build/agent-usage-stage'
import { useCurrentWorkspace } from '@/providers/workspace-provider'
import type { Agent } from '@/types/agent'

import { StudioBriefStage } from './studio-brief-stage'
import { StudioCanvasStage } from './studio-canvas-stage'
import { StudioTestLabStage } from './studio-test-lab-stage'
import {
  AGENT_STUDIO_STAGES,
  normalizeStudioStage,
  type AgentStudioStage,
} from './studio-types'

interface AgentStudioShellProps {
  agent: Agent
  initialStage?: string | null
  nodesCount: number
  hasPendingChanges?: boolean
}

export function AgentStudioShell({
  agent,
  initialStage,
  nodesCount,
  hasPendingChanges = false,
}: AgentStudioShellProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { workspaceId } = useCurrentWorkspace()
  const stageContext = { nodesCount, hasActiveRelease: Boolean(agent.active_release_id) }
  const defaultStage = normalizeStudioStage(initialStage, stageContext)

  const handleGenerateFromBrief = useCallback(
    (prompt: string) => {
      const params = new URLSearchParams(searchParams.toString())
      params.set('stage', 'canvas')
      params.set('copilotInput', prompt)
      router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
    },
    [agent.id, router, searchParams],
  )

  return (
    <AgentBuildShell
      agent={agent}
      stages={AGENT_STUDIO_STAGES}
      initialStage={initialStage}
      defaultStage={defaultStage}
      titleKey="agents.studio.visualAgent"
      statusBadges={[
        {
          label:
            nodesCount === 0
              ? 'agents.studio.status.emptyDraft'
              : hasPendingChanges
                ? 'agents.studio.status.unsavedDraft'
                : 'agents.studio.status.savedDraft',
          variant: 'outline',
        },
        {
          label: agent.active_release_id
            ? 'agents.studio.status.published'
            : 'agents.studio.status.notPublished',
          variant: agent.active_release_id ? 'default' : 'outline',
        },
      ]}
      renderStage={(stage, navigateToStage) => {
        const activeStage = stage.id as AgentStudioStage

        return (
          <>
            {activeStage === 'brief' && (
              <StudioBriefStage
                agent={agent}
                onGenerate={handleGenerateFromBrief}
                onSkipToCanvas={() => navigateToStage('canvas')}
              />
            )}
            {activeStage === 'canvas' && (
              <StudioCanvasStage
                agentId={agent.id}
                workspaceId={workspaceId}
                versionId={agent.current_draft_version_id || undefined}
                onOpenTestLab={() => navigateToStage('test-lab')}
                onOpenRelease={() => navigateToStage('release')}
              />
            )}
            {activeStage === 'test-lab' && (
              <StudioTestLabStage
                agentId={agent.id}
                onOpenCanvas={() => navigateToStage('canvas')}
                onOpenRelease={() => navigateToStage('release')}
                versionId={agent.current_draft_version_id || undefined}
                workspaceId={workspaceId}
              />
            )}
            {activeStage === 'release' && (
              <AgentReleaseStage
                agent={agent}
                canPublishDraft={nodesCount > 0}
                versionId={agent.current_draft_version_id || undefined}
                workspaceId={workspaceId}
                runtimeKind="graph"
              />
            )}
            {activeStage === 'usage' && (
              <AgentUsageStage agent={agent} workspaceId={workspaceId} />
            )}
          </>
        )
      }}
    />
  )
}
