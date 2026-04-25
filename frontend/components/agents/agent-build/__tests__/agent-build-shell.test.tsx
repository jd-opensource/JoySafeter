import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FileText, Rocket } from 'lucide-react'

import { AgentBuildShell } from '../agent-build-shell'
import type { AgentBuildStageConfig } from '../agent-build-types'
import type { Agent } from '@/types/agent'

const replaceMock = vi.fn()
let searchParams = new URLSearchParams()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => searchParams,
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key,
  }),
}))

const stages: readonly AgentBuildStageConfig[] = [
  {
    id: 'brief',
    labelKey: 'Brief',
    descriptionKey: 'Describe',
    icon: FileText,
    primaryActionKey: 'Open Build',
  },
  {
    id: 'release',
    labelKey: 'Release',
    descriptionKey: 'Publish',
    icon: Rocket,
    primaryActionKey: 'Open Usage',
  },
]

const agent: Agent = {
  id: 'agent-1',
  workspace_id: 'workspace-1',
  name: 'Lifecycle Agent',
  slug: 'lifecycle-agent',
  description: null,
  avatar: null,
  status: 'draft',
  current_draft_version_id: 'version-1',
  active_release_id: null,
  created_by: 'user-1',
  created_at: '2026-04-25T00:00:00.000Z',
  updated_at: '2026-04-25T00:00:00.000Z',
}

describe('AgentBuildShell', () => {
  beforeEach(() => {
    replaceMock.mockClear()
    searchParams = new URLSearchParams()
  })

  it('renders configured lifecycle stages without assuming a visual builder', () => {
    render(
      <AgentBuildShell
        agent={agent}
        stages={stages}
        initialStage="brief"
        defaultStage="brief"
        titleKey="Agent Builder"
        statusBadges={['Draft']}
        renderStage={(stage) => <div data-testid="stage">{stage.id}</div>}
      />,
    )

    expect(screen.getByRole('button', { name: /Brief/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Release/ })).toBeInTheDocument()
    expect(screen.getByTestId('stage')).toHaveTextContent('brief')
    expect(screen.getByText('Draft')).toBeInTheDocument()
  })

  it('syncs stage changes to the URL and preserves unrelated query params', async () => {
    searchParams = new URLSearchParams('invite=abc123')
    const user = userEvent.setup()

    render(
      <AgentBuildShell
        agent={agent}
        stages={stages}
        initialStage="brief"
        defaultStage="brief"
        titleKey="Agent Builder"
        statusBadges={[]}
        renderStage={(stage) => <div data-testid="stage">{stage.id}</div>}
      />,
    )

    await user.click(screen.getByRole('button', { name: /Release/ }))

    expect(screen.getByTestId('stage')).toHaveTextContent('release')
    expect(replaceMock).toHaveBeenCalledWith('/agents/agent-1?invite=abc123&stage=release', {
      scroll: false,
    })
  })
})
