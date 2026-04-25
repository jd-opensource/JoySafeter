import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AgentReleaseStage } from '../agent-release-stage'
import { AgentUsageStage } from '../agent-usage-stage'
import type { Agent } from '@/types/agent'

const tMock = vi.hoisted(() => vi.fn((_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key))

const releases = vi.hoisted(() => ({
  items: [
    {
      id: 'release-1',
      agent_version_id: 'version-1',
      release_number: 1,
      status: 'ready' as const,
      runtime_kind: 'graph' as const,
      builder_kind: null,
      executable_ref: null,
      runtime_binding: {},
      published_by: null,
      published_at: '2026-04-25T00:00:00.000Z',
      retired_at: null,
    },
  ],
}))

const publishMock = vi.hoisted(() => vi.fn())

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/hooks/queries/agents', () => ({
  agentKeys: {
    detail: () => ['agent-detail'],
  },
}))

vi.mock('@/hooks/queries/agentReleases', () => ({
  releaseKeys: {
    all: () => ['releases'],
  },
  useReleases: () => ({ data: releases.items, isLoading: false }),
  useActivateRelease: () => ({ mutate: vi.fn(), isPending: false }),
  useRetireRelease: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/hooks/queries/agentVersions', () => ({
  versionKeys: {
    all: () => ['versions'],
  },
}))

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: tMock,
  }),
}))

vi.mock('@/providers/workspace-permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canAdmin: true }),
}))

vi.mock('../agent-release-adapter', () => ({
  agentReleaseAdapter: { publish: publishMock },
}))

vi.mock('../agent-api-access-dialog', () => ({
  AgentApiAccessDialog: ({ open }: { open: boolean }) => (
    <div data-testid="api-access-dialog">{open ? 'open' : 'closed'}</div>
  ),
}))

const agent: Agent = {
  id: 'agent-1',
  workspace_id: 'workspace-1',
  name: 'Reusable Agent',
  slug: 'reusable-agent',
  description: null,
  avatar: null,
  status: 'draft',
  current_draft_version_id: 'version-1',
  active_release_id: 'release-1',
  created_by: 'user-1',
  created_at: '2026-04-25T00:00:00.000Z',
  updated_at: '2026-04-25T00:00:00.000Z',
}

describe('Agent build reusable stages', () => {
  beforeEach(() => {
    tMock.mockClear()
    publishMock.mockReset()
  })

  it('renders release management without depending on the Visual Studio wrapper', () => {
    render(
      <AgentReleaseStage
        agent={agent}
        canPublishDraft
        versionId="version-1"
        workspaceId="workspace-1"
        runtimeKind="graph"
      />,
    )

    expect(screen.getByRole('heading', { name: 'Publish and manage releases' })).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(tMock).toHaveBeenCalledWith(
      'agents.build.release.title',
      expect.objectContaining({ defaultValue: 'Publish and manage releases' }),
    )
  })

  it('can publish non-visual runtimes without requiring graph nodes', async () => {
    const user = userEvent.setup()
    publishMock.mockResolvedValue({ id: 'release-2', version: 2, status: 'ready' })

    render(
      <AgentReleaseStage
        agent={agent}
        canPublishDraft
        versionId="version-1"
        workspaceId="workspace-1"
        runtimeKind="code"
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Publish Draft' }))

    expect(publishMock).toHaveBeenCalledWith('agent-1', 'version-1', 'workspace-1', 'code')
  })

  it('renders usage entry points without depending on the Visual Studio wrapper', () => {
    render(<AgentUsageStage agent={agent} workspaceId="workspace-1" />)

    expect(screen.getByRole('heading', { name: 'Use this Agent in business scenarios' })).toBeInTheDocument()
    expect(screen.getByText('Chat')).toBeInTheDocument()
    expect(screen.getByText('Tasks and workflows')).toBeInTheDocument()
    expect(screen.getByText('API Access')).toBeInTheDocument()
    expect(tMock).toHaveBeenCalledWith(
      'agents.build.usage.title',
      expect.objectContaining({ defaultValue: 'Use this Agent in business scenarios' }),
    )
  })
})
