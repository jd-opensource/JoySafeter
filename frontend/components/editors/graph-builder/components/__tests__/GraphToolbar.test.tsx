import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (_: string, o?: { defaultValue?: string }) => o?.defaultValue ?? _ }),
}))
vi.mock('@/providers/workspace-permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canEdit: true, canAdmin: true }),
}))
vi.mock('../../stores/graphStore', () => ({
  useGraphStore: (selector: (s: { addNode: ReturnType<typeof vi.fn> }) => unknown) =>
    selector({ addNode: vi.fn() }),
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
  it('renders Test and Release buttons', () => {
    const onTest = vi.fn()
    const onRelease = vi.fn()
    render(<GraphToolbar onOpenTestLab={onTest} onOpenRelease={onRelease} />)
    expect(screen.getByRole('button', { name: /test/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /release/i })).toBeInTheDocument()
  })

  it('calls onOpenTestLab when Test clicked', () => {
    const onTest = vi.fn()
    render(<GraphToolbar onOpenTestLab={onTest} onOpenRelease={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /test/i }))
    expect(onTest).toHaveBeenCalled()
  })

  it('does not render Test button when callback not provided', () => {
    render(<GraphToolbar />)
    expect(screen.queryByRole('button', { name: /test/i })).not.toBeInTheDocument()
  })

  it('renders ImportExportMenu', () => {
    render(<GraphToolbar />)
    expect(screen.getByTestId('import-export-menu')).toBeInTheDocument()
  })
})
