import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AgentStudioShell } from '../agent-studio-shell'
import type { Agent } from '@/types/agent'

const replaceMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    replace: replaceMock,
  }),
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
  StudioCanvasStage: ({ agentId, workspaceId }: { agentId: string; workspaceId: string }) => (
    <div data-testid="studio-canvas-stage">
      Canvas {agentId} {workspaceId}
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
})
