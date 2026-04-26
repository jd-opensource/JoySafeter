import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (_: string, o?: { defaultValue?: string }) => o?.defaultValue ?? _ }),
}))
vi.mock('@/providers/workspace-permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canEdit: true, canAdmin: true }),
}))
vi.mock('../../stores/graphStore', () => ({
  useGraphStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ addNode: vi.fn(), past: [], future: [], undo: vi.fn(), redo: vi.fn() }),
}))
vi.mock('../AddNodeButton', () => ({
  AddNodeButton: ({ onAddNode }: { onAddNode: (n: { type: string; label: string }) => void }) => (
    <button onClick={() => onAddNode({ type: 'agent', label: 'Agent' })}>Add</button>
  ),
}))
vi.mock('../ImportExportMenu', () => ({
  ImportExportMenu: () => <div data-testid="import-export-menu" />,
}))

import { GraphToolbar } from '../GraphToolbar'

describe('GraphToolbar', () => {
  it('renders Add button and ImportExportMenu', () => {
    render(<GraphToolbar />)
    expect(screen.getByRole('button', { name: /add/i })).toBeInTheDocument()
    expect(screen.getByTestId('import-export-menu')).toBeInTheDocument()
  })

  it('renders Undo and Redo buttons', () => {
    render(<GraphToolbar />)
    expect(screen.getByRole('button', { name: /undo/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /redo/i })).toBeInTheDocument()
  })

  it('disables Undo when past is empty', () => {
    render(<GraphToolbar />)
    expect(screen.getByRole('button', { name: /undo/i })).toBeDisabled()
  })

  it('disables Redo when future is empty', () => {
    render(<GraphToolbar />)
    expect(screen.getByRole('button', { name: /redo/i })).toBeDisabled()
  })
})
