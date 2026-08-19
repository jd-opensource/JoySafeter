import { render, screen } from '@testing-library/react'

import { CredentialReferences } from './credential-references'

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}))
vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) => (o?.id ?? o?.count ?? k) as string,
  }),
}))

const base = {
  references: [
    { surface: 'agent_model_binding', resourceType: 'agent' as const, id: 'a1', name: '客服机器人' },
    { surface: 'active_session_snapshot', resourceType: 'session' as const, id: 's1', name: null },
  ],
  otherCount: 0,
  canArchive: false,
  canDelete: false,
}

describe('CredentialReferences', () => {
  it('renders each item as a link to its route', () => {
    render(<CredentialReferences data={base} variant="blocker" />)
    expect(screen.getByText('客服机器人').closest('a')).toHaveAttribute('href', '/managed/agents/a1')
    // session with null name → fallback shows the id
    expect(screen.getByText('s1').closest('a')).toHaveAttribute('href', '/managed/sessions/s1')
  })

  it('renders the legacy other-count line but not as a link', () => {
    render(<CredentialReferences data={{ ...base, otherCount: 3 }} variant="blocker" />)
    const other = screen.getByText('3')
    expect(other.closest('a')).toBeNull()
  })

  it('renders nothing when empty', () => {
    const { container } = render(
      <CredentialReferences
        data={{ references: [], otherCount: 0, canArchive: true, canDelete: true }}
        variant="informational"
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
