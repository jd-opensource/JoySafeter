import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useExecutionStore } from '../executionStore'
import { useBuilderStore } from '../../builderStore'
import { executionAdapter } from '../../../services/executionAdapter'

vi.mock('@/lib/ws/executions/executionWsClient', () => ({
  getExecutionWsClient: () => ({
    subscribe: vi.fn(
      async (
        _executionId: string,
        _afterSeq: number,
        handlers: { onCompleted: (frame: { status: string }) => void },
      ) => {
        handlers.onCompleted({ status: 'succeeded' })
      },
    ),
    unsubscribe: vi.fn(),
  }),
}))

vi.mock('@/services/agentService', () => ({
  agentService: {
    get: vi.fn(),
  },
}))

vi.mock('../../../services/executionAdapter', () => ({
  executionAdapter: {
    startDraftRun: vi.fn(),
    startRun: vi.fn(),
    cancelRun: vi.fn(),
  },
}))

describe('executionStore draft execution', () => {
  beforeEach(() => {
    useExecutionStore.setState({
      contexts: new Map(),
      currentGraphId: null,
      steps: [],
      isExecuting: false,
      showPanel: false,
      activeNodeId: null,
      pendingInterrupts: new Map(),
      currentState: null,
      executionTrace: [],
      routeDecisions: [],
      treeRoots: [],
      treeNodeMap: new Map(),
    })
    useBuilderStore.setState({
      agentId: 'agent-1',
      graphId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
    })
    vi.mocked(executionAdapter.startDraftRun).mockResolvedValue({
      id: 'run-draft',
      current_execution_id: 'exec-draft',
      status: 'running',
    })
    vi.clearAllMocks()
  })

  it('does not open the global execution dock for embedded draft runs', async () => {
    useExecutionStore.getState().setCurrentGraphId('agent-1')

    await useExecutionStore.getState().startDraftExecution({
      agentId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
      input: 'hello draft',
    })

    expect(executionAdapter.startDraftRun).toHaveBeenCalledWith({
      agentId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
      prompt: 'hello draft',
    })
    expect(useExecutionStore.getState().showPanel).toBe(false)
  })
})
