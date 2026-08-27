import { render, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { Agent } from '@/types/managed'

import { VersionDiffView } from './version-diff-view'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const agent = (version: number): Agent =>
  ({
    id: 'agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001',
    name: 'Agent',
    engine_kind: 'claude',
    model: null,
    model_credential_id: null,
    version,
    created_at: '2026-08-27T00:00:00Z',
    updated_at: '2026-08-27T00:00:00Z',
  }) as Agent

describe('VersionDiffView', () => {
  it('renders an absent model as a visible dash', () => {
    const view = render(
      <VersionDiffView base={agent(1)} target={agent(2)} baseVersion={1} targetVersion={2} />,
    )
    const heading = view.getByText('managed.agents.model')
    expect(within(heading.closest('section')!).getByText('-')).toBeTruthy()
  })
})
