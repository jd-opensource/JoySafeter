import {
  Fan, Bot, Wrench, CircleDot, MoveHorizontal,
  Link, Search, Layers3, ShieldCheck, WandSparkles,
} from 'lucide-react'
import type { ObservationType } from './types'
import type { LucideIcon } from 'lucide-react'

export const OBSERVATION_ICON_MAP: Record<ObservationType, LucideIcon> = {
  GENERATION: Fan,
  AGENT: Bot,
  TOOL: Wrench,
  EVENT: CircleDot,
  SPAN: MoveHorizontal,
  CHAIN: Link,
  RETRIEVER: Search,
  EMBEDDING: Layers3,
  GUARDRAIL: ShieldCheck,
  EVALUATOR: WandSparkles,
}

export const OBSERVATION_COLOR_MAP: Record<ObservationType, string> = {
  GENERATION: 'text-muted-magenta',
  AGENT: 'text-purple-600',
  TOOL: 'text-orange-600',
  EVENT: 'text-muted-green',
  SPAN: 'text-muted-blue',
  CHAIN: 'text-pink-600',
  RETRIEVER: 'text-teal-600',
  EMBEDDING: 'text-amber-600',
  GUARDRAIL: 'text-red-600',
  EVALUATOR: 'text-primary-accent',
}
