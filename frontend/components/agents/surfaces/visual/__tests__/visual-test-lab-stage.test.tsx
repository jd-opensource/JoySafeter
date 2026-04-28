import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))
vi.mock('@/components/observation/components/DebugPanel', () => ({
  DebugPanel: () => <div data-testid="debug-panel">DebugPanel</div>,
}))

import { VisualTestLabStage } from '../visual-test-lab-stage'

const baseProps = {
  agent: { id: 'a-1', name: 'Test' } as any,
  version: { id: 'v-1', definition_kind: 'graph' } as any,
  workspaceId: 'ws-1',
  navigateToStage: vi.fn(),
}

describe('VisualTestLabStage', () => {
  it('renders header with title and subtitle', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByText('Test the current draft')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Run draft behavior before publishing. These tests do not affect the active release.',
      ),
    ).toBeInTheDocument()
  })

  it('renders DebugPanel', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByTestId('debug-panel')).toBeInTheDocument()
  })

  it('has navigation buttons using navigateToStage', () => {
    render(<VisualTestLabStage {...baseProps} />)
    expect(screen.getByRole('button', { name: /back to build/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /open release/i })).toBeInTheDocument()
  })
})
