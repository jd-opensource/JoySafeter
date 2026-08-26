import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import React, { createContext, useContext } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { toast } from '@/hooks/use-toast'
import { managedGet, managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { useProjectStore } from '@/stores/managed/project-store'
import type { OrgInfo, ProjectInfo } from '@/stores/managed/project-store'
import {
  FIFTH_PROJECT_ID,
  FOURTH_PROJECT_ID,
  ORGANIZATION_ID,
  OTHER_ORGANIZATION_ID,
  OTHER_PROJECT_ID,
  PROJECT_ID,
  THIRD_PROJECT_ID,
  USER_ID,
} from '@/test-utils/entity-ids'
import type { OrganizationId, ProjectId } from '@/types/entity-id'

vi.mock('@/lib/api-client', () => ({
  extractErrorFromResponse: vi.fn(async () => new Error('mock api error')),
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
  managedPut: vi.fn(),
}))

vi.mock('@/lib/i18n', () => ({
  i18n: { language: 'en' },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

vi.mock('@/hooks/use-toast', () => ({
  toast: vi.fn(),
}))

vi.mock('@/lib/managed/errors', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/managed/errors')>()
  return {
    ...actual,
    toastOperationError: vi.fn(),
  }
})

vi.mock('@/lib/auth/auth-client', () => ({
  client: { signOut: vi.fn() },
  useSession: () => ({
    data: { user: { name: 'User', email: 'user@example.com' } },
  }),
}))

vi.mock('@/stores/sidebar/store', () => ({
  useSidebarStore: () => ({ isCollapsed: false, setIsCollapsed: vi.fn() }),
}))

vi.mock('next/navigation', () => ({
  usePathname: () => '/managed/agents',
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}))

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}))

const dropdownContext = createContext<{ open: boolean; setOpen: (open: boolean) => void } | null>(
  null,
)

vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({
    children,
    open = false,
    onOpenChange,
  }: {
    children: ReactNode
    open?: boolean
    onOpenChange?: (open: boolean) => void
  }) => (
    <dropdownContext.Provider value={{ open, setOpen: (next) => onOpenChange?.(next) }}>
      <div>{children}</div>
    </dropdownContext.Provider>
  ),
  DropdownMenuContent: ({ children }: { children: ReactNode }) => {
    const ctx = useContext(dropdownContext)
    return ctx?.open ? <div>{children}</div> : null
  },
  DropdownMenuItem: ({
    children,
    onClick,
    onSelect,
    className,
  }: {
    children: ReactNode
    onClick?: () => void
    onSelect?: () => void
    className?: string
  }) => (
    <button className={className} type="button" onClick={onClick || onSelect}>
      {children}
    </button>
  ),
  DropdownMenuSeparator: () => null,
  DropdownMenuSub: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuSubContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuSubTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => {
    const ctx = useContext(dropdownContext)
    return React.cloneElement(children as React.ReactElement<{ onClick?: () => void }>, {
      onClick: () => ctx?.setOpen(!ctx.open),
    })
  },
}))

