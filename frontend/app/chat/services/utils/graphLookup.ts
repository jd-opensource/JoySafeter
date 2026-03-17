/**
 * Shared graph-lookup utility
 *
 * Eliminates duplicate cache→API→find pattern in mode handlers.
 */

import { agentService } from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { graphKeys } from '@/hooks/queries/graphs'

import type { ModeContext } from '../modeHandlers/types'

/**
 * Look up a graph by name in the user's personal workspace.
 * Tries query cache first, then falls back to API.
 */
export async function findGraphByName(
  graphName: string,
  context: ModeContext
): Promise<{ id: string; name: string } | null> {
  if (!context.personalWorkspaceId) return null

  // 1. Try query cache
  let workspaceGraphs: Array<{ id: string; name: string }> | undefined
  if (context.queryClient.getQueryData) {
    workspaceGraphs = context.queryClient.getQueryData<Array<{ id: string; name: string }>>(
      [...graphKeys.list(context.personalWorkspaceId)]
    )
  }

  // 2. Fallback to API
  if (!workspaceGraphs) {
    try {
      workspaceGraphs = await agentService.listGraphs(context.personalWorkspaceId)
    } catch (error) {
      console.error('Failed to fetch workspace graphs:', error)
      return null
    }
  }

  // 3. Find by name
  return workspaceGraphs?.find((g) => g.name === graphName) ?? null
}

/**
 * Refresh graph list in query cache, then look up by name.
 * Used after creating a graph to verify it now exists.
 */
export async function refreshAndFindGraph(
  graphName: string,
  context: ModeContext
): Promise<{ id: string; name: string } | null> {
  if (!context.personalWorkspaceId) return null

  if (context.queryClient.refetchQueries) {
    await context.queryClient.refetchQueries({
      queryKey: [...graphKeys.list(context.personalWorkspaceId)],
    })
  }

  if (context.queryClient.getQueryData) {
    const queryData = context.queryClient.getQueryData<Array<{ id: string; name: string }>>(
      [...graphKeys.list(context.personalWorkspaceId)]
    )
    return queryData?.find((g) => g.name === graphName) ?? null
  }

  return null
}
