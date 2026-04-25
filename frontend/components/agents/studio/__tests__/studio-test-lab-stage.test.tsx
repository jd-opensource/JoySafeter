import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { StudioTestLabStage } from '../studio-test-lab-stage'

const startExecutionMock = vi.fn()
const startDraftExecutionMock = vi.fn()
const stopExecutionMock = vi.fn()
const togglePanelMock = vi.fn()
const setCurrentGraphIdMock = vi.fn()
const setBuilderStateMock = vi.fn()

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key,
  }),
}))

vi.mock('@/components/editors/graph-builder/stores/builderStore', () => ({
  useBuilderStore: {
    setState: (...args: unknown[]) => setBuilderStateMock(...args),
  },
}))

vi.mock('@/components/editors/graph-builder/stores/execution/executionStore', () => ({
  useExecutionStore: () => ({
    isExecuting: false,
    setCurrentGraphId: setCurrentGraphIdMock,
    startExecution: startExecutionMock,
    startDraftExecution: startDraftExecutionMock,
    stopExecution: stopExecutionMock,
    togglePanel: togglePanelMock,
  }),
}))

vi.mock('@/components/execution/ExecutionPanelNew', () => ({
  ExecutionPanelNew: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="execution-panel">{embedded ? 'embedded' : 'dock'}</div>
  ),
}))

describe('StudioTestLabStage', () => {
  beforeEach(() => {
    startExecutionMock.mockReset()
    startDraftExecutionMock.mockReset()
    stopExecutionMock.mockReset()
    togglePanelMock.mockReset()
    setCurrentGraphIdMock.mockReset()
    setBuilderStateMock.mockReset()
  })

  it('runs the current draft version instead of the active release execution path', async () => {
    startDraftExecutionMock.mockResolvedValue(undefined)

    render(
      <StudioTestLabStage
        agentId="agent-1"
        versionId="version-1"
        workspaceId="workspace-1"
        onOpenCanvas={vi.fn()}
        onOpenRelease={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByPlaceholderText('Enter a sample request for this draft...'), {
      target: { value: 'hello draft' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Run Draft' }))

    await waitFor(() =>
      expect(startDraftExecutionMock).toHaveBeenCalledWith({
        agentId: 'agent-1',
        versionId: 'version-1',
        workspaceId: 'workspace-1',
        input: 'hello draft',
      }),
    )
    expect(startExecutionMock).not.toHaveBeenCalled()
    expect(togglePanelMock).not.toHaveBeenCalled()
  })
})
