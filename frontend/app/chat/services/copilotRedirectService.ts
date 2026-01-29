/**
 * Copilot Redirect Service
 * 
 * Handles automatic redirect to Copilot logic
 * When autoRedirect is enabled, creates a new Graph and redirects to Copilot page
 */

import { agentService } from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { graphKeys } from '@/hooks/queries'

import type { ModeContext } from './modeHandlers/types'

/**
 * Copilot Redirect Service
 */
class CopilotRedirectService {
  /**
   * Redirect to Copilot
   * 
   * Creates a new Graph and redirects to Copilot page
   * 
   * @param userInput User input
   * @param context Mode context
   * @returns Redirect path, or null if failed
   */
  async redirectToCopilot(
    userInput: string,
    context: ModeContext
  ): Promise<string | null> {
    const { workspaces, t, router, queryClient } = context

    try {
      // 1. Get personal workspace
      const personalWorkspace = workspaces.find((w) => w.type === 'personal')
      if (!personalWorkspace) {
        return null
      }

      const workspaceId = personalWorkspace.id
      const graphName = t('workspace.defaultGraphName', {
        defaultValue: 'New Graph',
      })

      // 2. Create Graph
      const graph = await agentService.createGraph({
        name: graphName,
        description: t('workspace.defaultGraphDescription', {
          defaultValue: 'Default graph created from chat',
        }),
        color: '',
        workspaceId: workspaceId,
      })

      const graphId = graph.id

      // 3. Save Graph state (empty graph)
      await agentService.saveGraphState({
        graphId,
        nodes: [],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      })

      // 4. Refresh Graph list cache
      queryClient.invalidateQueries({ queryKey: [...graphKeys.list(workspaceId)] })

      // 5. Build redirect path
      const encodedInput = encodeURIComponent(userInput)
      const redirectPath = `/workspace/${workspaceId}/${graphId}?copilotInput=${encodedInput}`

      return redirectPath
    } catch (error) {
      console.error('Failed to redirect to copilot:', error)
      return null
    }
  }

  /**
   * Execute redirect
   * 
   * @param userInput User input
   * @param context Mode context
   * @returns Whether the redirect was successful
   */
  async executeRedirect(
    userInput: string,
    context: ModeContext
  ): Promise<boolean> {
    const redirectPath = await this.redirectToCopilot(userInput, context)
    if (redirectPath) {
      context.router.push(redirectPath)
      return true
    }
    return false
  }
}

// Export singleton instance
export const copilotRedirectService = new CopilotRedirectService()

