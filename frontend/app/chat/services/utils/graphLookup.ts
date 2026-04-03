/**
 * Shared graph-lookup utility
 *
 * Eliminates duplicate cache→API→find pattern in mode handlers.
 */

import { agentService } from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { graphKeys } from '@/hooks/queries/graphs'

import type { ModeContext } from '../modeHandlers/types'

/**
 * Fetch a graph template JSON from /data/graph-templates/{templateName}.json
 * and apply its nodes/edges/viewport to the given graph via saveGraphState.
 */
async function applyTemplate(graphId: string, templateName: string): Promise<void> {
  const res = await fetch(`/data/graph-templates/${templateName}.json`)
  if (!res.ok) {
    console.warn(`[graphLookup] Template "${templateName}" not found (${res.status}), skipping`)
    return
  }
  const template = await res.json()
  const nodes = template.nodes ?? []
  if (nodes.length === 0) return

  await agentService.saveGraphState({
    graphId,
    nodes,
    edges: template.edges ?? [],
    viewport: template.viewport,
  })
}

// Module-level promise locks keyed by graph name — prevents concurrent creation across all callers
const creationLocks = new Map<string, Promise<{ id: string; name: string }>>()

/**
 * Look up a graph by name in the user's personal workspace.
 * Tries query cache first, then falls back to API.
 */
export async function findGraphByName(
  graphName: string,
  context: ModeContext,
): Promise<{ id: string; name: string } | null> {
  if (!context.personalWorkspaceId) return null

  // 1. Try query cache
  let workspaceGraphs: Array<{ id: string; name: string }> | undefined
  if (context.queryClient.getQueryData) {
    workspaceGraphs = context.queryClient.getQueryData<Array<{ id: string; name: string }>>([
      ...graphKeys.list(context.personalWorkspaceId),
    ])
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
  context: ModeContext,
): Promise<{ id: string; name: string } | null> {
  if (!context.personalWorkspaceId) return null

  if (context.queryClient.refetchQueries) {
    await context.queryClient.refetchQueries({
      queryKey: [...graphKeys.list(context.personalWorkspaceId)],
    })
  }

  if (context.queryClient.getQueryData) {
    const queryData = context.queryClient.getQueryData<Array<{ id: string; name: string }>>([
      ...graphKeys.list(context.personalWorkspaceId),
    ])
    return queryData?.find((g) => g.name === graphName) ?? null
  }

  return null
}

/**
 * Find an existing graph by name with nodes, or create from template.
 * - If duplicates exist, keeps the one with most nodes and deletes the rest.
 * - If a graph exists but has no nodes, re-applies the template state.
 * - Uses a module-level promise lock keyed by graph name to prevent concurrent creation.
 */
export async function findOrCreateGraphByTemplate(
  graphName: string,
  templateName: string,
  workspaceId: string,
): Promise<{ id: string; name: string }> {
  // If a creation/repair is already in progress for this name, wait for it
  const inflight = creationLocks.get(graphName)
  if (inflight) {
    return inflight
  }

  const promise = (async () => {
    try {
      const graphs = await agentService.listGraphs(workspaceId)
      const matches = graphs.filter((g) => g.name === graphName)

      if (matches.length > 0) {
        // Deduplicate: keep the one with most nodes, delete the rest
        let best = matches[0]
        for (const g of matches) {
          if ((g.nodeCount ?? 0) > (best.nodeCount ?? 0)) best = g
        }
        // Delete duplicates in the background
        for (const g of matches) {
          if (g.id !== best.id) {
            agentService
              .deleteGraph(g.id)
              .catch((e) => console.warn(`Failed to delete duplicate graph ${g.id}:`, e))
          }
        }

        // If the best graph has nodes, use it directly
        if ((best.nodeCount ?? 0) > 0) {
          return { id: best.id, name: best.name }
        }

        // Graph exists but has no nodes — apply template to populate it
        await applyTemplate(best.id, templateName)
        return { id: best.id, name: best.name }
      }

      // No existing graph — create and populate from template
      const created = await agentService.createGraph({
        name: graphName,
        workspaceId,
      })
      await applyTemplate(created.id, templateName)
      return { id: created.id, name: created.name }
    } finally {
      creationLocks.delete(graphName)
    }
  })()

  creationLocks.set(graphName, promise)
  return promise
}
