import { render, screen } from '@testing-library/react'
import type React from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ExecutionPanelNew } from '../ExecutionPanelNew'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key,
  }),
}))

vi.mock('react-resizable-panels', () => ({
  PanelGroup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Panel: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PanelResizeHandle: () => <div />,
}))

vi.mock('@/components/editors/graph-builder/stores/execution/executionStore', () => ({
  useExecutionStore: () => ({
    steps: [],
    isExecuting: false,
    treeRoots: [],
    treeNodeMap: new Map(),
    togglePanel: vi.fn(),
    clear: vi.fn(),
    pendingInterrupts: new Map(),
  }),
}))

vi.mock('@/components/editors/graph-builder/components/InterruptPanel', () => ({
  InterruptPanel: () => <div />,
}))

vi.mock('../ExecutionDetailPanel', () => ({
  ExecutionDetailPanel: () => <div />,
}))

vi.mock('../ExecutionTimeline', () => ({
  ExecutionTimelineView: () => <div />,
}))

vi.mock('../ExecutionTree', () => ({
  ExecutionTree: () => <div />,
}))

describe('ExecutionPanelNew', () => {
  it('does not show the bottom-dock close button when embedded', () => {
    render(<ExecutionPanelNew embedded />)

    expect(screen.queryByRole('button', { name: /Close/i })).not.toBeInTheDocument()
  })
})
