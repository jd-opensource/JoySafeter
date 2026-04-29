import type { RawObservation } from './types'

export function normalizeObservation(raw: Record<string, unknown>): RawObservation {
  const costDetails = (raw.cost_details ?? raw.costDetails) as Record<string, number> | undefined

  return {
    id: raw.id as string,
    traceId: (raw.trace_id ?? raw.traceId) as string,
    parentObservationId: (raw.parent_observation_id ?? raw.parentObservationId ?? null) as string | null,
    type: (raw.type as RawObservation['type']) ?? 'SPAN',
    name: (raw.name as string) ?? '',
    level: (raw.level as RawObservation['level']) ?? 'DEFAULT',
    statusMessage: (raw.status_message ?? raw.statusMessage ?? null) as string | null,
    startTime: (raw.start_time ?? raw.startTime) as string,
    endTime: (raw.end_time ?? raw.endTime ?? null) as string | null,
    completionStartTime: (raw.completion_start_time ?? raw.completionStartTime ?? null) as string | null,
    input: raw.input ?? null,
    output: raw.output ?? null,
    metadata: (raw.metadata ?? raw.meta ?? null) as Record<string, unknown> | null,
    model: raw.model as string | undefined,
    modelParameters: (raw.model_parameters ?? raw.modelParameters ?? null) as Record<string, unknown> | null,
    usageDetails: (raw.usage_details ?? raw.usageDetails) as Record<string, number> | undefined,
    costDetails,
    calculatedInputCost: (raw.calculatedInputCost ?? costDetails?.input ?? null) as number | null,
    calculatedOutputCost: (raw.calculatedOutputCost ?? costDetails?.output ?? null) as number | null,
    calculatedTotalCost: (raw.calculatedTotalCost ?? costDetails?.total ?? null) as number | null,
    environment: (raw.environment ?? null) as string | null,
    promptName: (raw.prompt_name ?? raw.promptName ?? null) as string | null,
    promptVersion: (raw.prompt_version ?? raw.promptVersion ?? null) as number | null,
  }
}
