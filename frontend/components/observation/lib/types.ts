export type ObservationType =
  | 'SPAN' | 'EVENT' | 'GENERATION' | 'AGENT' | 'TOOL'
  | 'CHAIN' | 'RETRIEVER' | 'EMBEDDING' | 'EVALUATOR' | 'GUARDRAIL'

export type ObservationLevel = 'DEBUG' | 'DEFAULT' | 'WARNING' | 'ERROR'

export interface ObservationNode {
  id: string
  parentObservationId: string | null
  traceId: string
  type: ObservationType
  name: string
  level: ObservationLevel
  statusMessage: string | null
  startTime: Date
  endTime: Date | null
  completionStartTime: Date | null

  input: unknown
  output: unknown
  metadata: Record<string, unknown> | null

  model?: string
  usageDetails?: Record<string, number>
  costDetails?: Record<string, number>
  calculatedInputCost?: number | null
  calculatedOutputCost?: number | null
  calculatedTotalCost?: number | null
  toolCalls?: Array<{ id: string; name: string; arguments: unknown }>

  children: ObservationNode[]
  depth: number
  childrenDepth: number

  totalCost: number
  inputUsage: number | null
  outputUsage: number | null
  totalUsage: number | null

  latency: number | null
  startTimeSinceTrace: number
  startTimeSinceParentStart: number | null
}

export interface ObservationFlatItem {
  node: ObservationNode
  depth: number
  isLastSibling: boolean
  treeLines: boolean[]
}

export interface TimelineMetrics {
  startOffset: number
  itemWidth: number
  firstTokenTimeOffset?: number
  latency?: number
}

export interface TimelineFlatItem {
  node: ObservationNode
  depth: number
  treeLines: boolean[]
  isLastSibling: boolean
  metrics: TimelineMetrics
}

export interface SearchItem {
  node: ObservationNode
  observationId: string
}

export interface ProcessingNode {
  observation: RawObservation
  childrenIds: string[]
  inDegree: number
  depth: number
  treeNode?: ObservationNode
}

export interface TraceTreeResult {
  roots: ObservationNode[]
  nodeMap: Map<string, ObservationNode>
  searchItems: SearchItem[]
}

export interface RawObservation {
  id: string
  traceId: string
  parentObservationId: string | null
  type: ObservationType
  name: string
  level: ObservationLevel
  statusMessage: string | null
  startTime: string
  endTime: string | null
  completionStartTime: string | null
  input: unknown
  output: unknown
  metadata: Record<string, unknown> | null
  model?: string
  usageDetails?: Record<string, number>
  costDetails?: Record<string, number>
  calculatedInputCost?: number | null
  calculatedOutputCost?: number | null
  calculatedTotalCost?: number | null
}
