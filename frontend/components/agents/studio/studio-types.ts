import { Beaker, BriefcaseBusiness, FileText, GitBranch, Rocket, type LucideIcon } from 'lucide-react'

export type StudioStageId = 'brief' | 'canvas' | 'test-lab' | 'release' | 'usage'

export interface StudioStage {
  id: StudioStageId
  i18nKey: 'brief' | 'canvas' | 'testLab' | 'release' | 'usage'
  icon: LucideIcon
}

export interface StudioStageContext {
  nodesCount: number
  hasActiveRelease: boolean
}

export const AGENT_STUDIO_STAGES: readonly StudioStage[] = [
  { id: 'brief', i18nKey: 'brief', icon: FileText },
  { id: 'canvas', i18nKey: 'canvas', icon: GitBranch },
  { id: 'test-lab', i18nKey: 'testLab', icon: Beaker },
  { id: 'release', i18nKey: 'release', icon: Rocket },
  { id: 'usage', i18nKey: 'usage', icon: BriefcaseBusiness },
] as const

const STUDIO_STAGE_IDS = new Set<StudioStageId>(AGENT_STUDIO_STAGES.map((stage) => stage.id))

export function isStudioStage(value: string): value is StudioStageId {
  return STUDIO_STAGE_IDS.has(value as StudioStageId)
}

export function getDefaultStudioStage(context: StudioStageContext): StudioStageId {
  return context.nodesCount > 0 ? 'canvas' : 'brief'
}

export function normalizeStudioStage(
  value: string | null | undefined,
  context: StudioStageContext,
): StudioStageId {
  return value && isStudioStage(value) ? value : getDefaultStudioStage(context)
}