vi.mock('@/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TooltipProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage
Object.defineProperty(globalThis.HTMLElement.prototype, 'attachEvent', {
  configurable: true,
  value: vi.fn(),
})
Object.defineProperty(globalThis.HTMLElement.prototype, 'detachEvent', {
  configurable: true,
  value: vi.fn(),
})

const organizations: OrgInfo[] = [
  {
    id: ORGANIZATION_ID,
    name: 'Organization Alpha With A Long Name',
    slug: 'org-a',
    role: 'owner',
    owner_name: 'User',
    owner_email: 'user@example.com',
  },
  {
    id: OTHER_ORGANIZATION_ID,
    name: 'Organization Beta',
    slug: 'org-b',
    role: 'member',
    owner_name: 'Bob Owner',
    owner_email: 'bob@example.com',
  },
]

const projectA: ProjectInfo = {
  id: PROJECT_ID,
  name: 'Project A Current',
  slug: 'project-a-current',
  is_default: true,
  org_id: ORGANIZATION_ID,
  capability: 'write',
}

const projectBCurrent: ProjectInfo = {
  id: OTHER_PROJECT_ID,
  name: 'Project B Current',
  slug: 'project-b-current',
  is_default: true,
  org_id: OTHER_ORGANIZATION_ID,
  capability: 'write',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function authContext(orgId: OrganizationId, project: ProjectInfo) {
  return {
    user: { id: USER_ID, email: 'user@example.com', name: 'User' },
    organization: organizations.find((org) => org.id === orgId) || organizations[0],
    project,
    organizations,
    projects: [project],
  }
}

function setProjectContext(orgId: OrganizationId, project: ProjectInfo) {
  useProjectStore.setState({
    currentOrgId: orgId,
    currentProjectId: project.id,
    currentProject: project,
    organizations,
    projects: [project],
  })
}

function renderSidebar(AppSidebar: React.ComponentType) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
  const renderTree = () => (
    <QueryClientProvider client={queryClient}>
      <AppSidebar />
    </QueryClientProvider>
  )
  const view = render(renderTree())
  return {
    ...view,
    rerenderSidebar: () => view.rerender(renderTree()),
  }
}

function setCompactViewport(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: matches && query === '(max-width: 639px)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

describe('AppSidebar project switcher lifecycle', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.clearAllMocks()
    setCompactViewport(false)
    setProjectContext(ORGANIZATION_ID, projectA)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      currentProject: null,
      organizations: [],
      projects: [],
    })
  })

  it('uses the compact navigation rail on narrow viewports', async () => {
    setCompactViewport(true)
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)

    expect(view.container.querySelector('aside')).toHaveClass('w-[52px]')
    expect(view.queryByText('sidebar.appTitle')).toBeNull()
  })

  it('keeps management object-oriented and links organization management from the switcher', async () => {
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)

    expect(view.getByText('nav.organization')).toBeTruthy()
    expect(view.getByText('nav.projects')).toBeTruthy()
    expect(view.queryByText('nav.members')).toBeNull()
    expect(view.queryByText('nav.apiKeys')).toBeNull()

    const trigger = view.getByText('Project A Current').closest('button')
    expect(trigger).not.toBeNull()
    await act(async () => {
      fireEvent.click(trigger!)
    })

    const manageOrganizations = view.getByText('sidebar.manageOrganizations').closest('a')
    expect(manageOrganizations?.getAttribute('href')).toBe('/managed/settings')
  })

  it('shows the complete current hierarchy and groups owned and shared organizations', async () => {
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)

    const trigger = view.getByRole('button', { name: /Organization Alpha With A Long Name/i })
    expect(trigger.textContent).toContain('Organization Alpha With A Long Name')
    expect(trigger.textContent).toContain('Project A Current')
    expect(trigger.textContent).toContain('sidebar.ownedByYou')

    await act(async () => {
      fireEvent.click(trigger)
    })

    expect(view.getByText('sidebar.ownedOrganizations')).toBeTruthy()
    expect(view.getByText('sidebar.sharedOrganizations')).toBeTruthy()
    expect(view.getAllByText('sidebar.ownedByYou').length).toBeGreaterThan(0)
    expect(view.getByText(/Bob Owner/)).toBeTruthy()
    expect(view.getAllByText('sidebar.defaultProject').length).toBeGreaterThan(0)
  })

  it('makes the current work location and switch actions explicit', async () => {
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([projectBCurrent])
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)

    expect(view.getByText('sidebar.currentContext')).toBeTruthy()
    expect(view.getByText('sidebar.switchContext')).toBeTruthy()

    const trigger = view.getByText('Project A Current').closest('button')
    expect(trigger).not.toBeNull()
    await act(async () => {
      fireEvent.click(trigger!)
    })

    await waitFor(() => expect(view.getByText('Project B Current')).toBeTruthy())
    expect(view.getByText('sidebar.switchHint')).toBeTruthy()

    const currentRow = view
      .getAllByText('Project A Current')
      .map((element) => element.closest('button'))
      .find((button) => button?.hasAttribute('aria-current'))
    expect(currentRow).toBeTruthy()
    expect(currentRow).toBeDisabled()
    expect(currentRow?.textContent).toContain('sidebar.defaultProject')
    expect(currentRow?.textContent).toContain('sidebar.currentProject')

    const targetRow = view.getByText('Project B Current').closest('button')
    expect(targetRow).not.toBeNull()
    expect(targetRow?.textContent).toContain('sidebar.defaultProject')
    expect(targetRow?.textContent).toContain('sidebar.switchAction')
  })

  it('shows switching progress and prevents duplicate requests', async () => {
    const switchRequest = deferred<{
      org_id: OrganizationId
      project_id: ProjectId
      project: ProjectInfo
      projects: ProjectInfo[]
    }>()
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([projectBCurrent])
    ;(managedPost as unknown as ReturnType<typeof vi.fn>).mockReturnValue(switchRequest.promise)
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)
    fireEvent.click(view.getByText('Project A Current').closest('button')!)
    await waitFor(() => expect(view.getByText('Project B Current')).toBeTruthy())

    const targetRow = view.getByText('Project B Current').closest('button')!
    act(() => {
      fireEvent.click(targetRow)
      fireEvent.click(targetRow)
    })

    await waitFor(() => expect(targetRow).toBeDisabled())
    expect(targetRow.textContent).toContain('sidebar.switching')
    expect(managedPost).toHaveBeenCalledTimes(1)

    await act(async () => {
      switchRequest.resolve({
        org_id: OTHER_ORGANIZATION_ID,
        project_id: OTHER_PROJECT_ID,
        project: projectBCurrent,
        projects: [projectBCurrent],
      })
      await switchRequest.promise
    })
  })

  it('confirms a successful switch and closes the switcher', async () => {
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([projectBCurrent])
    ;(managedPost as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      org_id: OTHER_ORGANIZATION_ID,
      project_id: OTHER_PROJECT_ID,
      project: projectBCurrent,
      projects: [projectBCurrent],
    })
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)
    fireEvent.click(view.getByText('Project A Current').closest('button')!)
    await waitFor(() => expect(view.getByText('Project B Current')).toBeTruthy())
    fireEvent.click(view.getByText('Project B Current').closest('button')!)

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'sidebar.switchSuccess' }),
      )
      expect(view.queryByPlaceholderText('sidebar.searchOrgProject')).toBeNull()
    })
  })

  it('keeps the switcher open and restores the action after failure', async () => {
    const switchError = new Error('switch failed')
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([projectBCurrent])
    ;(managedPost as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(switchError)
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)
    fireEvent.click(view.getByText('Project A Current').closest('button')!)
    await waitFor(() => expect(view.getByText('Project B Current')).toBeTruthy())
    fireEvent.click(view.getByText('Project B Current').closest('button')!)

    await waitFor(() => {
      expect(toastOperationError).toHaveBeenCalledWith(
        expect.any(Function),
        switchError,
        'sidebar.switchFailed',
      )
    })
    expect(view.getByPlaceholderText('sidebar.searchOrgProject')).toBeTruthy()
    const targetRow = view.getByText('Project B Current').closest('button')
    expect(targetRow).not.toBeDisabled()
    expect(targetRow?.textContent).toContain('sidebar.switchAction')
    consoleError.mockRestore()
  })

  it('shows the archived current project even when it is absent from the active project list', async () => {
    const archivedProject: ProjectInfo = {
      id: THIRD_PROJECT_ID,
      name: 'Archived Project',
      slug: 'project-archived',
      is_default: false,
      org_id: ORGANIZATION_ID,
      capability: 'write',
      archived_at: '2026-01-02T00:00:00Z',
    }
    useProjectStore.setState({
      currentOrgId: ORGANIZATION_ID,
      currentProjectId: archivedProject.id,
      currentProject: archivedProject,
      organizations,
      projects: [],
    })
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/auth/me') {
        return Promise.resolve({
          ...authContext(ORGANIZATION_ID, archivedProject),
          projects: [],
        })
      }
      return Promise.resolve([])
    })
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)

    expect(view.getAllByText('Archived Project').length).toBeGreaterThan(0)
  })

  it('does not let an older all-projects load override the active org project list', async () => {
    const oldOrgBProjects = deferred<ProjectInfo[]>()
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/auth/me') return Promise.resolve(authContext(ORGANIZATION_ID, projectA))
      if (path === '/auth/projects?include_archived=false&limit=200') return oldOrgBProjects.promise
      return Promise.resolve([])
    })
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)

    const trigger = view.getByText('Project A Current').closest('button')
    expect(trigger).not.toBeNull()
    await act(async () => {
      fireEvent.click(trigger!)
    })

    await waitFor(() => {
      expect(managedGet).toHaveBeenCalledWith('/auth/projects?include_archived=false&limit=200', {
        skipManagedContext: true,
        headers: { 'X-Org-Id': OTHER_ORGANIZATION_ID },
      })
    })

    await act(async () => {
      setProjectContext(OTHER_ORGANIZATION_ID, projectBCurrent)
      view.rerenderSidebar()
      await Promise.resolve()
    })
    expect(view.getAllByText('Project B Current').length).toBeGreaterThan(0)

    await act(async () => {
      oldOrgBProjects.resolve([
        {
          id: FOURTH_PROJECT_ID,
          name: 'Project B Old',
          slug: 'project-b-old',
          is_default: true,
          org_id: OTHER_ORGANIZATION_ID,
        },
      ])
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.queryByText('Project B Old')).toBeNull()
  })

  it('does not let an older project switch completion close a reopened switcher', async () => {
    const olderSwitch = deferred<{
      org_id: OrganizationId
      project_id: ProjectId
      project: ProjectInfo
      projects: ProjectInfo[]
    }>()
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/auth/me') return Promise.resolve(authContext(ORGANIZATION_ID, projectA))
      if (path === '/auth/projects?include_archived=false&limit=200') {
        return Promise.resolve([
          {
            id: FIFTH_PROJECT_ID,
            name: 'Project B Target',
            slug: 'project-b-target',
            is_default: true,
            org_id: OTHER_ORGANIZATION_ID,
          },
        ])
      }
      return Promise.resolve([])
    })
    ;(managedPost as unknown as ReturnType<typeof vi.fn>).mockReturnValue(olderSwitch.promise)
    const { AppSidebar } = await import('./app-sidebar')

    const view = renderSidebar(AppSidebar)

    const openSwitcher = async () => {
      const trigger = view.getByText('Project A Current').closest('button')
      expect(trigger).not.toBeNull()
      await act(async () => {
        fireEvent.click(trigger!)
      })
    }

    await openSwitcher()
    await waitFor(() => expect(view.getByText('Project B Target')).toBeTruthy())

    await act(async () => {
      fireEvent.click(view.getByText('Project B Target'))
      await Promise.resolve()
    })

    const openTrigger = view
      .getAllByText('Project A Current')
      .map((element) => element.closest('button'))
      .find((button) => !button?.hasAttribute('aria-current'))
    expect(openTrigger).toBeTruthy()
    await act(async () => {
      fireEvent.click(openTrigger!)
    })

    await waitFor(() => expect(view.queryByPlaceholderText('sidebar.searchOrgProject')).toBeNull())
    await openSwitcher()
    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('sidebar.searchOrgProject'), {
        target: { value: 'still-open' },
      })
    })

    await act(async () => {
      olderSwitch.resolve({
        org_id: OTHER_ORGANIZATION_ID,
        project_id: FIFTH_PROJECT_ID,
        project: {
          id: FIFTH_PROJECT_ID,
          name: 'Project B Target',
          slug: 'project-b-target',
          is_default: true,
          org_id: OTHER_ORGANIZATION_ID,
          capability: 'write',
        },
        projects: [
          {
            id: FIFTH_PROJECT_ID,
            name: 'Project B Target',
            slug: 'project-b-target',
            is_default: true,
            org_id: OTHER_ORGANIZATION_ID,
          },
        ],
      })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect((view.getByPlaceholderText('sidebar.searchOrgProject') as HTMLInputElement).value).toBe(
      'still-open',
    )
  })
})
