'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { useTranslation } from '@/lib/i18n'
import { useProjectContext } from '@/hooks/managed/use-project-context'
import type { Agent, AgentVersion } from '@/types/agent'

import {
  BUILD_STAGES,
  isBuildStageId,
  resolveDefaultStage,
  type BuildStageId,
} from './agent-build-types'
import { BuildStepper } from './build-stepper'
import { useBuilderSurface } from './builder-surface-context'
import { StageRenderer } from './stage-renderer'

interface AgentBuildShellProps {
  agent: Agent
  version: AgentVersion | null
}

export function AgentBuildShell({ agent, version }: AgentBuildShellProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const surface = useBuilderSurface()
  const { projectId } = useProjectContext()
  const activeStageId = (() => {
    const urlStage = searchParams.get('stage')
    if (urlStage && isBuildStageId(urlStage)) return urlStage
    return resolveDefaultStage(agent, version)
  })()

  useEffect(() => {
    const urlStage = searchParams.get('stage')
    if (!urlStage) {
      const defaultStage = resolveDefaultStage(agent, version)
      const params = new URLSearchParams(searchParams.toString())
      params.set('stage', defaultStage)
      router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
    }
  }, [agent.id, router, searchParams, version])

  const navigateToStage = useCallback(
    (stageId: BuildStageId) => {
      const params = new URLSearchParams(searchParams.toString())
      params.set('stage', stageId)
      router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
    },
    [agent.id, router, searchParams],
  )

  const stageProps = {
    agent,
    version,
    projectId: projectId,
    navigateToStage,
  }

  return (
    <div className="flex h-full flex-col">
      <main className="min-h-0 flex-1 overflow-hidden">
        <StageRenderer stageId={activeStageId} surface={surface} stageProps={stageProps} />
      </main>
    </div>
  )
}
