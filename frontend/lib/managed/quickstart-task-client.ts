import { managedGet } from '@/lib/api-client'
import { apiCollectionPath, apiResourceId } from '@/lib/managed/api-paths'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'
import type { SessionId } from '@/types/entity-id'
import type { QuickstartTaskSummary } from '@/types/managed'

import { parseQuickstartTaskPage } from './quickstart-task-response-parsers'

export function quickstartTrialTaskQueryKey(scopeKey: string, sessionId: SessionId | null) {
  return ['quickstart-trial-task', scopeKey, sessionId] as const
}

export async function fetchLatestQuickstartTrialTask(
  sessionId: SessionId,
  requestScope: ManagedRequestScope,
): Promise<QuickstartTaskSummary | null> {
  const response = await managedGet<unknown>(
    apiCollectionPath('tasks', {
      session_id: apiResourceId(sessionId),
      limit: 1,
    }),
    managedRequestOptions(requestScope),
  )
  return parseQuickstartTaskPage(response).data[0] ?? null
}
