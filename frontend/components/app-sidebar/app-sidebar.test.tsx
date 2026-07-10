import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import React, { createContext, useContext } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'
import type { OrgInfo, ProjectInfo } from '@/stores/managed/project-store'

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

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
  { id: 'org-a', name: 'Org A', slug: 'org-a', role: 'owner' },
  { id: 'org-b', name: 'Org B', slug: 'org-b', role: 'owner' },
]

const projectA: ProjectInfo = {
  id: 'project-a-current',
  name: 'Project A Current',
  slug: 'project-a-current',
  is_default: true,
  org_id: 'org-a',
}

const projectBCurrent: ProjectInfo = {
  id: 'project-b-current',
  name: 'Project B Current',
  slug: 'project-b-current',
  is_default: true,
  org_id: 'org-b',
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

function authContext(orgId: string, project: ProjectInfo) {
  return {
    user: { id: 'user-1', email: 'user@example.com', name: 'User' },
    organization: organizations.find((org) => org.id === orgId) || organizations[0],
    project,
    organizations,
    projects: [project],
  }
}

function setProjectContext(orgId: string, project: ProjectInfo) {
  useProjectStore.setState({
    currentOrgId: orgId,
    currentProjectId: project.id,
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

describe('AppSidebar project switcher lifecycle', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setProjectContext('org-a', projectA)
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      organizations: [],
      projects: [],
    })
  })

  it('does not let an older all-projects load override the active org project list', async () => {
    const oldOrgBProjects = deferred<ProjectInfo[]>()
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/auth/me') return Promise.resolve(authContext('org-a', projectA))
      if (path === '/auth/projects?include_archived=false') return oldOrgBProjects.promise
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
      expect(managedGet).toHaveBeenCalledWith('/auth/projects?include_archived=false', {
        skipManagedContext: true,
        headers: { 'X-Org-Id': 'org-b' },
      })
    })

    await act(async () => {
      setProjectContext('org-b', projectBCurrent)
      view.rerenderSidebar()
      await Promise.resolve()
    })
    expect(view.getAllByText('Project B Current').length).toBeGreaterThan(0)

    await act(async () => {
      oldOrgBProjects.resolve([
        {
          id: 'project-b-old',
          name: 'Project B Old',
          slug: 'project-b-old',
          is_default: true,
          org_id: 'org-b',
        },
      ])
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.queryByText('Project B Old')).toBeNull()
  })

  it('does not let an older project switch completion close a reopened switcher', async () => {
    const olderSwitch = deferred<{ org_id: string; project: ProjectInfo; projects: ProjectInfo[] }>()
    ;(managedGet as unknown as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === '/auth/me') return Promise.resolve(authContext('org-a', projectA))
      if (path === '/auth/projects?include_archived=false') {
        return Promise.resolve([
          {
            id: 'project-b-target',
            name: 'Project B Target',
            slug: 'project-b-target',
            is_default: true,
            org_id: 'org-b',
          },
        ])
      }
      return Promise.resolve([])
    })
    ;(managedPost as unknown as ReturnType<typeof vi.fn>)
      .mockReturnValueOnce(olderSwitch.promise)
      .mockResolvedValueOnce({
        org_id: 'org-a',
        project: projectA,
        projects: [projectA],
      })
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

    const projectACandidates = view.getAllByText('Project A Current')
    await act(async () => {
      fireEvent.click(projectACandidates[projectACandidates.length - 1])
      await Promise.resolve()
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
        org_id: 'org-b',
        project: {
          id: 'project-b-target',
          name: 'Project B Target',
          slug: 'project-b-target',
          is_default: true,
          org_id: 'org-b',
        },
        projects: [
          {
            id: 'project-b-target',
            name: 'Project B Target',
            slug: 'project-b-target',
            is_default: true,
            org_id: 'org-b',
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
