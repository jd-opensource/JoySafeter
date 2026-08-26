import { cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ORGANIZATION_ID, OTHER_ORGANIZATION_ID } from '@/test-utils/entity-ids'

const managedGet = vi.fn()
let pathname = `/managed/settings/organizations/${OTHER_ORGANIZATION_ID}/members`
let currentOrgId = ORGANIZATION_ID
let organization = {
  id: OTHER_ORGANIZATION_ID,
  name: 'Organization B',
  slug: 'organization-b',
  role: 'admin',
  owner_name: 'Workspace Owner',
  owner_email: 'owner@example.com',
  project_creation_policy: 'admins_only' as const,
  created_at: '2026-08-01T00:00:00Z',
}

vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: { queryFn: () => unknown }) => {
    void options.queryFn()
    return { data: organization, isLoading: false }
  },
}))

vi.mock('@/lib/api-client', () => ({ managedGet }))

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

vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: (selector: (state: { currentOrgId: string }) => unknown) =>
    selector({ currentOrgId }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('OrganizationDetailShell', () => {
  afterEach(() => {
    cleanup()
    managedGet.mockClear()
    pathname = `/managed/settings/organizations/${OTHER_ORGANIZATION_ID}/members`
    currentOrgId = ORGANIZATION_ID
    organization = {
      id: OTHER_ORGANIZATION_ID,
      name: 'Organization B',
      slug: 'organization-b',
      role: 'admin',
      owner_name: 'Workspace Owner',
      owner_email: 'owner@example.com',
      project_creation_policy: 'admins_only',
      created_at: '2026-08-01T00:00:00Z',
    }
  })

  it('identifies the route organization without changing active context', async () => {
    managedGet.mockResolvedValue(organization)
    const { OrganizationDetailShell } = await import('./organization-detail-shell')
    const view = render(
      <OrganizationDetailShell organizationId={OTHER_ORGANIZATION_ID}>
        <div>organization-content</div>
      </OrganizationDetailShell>,
    )

    expect(managedGet).toHaveBeenCalledWith(`organizations/${OTHER_ORGANIZATION_ID}`)
    expect(view.getByText('Organization B')).toBeTruthy()
    expect(view.getByText('manage.organization.detail.role.admin')).toBeTruthy()
    expect(view.getByText(/Workspace Owner/)).toBeTruthy()
    expect(view.queryByText('manage.organization.current')).toBeNull()
    expect(view.getByText('organization-content')).toBeTruthy()

    expect(
      view
        .getByText('manage.organization.detail.backToOrganizations')
        .closest('a')
        ?.getAttribute('href'),
    ).toBe('/managed/settings')
    expect(
      view.getByText('manage.organization.detail.tabs.overview').closest('a')?.getAttribute('href'),
    ).toBe(`/managed/settings/organizations/${OTHER_ORGANIZATION_ID}`)
    const membersTab = view.getByText('manage.organization.detail.tabs.members').closest('a')
    expect(membersTab?.getAttribute('href')).toBe(
      `/managed/settings/organizations/${OTHER_ORGANIZATION_ID}/members`,
    )
    expect(membersTab?.getAttribute('aria-current')).toBe('page')
  })

  it('marks the active organization and explains read-only access', async () => {
    currentOrgId = OTHER_ORGANIZATION_ID
    pathname = `/managed/settings/organizations/${OTHER_ORGANIZATION_ID}`
    organization = { ...organization, role: 'member' }
    managedGet.mockResolvedValue(organization)
    const { OrganizationDetailShell } = await import('./organization-detail-shell')
    const view = render(
      <OrganizationDetailShell organizationId={OTHER_ORGANIZATION_ID}>
        <div>organization-content</div>
      </OrganizationDetailShell>,
    )

    expect(view.getByText('manage.organization.current')).toBeTruthy()
    expect(view.getByText('manage.organization.detail.role.member')).toBeTruthy()
    expect(view.getByText('manage.organization.detail.readOnly')).toBeTruthy()
    expect(
      view
        .getByText('manage.organization.detail.tabs.overview')
        .closest('a')
        ?.getAttribute('aria-current'),
    ).toBe('page')
  })
})
