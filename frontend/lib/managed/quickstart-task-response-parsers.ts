import { isRecord } from '@/lib/managed/quickstart-value-coercion'
import { parseTaskId, type TaskId } from '@/types/entity-id'
import type { PaginatedResponse, QuickstartTaskSummary } from '@/types/managed'

import { parseManagedCursorPage } from './cursor-page'

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
  const page = parseManagedCursorPage<QuickstartTaskSummary, TaskId>(response, {
    parseItem: parseQuickstartTaskSummary,
    parseCursor: parseTaskId,
    responseName: 'Quickstart task page',
  })
  return {
    data: page.items,
    has_more: page.hasMore,
  }
}
