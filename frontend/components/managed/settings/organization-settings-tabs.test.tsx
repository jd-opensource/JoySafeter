import { cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

let pathname = '/managed/settings'

vi.mock('next/navigation', () => ({
  usePathname: () => pathname,
}))

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('OrganizationSettingsTabs', () => {
  afterEach(() => cleanup())

  it('links organization settings and members with the current route marked', async () => {
    pathname = '/managed/settings/members'
    const { OrganizationSettingsTabs } = await import('./organization-settings-tabs')

    const view = render(<OrganizationSettingsTabs />)

    const organizations = view.getByText('manage.organization.tabs.organizations').closest('a')
    const members = view.getByText('manage.organization.tabs.membersRoles').closest('a')
    expect(organizations?.getAttribute('href')).toBe('/managed/settings')
    expect(members?.getAttribute('href')).toBe('/managed/settings/members')
    expect(organizations?.getAttribute('aria-current')).toBeNull()
    expect(members?.getAttribute('aria-current')).toBe('page')
  })
})
