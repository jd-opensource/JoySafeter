import { cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const switchProject = vi.fn(async () => undefined)
let pathname = '/managed/projects/project-b/access'
let activeProjectId = 'project-a'

const projects = [
  {
    id: 'project-a',
    org_id: 'org-a',
    name: 'Project A',
    slug: 'project-a',
    is_default: false,
    capability: 'write',
  },
  {
    id: 'project-b',
    org_id: 'org-a',
    name: 'Project B',
    slug: 'project-b',
    is_default: true,
    archived_at: '2026-08-01T00:00:00Z',
    capability: 'admin',
  },
]
let routeProject = projects[1]

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: routeProject, isLoading: false }),
}))

vi.mock('@/lib/api-client', () => ({ managedGet: vi.fn() }))

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

vi.mock('@/hooks/managed/use-project-context', () => ({
  useProjectContext: () => ({
    orgId: 'org-a',
    projectId: activeProjectId,
    organizations: [{ id: 'org-a', name: 'Organization A', slug: 'org-a', role: 'owner' }],
    isLoading: false,
    switchProject,
  }),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('ProjectSettingsShell', () => {
  afterEach(() => {
    cleanup()
    switchProject.mockClear()
    activeProjectId = 'project-a'
    pathname = '/managed/projects/project-b/access'
    routeProject = projects[1]
  })

  it('renders the route project without switching the active work context', async () => {
    const { ProjectSettingsShell } = await import('./project-settings-shell')
    const view = render(
      <ProjectSettingsShell projectId="project-b">
        <div>route-content</div>
      </ProjectSettingsShell>,
    )

    expect(view.getByText('route-content')).toBeTruthy()
    expect(switchProject).not.toHaveBeenCalled()
    expect(view.getByText('Organization A')).toBeTruthy()
    expect(view.getByText('Project B')).toBeTruthy()
    expect(view.getByText('managed.projectSettings.capability.admin')).toBeTruthy()
    expect(view.getByText('managed.projectSettings.default')).toBeTruthy()
    expect(view.getByText('managed.projectSettings.archived')).toBeTruthy()

    const accessTab = view.getByText('managed.projectSettings.tabs.access').closest('a')
    expect(accessTab?.getAttribute('href')).toBe('/managed/projects/project-b/access')
    expect(accessTab?.getAttribute('aria-current')).toBe('page')
  })

  it('keeps view-only projects on overview and hides management tabs', async () => {
    routeProject = projects[0]
    pathname = '/managed/projects/project-a/tokens'
    const { ProjectSettingsShell } = await import('./project-settings-shell')
    const view = render(
      <ProjectSettingsShell projectId="project-a">
        <div>restricted-route-content</div>
      </ProjectSettingsShell>,
    )

    expect(view.getByText('managed.projectSettings.tabs.overview')).toBeTruthy()
    expect(view.queryByText('managed.projectSettings.tabs.access')).toBeNull()
    expect(view.queryByText('managed.projectSettings.tabs.tokens')).toBeNull()
    expect(view.queryByText('managed.projectSettings.tabs.lifecycle')).toBeNull()
    expect(view.queryByText('restricted-route-content')).toBeNull()
    expect(view.getByText('managed.projectSettings.restricted.title')).toBeTruthy()

    const overviewLink = view
      .getByText('managed.projectSettings.restricted.backToOverview')
      .closest('a')
    expect(overviewLink?.getAttribute('href')).toBe('/managed/projects/project-a')
  })
})
