import { parseTaskId } from '@/types/entity-id'
import type { PaginatedResponse, QuickstartTaskSummary } from '@/types/managed'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requiredString(value: Record<string, unknown>, field: string): string {
  const fieldValue = value[field]
  if (typeof fieldValue !== 'string') {
    throw new TypeError(`Expected quickstart task ${field} to be a string`)
  }
  return fieldValue
}

function optionalNullableString(
  value: Record<string, unknown>,
  field: string,
): string | null | undefined {
  const fieldValue = value[field]
  if (fieldValue === undefined || fieldValue === null || typeof fieldValue === 'string') {
    return fieldValue
  }
  throw new TypeError(`Expected quickstart task ${field} to be a string or null`)
}

function parseQuickstartTaskSummary(value: unknown): QuickstartTaskSummary {
  if (!isRecord(value)) {
    throw new TypeError('Expected quickstart task summary to be an object')
  }
  return {
    id: parseTaskId(requiredString(value, 'id')),
    status: requiredString(value, 'status'),
    created_at: requiredString(value, 'created_at'),
    started_at: optionalNullableString(value, 'started_at'),
    completed_at: optionalNullableString(value, 'completed_at'),
    error: optionalNullableString(value, 'error'),
  }
}

export function parseQuickstartTaskPage(
  response: unknown,
): PaginatedResponse<QuickstartTaskSummary> {
  if (!isRecord(response) || !Array.isArray(response.data)) {
    throw new TypeError('Expected quickstart task page with a data array')
  }
  if (response.has_more !== undefined && typeof response.has_more !== 'boolean') {
    throw new TypeError('Expected quickstart task page has_more to be a boolean')
  }
  return {
    data: response.data.map(parseQuickstartTaskSummary),
    has_more: response.has_more,
  }
}
