import type { ReactNode } from 'react'
import { Beaker, BriefcaseBusiness, FileText, Hammer, Rocket, type LucideIcon } from 'lucide-react'
import type { Agent, AgentVersion } from '@/types/agent'

export type BuildStageId = 'brief' | 'build' | 'test-lab' | 'release' | 'usage'

export interface StageProps {
  agent: Agent
  version: AgentVersion | null
  workspaceId: string
  navigateToStage: (stageId: BuildStageId) => void
  onToolbarSlot?: (slot: ReactNode) => void
}

export interface BuilderSurface {
  BriefStage: React.ComponentType<StageProps>
  BuildStage: React.ComponentType<StageProps>
  TestLabStage: React.ComponentType<StageProps>
}

export interface BuildStageConfig {
  id: BuildStageId
  labelKey: string
  descriptionKey: string
  icon: LucideIcon
}

export const BUILD_STAGES: readonly BuildStageConfig[] = [
  { id: 'brief',    labelKey: 'agents.build.stages.brief',   descriptionKey: 'agents.build.stageDescriptions.brief',   icon: FileText },
  { id: 'build',    labelKey: 'agents.build.stages.build',   descriptionKey: 'agents.build.stageDescriptions.build',   icon: Hammer },
  { id: 'test-lab', labelKey: 'agents.build.stages.testLab', descriptionKey: 'agents.build.stageDescriptions.testLab', icon: Beaker },
  { id: 'release',  labelKey: 'agents.build.stages.release', descriptionKey: 'agents.build.stageDescriptions.release', icon: Rocket },
  { id: 'usage',    labelKey: 'agents.build.stages.usage',   descriptionKey: 'agents.build.stageDescriptions.usage',   icon: BriefcaseBusiness },
] as const

const BUILD_STAGE_IDS = new Set<BuildStageId>(BUILD_STAGES.map((s) => s.id))

export function isBuildStageId(value: string | null | undefined): value is BuildStageId {
  return Boolean(value && BUILD_STAGE_IDS.has(value as BuildStageId))
}

export function hasVersionContent(version: AgentVersion): boolean {
  const payload = version.definition_payload
  if (!payload) return false
  const nodes = payload.nodes as unknown[] | undefined
  if (Array.isArray(nodes) && nodes.length > 0) return true
  const code = payload.code_content as string | undefined
  if (code && code.trim().length > 0) return true
  const prompt = payload.prompt as string | undefined
  if (prompt && prompt.trim().length > 0) return true
  return false
}

export function resolveDefaultStage(agent: Agent, version: AgentVersion | null): BuildStageId {
  if (agent.active_release_id) return 'usage'
  if (!version) return 'brief'
  return hasVersionContent(version) ? 'build' : 'brief'
}
