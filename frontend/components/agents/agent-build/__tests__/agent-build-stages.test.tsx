import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))
vi.mock('@/providers/workspace-permissions-provider', () => ({
  useUserPermissionsContext: () => ({ canAdmin: true }),
}))
vi.mock('@/hooks/queries/agentPublish', () => ({
  publishKeys: { all: () => ['releases'] },
  usePublishAgent: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false }),
  useRollbackAgent: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false }),
  useRetireRelease: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false }),
  useReleaseHistory: () => ({ data: [], isLoading: false }),
}))
vi.mock('@/hooks/queries/agents', () => ({
  agentKeys: { detail: () => ['agent'] },
}))
vi.mock('@/hooks/queries/agentVersions', () => ({
  versionKeys: { all: () => ['versions'] },
}))
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))
vi.mock('../agent-api-access-dialog', () => ({
  AgentApiAccessDialog: () => null,
}))

import { AgentReleaseStage } from '../agent-release-stage'
import { AgentUsageStage } from '../agent-usage-stage'

const baseStageProps = {
  agent: { id: 'a-1', name: 'Test', active_release_id: null } as any,
  version: { id: 'v-1', definition_kind: 'graph', definition_payload: { nodes: [{}] } } as any,
  workspaceId: 'ws-1',
  navigateToStage: vi.fn(),
}

describe('AgentReleaseStage', () => {
  it('renders with StageProps', () => {
    render(<AgentReleaseStage {...baseStageProps} />)
    expect(screen.getByText('Publish your Agent')).toBeInTheDocument()
  })

  it('enables publish when version has content', () => {
    render(<AgentReleaseStage {...baseStageProps} />)
    const publishBtn = screen.getByRole('button', { name: /publish/i })
    expect(publishBtn).not.toBeDisabled()
  })

  it('disables publish when version is null', () => {
    render(<AgentReleaseStage {...baseStageProps} version={null} />)
    const publishBtn = screen.getByRole('button', { name: /publish/i })
    expect(publishBtn).toBeDisabled()
  })
})

describe('AgentUsageStage', () => {
  it('renders with StageProps', () => {
    render(<AgentUsageStage {...baseStageProps} />)
    expect(screen.getByText('Use this Agent in business scenarios')).toBeInTheDocument()
  })
})
