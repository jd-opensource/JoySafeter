import { cleanup, render, waitFor } from '@testing-library/react'
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
    projects,
    isLoading: false,
    switchProject,
  }),
}))

vi.mock('@/stores/managed/project-store', () => ({
  useProjectStore: (
    selector: (state: { currentProject: (typeof projects)[number] | null }) => unknown,
  ) =>
    selector({
      currentProject: projects.find((project) => project.id === activeProjectId) ?? null,
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
  })

  it('withholds children until the route project becomes the active context', async () => {
    const { ProjectSettingsShell } = await import('./project-settings-shell')
    const view = render(
      <ProjectSettingsShell projectId="project-b">
        <div>route-content</div>
      </ProjectSettingsShell>,
    )

    expect(view.queryByText('route-content')).toBeNull()
    await waitFor(() => expect(switchProject).toHaveBeenCalledWith('project-b', 'org-a'))

    activeProjectId = 'project-b'
    view.rerender(
      <ProjectSettingsShell projectId="project-b">
        <div>route-content</div>
      </ProjectSettingsShell>,
    )

    expect(view.getByText('route-content')).toBeTruthy()
    expect(view.getByText('Organization A')).toBeTruthy()
    expect(view.getByText('Project B')).toBeTruthy()
    expect(view.getByText('managed.projectSettings.capability.admin')).toBeTruthy()
    expect(view.getByText('managed.projectSettings.default')).toBeTruthy()
    expect(view.getByText('managed.projectSettings.archived')).toBeTruthy()

    const accessTab = view.getByText('managed.projectSettings.tabs.access').closest('a')
    expect(accessTab?.getAttribute('href')).toBe('/managed/projects/project-b/access')
    expect(accessTab?.getAttribute('aria-current')).toBe('page')
  })
})
