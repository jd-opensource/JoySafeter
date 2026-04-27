import { renderHook, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AppErrorPayload } from '@/types/agent-run'

const invalidateQueries = vi.fn()

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    invalidateQueries,
  }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))

vi.mock('../stores/graphStore', () => ({
  useGraphStore: {
    getState: () => ({
      versionId: 'version-1',
      workspaceId: 'workspace-1',
    }),
  },
}))

vi.mock('../utils/copilotUtils', () => ({
  hasCurrentMessage: () => true,
}))

import { useCopilotWebSocketHandler } from '../useCopilotWebSocketHandler'

describe('useCopilotWebSocketHandler', () => {
  beforeEach(() => {
    invalidateQueries.mockReset()
  })

  it('maps BUILD_COPILOT_MODEL_REQUIRED to the Build Copilot error message', () => {
    const actions = {
      clearStreaming: vi.fn(),
      finalizeCurrentMessage: vi.fn(),
      clearSession: vi.fn(),
      setLoading: vi.fn(),
      setCurrentStage: vi.fn(),
      setThinkingMessage: vi.fn(),
      appendContent: vi.fn(),
      addThoughtStep: vi.fn(),
      setCurrentToolCall: vi.fn(),
      addToolResult: vi.fn(),
      executeActions: vi.fn(),
    }

    const refs = {
      isMountedRef: { current: true },
      isCreatingSessionRef: { current: true },
    }

    const { result } = renderHook(() =>
      useCopilotWebSocketHandler({
        state: {
          loading: false,
          currentStage: null,
          streamingContent: '',
          messages: [],
        } as any,
        actions: actions as any,
        refs: refs as any,
        graphId: 'graph-1',
      }),
    )

    act(() => {
      const error: AppErrorPayload = {
        code: 'BUILD_COPILOT_MODEL_REQUIRED',
        message: 'Build Copilot has no model configured.',
        data: null,
      }
      result.current.onError(error)
    })

    expect(actions.finalizeCurrentMessage).toHaveBeenCalledWith(
      'Build Copilot has no model configured. Select a model and try again.',
    )
    expect(actions.clearSession).toHaveBeenCalled()
    expect(actions.setLoading).toHaveBeenCalledWith(false)
  })
})
