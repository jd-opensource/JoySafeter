import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AgentStudioShell } from '../agent-studio-shell'
import type { Agent } from '@/types/agent'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, string>) => {
      if (key === 'agents.studio.stageOverview') {
        return `Active: ${values?.activeStage}; Default: ${values?.defaultStage}`
      }

      return key
    },
  }),
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
  it('syncs the active stage when the route-provided initial stage changes', () => {
    const { rerender } = render(
      <AgentStudioShell agent={agent} initialStage="brief" nodesCount={1} />,
    )

    expect(
      screen.getByText(
        'Active: agents.studio.stages.brief; Default: agents.studio.stages.canvas',
      ),
    ).toBeInTheDocument()

    rerender(<AgentStudioShell agent={agent} initialStage="canvas" nodesCount={1} />)

    expect(
      screen.getByText(
        'Active: agents.studio.stages.canvas; Default: agents.studio.stages.canvas',
      ),
    ).toBeInTheDocument()
  })

  it('does not reset local stage changes when no route-provided initial stage exists', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<AgentStudioShell agent={agent} nodesCount={0} />)

    await user.click(screen.getByRole('button', { name: /agents\.studio\.stages\.canvas/ }))

    rerender(<AgentStudioShell agent={agent} nodesCount={0} />)

    expect(
      screen.getByText(
        'Active: agents.studio.stages.canvas; Default: agents.studio.stages.brief',
      ),
    ).toBeInTheDocument()
  })
})
