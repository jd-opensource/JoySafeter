import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const replaceMock = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))
vi.mock('@/providers/workspace-provider', () => ({
  useCurrentWorkspace: () => ({ workspaceId: 'ws-1' }),
}))

const mockBriefStage = vi.fn(() => <div data-testid="brief-stage">Brief</div>)
const mockBuildStage = vi.fn(() => <div data-testid="build-stage">Build</div>)
const mockTestLabStage = vi.fn(() => <div data-testid="test-lab-stage">TestLab</div>)

vi.mock('../builder-surface-context', () => ({
  useBuilderSurface: () => ({
    BriefStage: mockBriefStage,
    BuildStage: mockBuildStage,
    TestLabStage: mockTestLabStage,
  }),
}))

vi.mock('../agent-release-stage', () => ({
  AgentReleaseStage: () => <div data-testid="release-stage">Release</div>,
}))
vi.mock('../agent-usage-stage', () => ({
  AgentUsageStage: () => <div data-testid="usage-stage">Usage</div>,
}))

import { AgentBuildShell } from '../agent-build-shell'

const baseAgent = {
  id: 'agent-1',
  name: 'Test Agent',
  active_release_id: null,
  status: 'draft',
} as any

describe('AgentBuildShell', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders stepper with 5 stages', () => {
    render(<AgentBuildShell agent={baseAgent} version={null} />)
    const buttons = screen.getAllByRole('button')
    expect(buttons.length).toBeGreaterThanOrEqual(5)
  })

  it('defaults to brief stage when no version', () => {
    render(<AgentBuildShell agent={baseAgent} version={null} />)
    expect(screen.getByTestId('brief-stage')).toBeInTheDocument()
  })

  it('defaults to usage stage when agent has active release', () => {
    const agent = { ...baseAgent, active_release_id: 'rel-1' }
    render(<AgentBuildShell agent={agent} version={null} />)
    expect(screen.getByTestId('usage-stage')).toBeInTheDocument()
  })

  it('navigates to a different stage on click', async () => {
    const user = userEvent.setup()
    render(<AgentBuildShell agent={baseAgent} version={null} />)
    const buttons = screen.getAllByRole('button')
    await user.click(buttons[3]) // release (index 3)
    expect(screen.getByTestId('release-stage')).toBeInTheDocument()
  })
})
