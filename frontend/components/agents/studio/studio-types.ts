import { Beaker, BriefcaseBusiness, FileText, GitBranch, Rocket, type LucideIcon } from 'lucide-react'

export type AgentStudioStage = 'brief' | 'canvas' | 'test-lab' | 'release' | 'usage'

export interface AgentStudioStageConfig {
  id: AgentStudioStage
  labelKey: string
  descriptionKey: string
  icon: LucideIcon
}

export interface StudioStageContext {
  nodesCount: number
  hasActiveRelease: boolean
}

export const AGENT_STUDIO_STAGES: readonly AgentStudioStageConfig[] = [
  {
    id: 'brief',
    labelKey: 'agents.studio.stages.brief',
    descriptionKey: 'agents.studio.stageDescriptions.brief',
    icon: FileText,
  },
  {
    id: 'canvas',
    labelKey: 'agents.studio.stages.canvas',
    descriptionKey: 'agents.studio.stageDescriptions.canvas',
    icon: GitBranch,
  },
  {
    id: 'test-lab',
    labelKey: 'agents.studio.stages.testLab',
    descriptionKey: 'agents.studio.stageDescriptions.testLab',
    icon: Beaker,
  },
  {
    id: 'release',
    labelKey: 'agents.studio.stages.release',
    descriptionKey: 'agents.studio.stageDescriptions.release',
    icon: Rocket,
  },
  {
    id: 'usage',
    labelKey: 'agents.studio.stages.usage',
    descriptionKey: 'agents.studio.stageDescriptions.usage',
    icon: BriefcaseBusiness,
  },
] as const

const STUDIO_STAGE_IDS = new Set<AgentStudioStage>(AGENT_STUDIO_STAGES.map((stage) => stage.id))

export function isStudioStage(value: string | null | undefined): value is AgentStudioStage {
  return Boolean(value && STUDIO_STAGE_IDS.has(value as AgentStudioStage))
}

export function getDefaultStudioStage(context: StudioStageContext): AgentStudioStage {
  return context.nodesCount > 0 ? 'canvas' : 'brief'
}

export function normalizeStudioStage(
  value: string | null | undefined,
  context: StudioStageContext,
): AgentStudioStage {
  return value && isStudioStage(value) ? value : getDefaultStudioStage(context)
}
