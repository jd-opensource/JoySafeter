import { describe, expect, it, vi, beforeEach } from 'vitest'

const apiPost = vi.fn()

vi.mock('@/lib/api-client', () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
}))

import { draftCopilotService } from '../draftCopilotService'

describe('draftCopilotService.dispatchRun', () => {
  beforeEach(() => {
    apiPost.mockReset()
  })

  it('sends draft identifiers with the copilot run request', async () => {
    apiPost.mockResolvedValue({ run_id: 'run-1', execution_id: 'exec-1' })

    await draftCopilotService.dispatchRun({
      agentId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
      prompt: 'Add a node',
      graphContext: { nodes: [] },
      conversationHistory: [],
      mode: 'deepagents',
    })

    expect(apiPost).toHaveBeenCalledWith('copilot/run', {
      agent_id: 'agent-1',
      version_id: 'version-1',
      workspace_id: 'workspace-1',
      prompt: 'Add a node',
      graph_context: { nodes: [] },
      conversation_history: [],
      mode: 'deepagents',
      provider_name: undefined,
      model_name: undefined,
    })
  })
})
