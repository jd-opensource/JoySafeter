import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AgentStudioShell } from '../agent-studio-shell'
import type { Agent } from '@/types/agent'

const replaceMock = vi.fn()
let searchParams = new URLSearchParams()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    replace: replaceMock,
  }),
  useSearchParams: () => searchParams,
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@/providers/workspace-provider', () => ({
  useCurrentWorkspace: () => ({ workspaceId: 'workspace-1' }),
}))

vi.mock('../studio-canvas-stage', () => ({
  StudioCanvasStage: ({
    agentId,
    workspaceId,
    onOpenTestLab,
  }: {
    agentId: string
    workspaceId: string
    onOpenTestLab: () => void
  }) => (
    <div data-testid="studio-canvas-stage">
      Canvas {agentId} {workspaceId}
      <button type="button" onClick={onOpenTestLab}>
        Open Test Lab
      </button>
    </div>
  ),
}))

vi.mock('../studio-test-lab-stage', () => ({
  StudioTestLabStage: ({
    onOpenCanvas,
    onOpenRelease,
  }: {
    onOpenCanvas: () => void
    onOpenRelease: () => void
  }) => (
    <div data-testid="studio-test-lab-stage">
      Test Lab Stage
      <button type="button" onClick={onOpenCanvas}>
        Back to Canvas
      </button>
      <button type="button" onClick={onOpenRelease}>
        Open Release
      </button>
    </div>
  ),
}))

const agent: Agent = {
  id: 'agent-1',
  workspace_id: 'workspace-1',
  name: 'Test Agent',
  slug: 'test-agent',
  description: null,
  avatar: null,
  status: 'draft',
  current_draft_version_id: 'version-1',
  active_release_id: null,
  created_by: 'user-1',
  created_at: '2026-04-25T00:00:00.000Z',
  updated_at: '2026-04-25T00:00:00.000Z',
}

describe('AgentStudioShell', () => {
  beforeEach(() => {
    replaceMock.mockClear()
    searchParams = new URLSearchParams()
  })

  it('syncs the active stage when the route-provided initial stage changes', () => {
    const { rerender } = render(
      <AgentStudioShell agent={agent} initialStage="brief" nodesCount={1} />,
    )

    expect(screen.getByRole('heading', { name: 'agents.studio.brief.title' })).toBeInTheDocument()

    rerender(<AgentStudioShell agent={agent} initialStage="canvas" nodesCount={1} />)

    expect(screen.getByTestId('studio-canvas-stage')).toHaveTextContent('Canvas agent-1 workspace-1')
  })

  it('does not reset local stage changes when no route-provided initial stage exists', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<AgentStudioShell agent={agent} nodesCount={0} />)

    await user.click(screen.getByRole('button', { name: /agents\.studio\.stages\.canvas/ }))

    rerender(<AgentStudioShell agent={agent} nodesCount={0} />)

    expect(screen.getByTestId('studio-canvas-stage')).toBeInTheDocument()
  })

  it('persists manual canvas navigation to the URL', async () => {
    const user = userEvent.setup()
    render(<AgentStudioShell agent={agent} nodesCount={0} />)

    await user.click(screen.getByRole('button', { name: /agents\.studio\.stages\.canvas/ }))

    expect(replaceMock).toHaveBeenCalledWith('/agents/agent-1?stage=canvas', { scroll: false })
  })

  it('preserves unrelated query params when persisting stage navigation', async () => {
    searchParams = new URLSearchParams('invite=abc123&stage=brief')
    const user = userEvent.setup()
    render(<AgentStudioShell agent={agent} nodesCount={0} />)

    await user.click(screen.getByRole('button', { name: /agents\.studio\.stages\.canvas/ }))

    expect(replaceMock).toHaveBeenCalledWith('/agents/agent-1?invite=abc123&stage=canvas', {
      scroll: false,
    })
  })

  it('persists build-manually navigation to the URL', async () => {
    const user = userEvent.setup()
    render(<AgentStudioShell agent={agent} nodesCount={0} />)

    await user.click(screen.getByRole('button', { name: 'agents.studio.brief.skip' }))

    expect(screen.getByTestId('studio-canvas-stage')).toBeInTheDocument()
    expect(replaceMock).toHaveBeenCalledWith('/agents/agent-1?stage=canvas', { scroll: false })
  })

  it('labels the Brief top-bar primary action as opening the canvas', () => {
    render(<AgentStudioShell agent={agent} initialStage="brief" nodesCount={0} />)

    expect(screen.getByRole('button', { name: 'agents.studio.actions.openCanvas' })).toBeInTheDocument()
  })

  it('preserves unrelated query params when generating from the Brief prompt', async () => {
    searchParams = new URLSearchParams('invite=abc123')
    const user = userEvent.setup()
    render(<AgentStudioShell agent={{ ...agent, description: 'Reach 95% accuracy' }} nodesCount={0} />)

    await user.click(screen.getByRole('button', { name: 'agents.studio.brief.generate' }))

    expect(replaceMock).toHaveBeenCalledTimes(1)
    const [url, options] = replaceMock.mock.calls[0]
    expect(url).toContain('/agents/agent-1?')
    const params = new URLSearchParams(url.split('?')[1])
    expect(params.get('invite')).toBe('abc123')
    expect(params.get('stage')).toBe('canvas')
    expect(params.get('copilotInput')).toContain('Reach 95% accuracy')
    expect(options).toEqual({ scroll: false })
  })

  it('renders the Test Lab stage and keeps its navigation URL-synced', async () => {
    const user = userEvent.setup()
    render(<AgentStudioShell agent={agent} initialStage="test-lab" nodesCount={1} />)

    expect(screen.getByTestId('studio-test-lab-stage')).toBeInTheDocument()
    expect(screen.queryByText('test-lab')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Back to Canvas' }))

    expect(screen.getByTestId('studio-canvas-stage')).toBeInTheDocument()
    expect(replaceMock).toHaveBeenCalledWith('/agents/agent-1?stage=canvas', { scroll: false })
  })

  it('opens Test Lab from the Canvas stage with URL synchronization', async () => {
    const user = userEvent.setup()
    render(<AgentStudioShell agent={agent} initialStage="canvas" nodesCount={1} />)

    await user.click(screen.getByRole('button', { name: 'Open Test Lab' }))

    expect(screen.getByTestId('studio-test-lab-stage')).toBeInTheDocument()
    expect(replaceMock).toHaveBeenCalledWith('/agents/agent-1?stage=test-lab', { scroll: false })
  })

  it('labels the Test Lab top-bar primary action as opening Release', async () => {
    const user = userEvent.setup()
    render(<AgentStudioShell agent={agent} initialStage="test-lab" nodesCount={1} />)

    await user.click(screen.getByRole('button', { name: 'agents.studio.actions.openRelease' }))

    expect(replaceMock).toHaveBeenCalledWith('/agents/agent-1?stage=release', { scroll: false })
  })
})
