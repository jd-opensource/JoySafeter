import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const dispatchRun = vi.fn()
const getGraphContext = vi.fn(() => ({ nodes: [] }))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))

vi.mock('@/services/agentRunService', () => ({
  agentRunService: {
    sendMessage: vi.fn(),
    cancel: vi.fn(),
  },
}))

vi.mock('@/services/draftCopilotService', () => ({
  draftCopilotService: {
    dispatchRun: (...args: unknown[]) => dispatchRun(...args),
  },
}))

vi.mock('../useCopilotState', () => ({}))

vi.mock('../../stores/graphStore', () => ({
  useGraphStore: Object.assign(
    () => ({
      getGraphContext,
    }),
    {
      getState: () => ({
        graphId: 'graph-1',
        agentId: 'agent-1',
        versionId: 'version-1',
        workspaceId: 'workspace-1',
      }),
    },
  ),
}))

import { useCopilotActions } from '../useCopilotActions'

describe('useCopilotActions', () => {
  beforeEach(() => {
    dispatchRun.mockReset()
    dispatchRun.mockResolvedValue({ run_id: 'run-1', execution_id: 'exec-1' })
  })

  it('dispatches the first copilot message against the draft version', async () => {
    const actions = {
      setInput: vi.fn(),
      addMessage: vi.fn(),
      setLoading: vi.fn(),
      clearStreaming: vi.fn(),
      clearSession: vi.fn(),
      setCurrentStage: vi.fn(),
      setThinkingMessage: vi.fn(),
      setSession: vi.fn(),
      finalizeCurrentMessage: vi.fn(),
      removeCurrentMessage: vi.fn(),
      clearMessages: vi.fn(),
      clearExpandedItems: vi.fn(),
    }

    const refs = {
      isMountedRef: { current: true },
      isCreatingSessionRef: { current: false },
      hasProcessedUrlInputRef: { current: false },
    }

    const { result } = renderHook(() =>
      useCopilotActions({
        state: {
          input: '',
          messages: [],
          loading: false,
          currentExecutionId: null,
          currentRunId: null,
        } as any,
        actions: actions as any,
        refs: refs as any,
      }),
    )

    await act(async () => {
      await result.current.handleSendWithInput('Add a node')
    })

    expect(dispatchRun).toHaveBeenCalledWith({
      agentId: 'agent-1',
      versionId: 'version-1',
      workspaceId: 'workspace-1',
      prompt: 'Add a node',
      graphContext: { nodes: [] },
      conversationHistory: [],
      mode: 'deepagents',
      providerName: undefined,
      modelName: undefined,
    })
  })
})
