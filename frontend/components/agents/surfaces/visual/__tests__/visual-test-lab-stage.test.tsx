import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))
vi.mock('@/components/editors/graph-builder/stores/graphStore', () => ({
  useGraphStore: { setState: vi.fn() },
}))
vi.mock('@/components/editors/graph-builder/stores/execution/executionStore', () => ({
  useExecutionStore: () => ({
    isExecuting: false,
    setCurrentGraphId: vi.fn(),
    startDraftExecution: vi.fn(),
    stopExecution: vi.fn(),
  }),
}))
vi.mock('@/components/execution/ExecutionPanelNew', () => ({
  ExecutionPanelNew: () => <div data-testid="execution-panel">Execution</div>,
}))

import { VisualTestLabStage } from '../visual-test-lab-stage'

const baseProps = {
  agent: { id: 'a-1', name: 'Test' } as any,
  version: { id: 'v-1', definition_kind: 'graph' } as any,
  workspaceId: 'ws-1',
  navigateToStage: vi.fn(),
}

describe('VisualTestLabStage', () => {
  it('renders test input and run button', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByPlaceholderText(/enter a sample request/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /run draft/i })).toBeInTheDocument()
  })

  it('renders execution panel', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByTestId('execution-panel')).toBeInTheDocument()
  })

  it('has navigation buttons using navigateToStage', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByRole('button', { name: /back to build/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open release/i })).toBeInTheDocument()
  })
})
