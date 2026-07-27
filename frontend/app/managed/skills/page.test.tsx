import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SkillFileRecord, SkillRecord, SkillVersionRecord } from '@/types/managed'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('next-themes', () => ({
  useTheme: () => ({ resolvedTheme: 'light' }),
}))

vi.mock('@codemirror/lang-python', () => ({
  python: () => ({}),
}))

vi.mock('@codemirror/view', () => ({
  EditorView: { lineWrapping: {} },
}))

vi.mock('@uiw/codemirror-theme-vscode', () => ({
  vscodeDark: {},
}))

vi.mock('@uiw/react-codemirror', () => ({
  default: ({ onChange, value }: { onChange: (value: string) => void; value: string }) => (
    <textarea
      aria-label="code-editor"
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  ),
}))

vi.mock('react-markdown', () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

vi.mock('remark-gfm', () => ({
  default: () => null,
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key, i18n: { language: 'en' } }),
}))

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedPut: vi.fn(),
  managedUpload: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('@/components/managed/skills/skill-status-badges', () => ({
  SkillLifecycleBadge: () => <span>lifecycle</span>,
  SkillRiskScoreBadge: ({ score }: { score: number }) => <span>score:{score}</span>,
  SkillSecurityBadge: () => <span>security</span>,
  SkillStatusBadges: () => <span>status</span>,
  SkillVisibilityBadge: () => <span>visibility</span>,
}))

vi.mock('@/components/managed/skills/skill-version-diff', () => ({
  SkillVersionDiffView: () => <div>diff</div>,
}))

vi.mock('@/components/managed/shared', () => ({
  ConfirmDialog: ({
    confirmLabel,
    onCancel,
    onConfirm,
    open,
    title,
  }: {
    confirmLabel: string
    onCancel: () => void
    onConfirm: () => void
    open: boolean
    title: string
  }) =>
    open ? (
      <div>
        <h2>{title}</h2>
        <button onClick={onConfirm}>{confirmLabel}</button>
        <button onClick={onCancel}>cancel</button>
      </div>
    ) : null,
  DataTable: ({
    actionMenu,
    data,
    onRowClick,
  }: {
    actionMenu?: (row: SkillRecord) => { label: string; onClick: () => void }[]
    data: SkillRecord[]
    onRowClick?: (row: SkillRecord) => void
  }) => (
    <div>
      {data.map((skill) => (
        <div key={skill.id}>
          <button onClick={() => onRowClick?.(skill)}>{skill.name}</button>
          {actionMenu?.(skill).map((item) => (
            <button key={item.label} onClick={item.onClick}>
              {skill.id}:{item.label}
            </button>
          ))}
        </div>
      ))}
    </div>
  ),
  FilterBar: () => null,
  MonoId: ({ id }: { id: string }) => <span>{id}</span>,
  PageHeader: ({
    action,
    breadcrumb,
    title,
  }: {
    action?: ReactNode
    breadcrumb?: { label: string; onClick?: () => void }[]
    title: string
  }) => (
    <div>
      <h1>{title}</h1>
      {breadcrumb?.map((item) => (
        <button key={item.label} onClick={item.onClick}>
          {item.label}
        </button>
      ))}
      {action}
    </div>
  ),
  RelativeTime: ({ date }: { date: string }) => <span>{date}</span>,
  ResourceErrorState: () => null,
  StatusBadge: ({ status }: { status: string }) => <span>{status}</span>,
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    disabled,
    onClick,
    type = 'button',
  }: {
    children: ReactNode
    disabled?: boolean
    onClick?: () => void
    type?: 'button' | 'submit' | 'reset'
  }) => (
    <button type={type} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    children,
    onOpenChange,
    open,
  }: {
    children: ReactNode
    onOpenChange?: (open: boolean) => void
    open: boolean
  }) =>
    open ? (
      <div>
        {children}
        <button onClick={() => onOpenChange?.(false)}>dialog-close</button>
      </div>
    ) : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({
    autoFocus: _autoFocus,
    onChange,
    ...props
  }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
    />
  ),
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

vi.mock('@/components/ui/tabs', () => {
  let onTabsValueChange: ((value: string) => void) | undefined
  return {
    Tabs: ({
      children,
      onValueChange,
    }: {
      children: ReactNode
      onValueChange?: (value: string) => void
    }) => {
      onTabsValueChange = onValueChange
      return <div>{children}</div>
    },
    TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    TabsTrigger: ({ children, value }: { children: ReactNode; value: string }) => (
      <button onClick={() => onTabsValueChange?.(value)}>{children}</button>
    ),
  }
})

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.HTMLButtonElement = dom.window.HTMLButtonElement
globalThis.HTMLTextAreaElement = dom.window.HTMLTextAreaElement
globalThis.localStorage = dom.window.localStorage

import { managedDelete, managedGet, managedPost, managedPut, managedUpload } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { useProjectStore } from '@/stores/managed/project-store'

import SkillManagerPage from './page'

const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const managedPutMock = managedPut as unknown as ReturnType<typeof vi.fn>
const managedUploadMock = managedUpload as unknown as ReturnType<typeof vi.fn>
const toastOperationErrorMock = toastOperationError as unknown as ReturnType<typeof vi.fn>

let activeProject = 'project-a'

function skill(id: string, name: string): SkillRecord {
  return {
    id,
    source: 'custom',
    name,
    description: `${name} description`,
    content: `${name} content`,
    tags: [],
    allowed_tools: [],
    metadata: {},
    license: 'MIT',
    compatibility: {},
    visibility: 'project',
    lifecycle_status: 'draft',
    source_type: '',
    source_url: '',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

function skillFile(
  id: string,
  skillId: string,
  content: string,
  fileName = 'SKILL.md',
  path = '',
  fileType = 'markdown',
): SkillFileRecord {
  return {
    id,
    skill_id: skillId,
    path,
    file_name: fileName,
    file_type: fileType,
    content,
    size: content.length,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

function skillVersion(version: string, skillId: string): SkillVersionRecord {
  return {
    id: `sklver_${version.replace(/\./g, '_')}`,
    skill_id: skillId,
    version,
    name: `Version ${version}`,
    description: `Version ${version} description`,
    directory: '',
    content: `Version ${version} content`,
    frontmatter: {},
    release_notes: `Release ${version}`,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function projectInfo(archivedAt: string | null = null) {
  return {
    id: 'project-a',
    org_id: 'org-a',
    name: 'Project A',
    slug: 'project-a',
    is_default: true,
    archived_at: archivedAt,
    // Admin-tier actions (publish, delete, lifecycle) require capability
    // 'admin'; fixtures represent a project admin unless a test overrides.
    capability: 'admin',
  }
}

function managedOptions(projectId = 'project-a') {
  return {
    headers: {
      'X-Org-Id': 'org-a',
      'X-Project-Id': projectId,
    },
    skipManagedContext: true,
  }
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

const skillA = skill('skill_a', 'Skill A')
const archivedSkillA: SkillRecord = { ...skillA, lifecycle_status: 'archived' }
const skillB = skill('skill_b', 'Skill B')
const fileA = skillFile('sklfile_a', skillA.id, 'Skill A content')
const helperFileA = skillFile(
  'sklfile_a_helper',
  skillA.id,
  'print("helper")',
  'helper.py',
  '',
  'python',
)
const secondHelperFileA = skillFile(
  'sklfile_a_helper_two',
  skillA.id,
  'print("helper two")',
  'helper_two.py',
  '',
  'python',
)
const toolsFileA = skillFile(
  'sklfile_a_tools',
  skillA.id,
  'print("tools")',
  'tool.py',
  'tools/',
  'python',
)
const docsFileA = skillFile('sklfile_a_docs', skillA.id, '# docs', 'readme.md', 'docs/', 'markdown')
const fileB = skillFile('sklfile_b', skillB.id, 'Skill B content')
const versionAOne = skillVersion('1.0.0', skillA.id)
const versionATwo = skillVersion('1.1.0', skillA.id)

function getRowActionButton(
  container: HTMLElement,
  label: string,
  actionIndex = 0,
): HTMLButtonElement {
  const labelNode = Array.from(container.querySelectorAll('span')).find(
    (node) => node.textContent === label,
  )
  const row = labelNode?.closest('div')
  const action = row?.querySelectorAll('button')[actionIndex]
  if (!(action instanceof HTMLButtonElement)) {
    throw new Error(`Missing action button ${actionIndex} for ${label}`)
  }
  return action
}

function setupManagedGetMock({ skillARecord = skillA }: { skillARecord?: SkillRecord } = {}) {
  managedGetMock.mockImplementation((url: string) => {
    if (url.startsWith('/skills?')) {
      const rows = activeProject === 'project-a' ? [skillARecord, skillB] : [skillB]
      return Promise.resolve({ data: rows, has_more: false })
    }
    if (url === '/skills/a') return Promise.resolve(skillARecord)
    if (url === '/skills/b') return Promise.resolve(skillB)
    if (url === '/skills/a/files') {
      return Promise.resolve({
        data: [fileA, helperFileA, secondHelperFileA, toolsFileA, docsFileA],
      })
    }
    if (url === '/skills/b/files') return Promise.resolve({ data: [fileB] })
    if (url === '/skills/a/versions?limit=50') {
      return Promise.resolve({ data: [versionATwo, versionAOne] })
    }
    if (url === '/skills/b/versions?limit=50') return Promise.resolve({ data: [] })
    if (url.includes('/versions/') && url.endsWith('/files')) {
      return Promise.resolve({ data: [fileA] })
    }
    if (url.includes('/versions')) return Promise.resolve({ data: [] })
    if (url.includes('/security-scans')) return Promise.resolve({ data: [] })
    return Promise.resolve({ data: [], has_more: false })
  })
}

function renderSkillsPage(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <SkillManagerPage />
    </QueryClientProvider>,
  )
}

describe('SkillManagerPage managed scope lifecycle', () => {
  beforeEach(() => {
    activeProject = 'project-a'
    managedDeleteMock.mockReset()
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedPutMock.mockReset()
    managedUploadMock.mockReset()
    toastOperationErrorMock.mockReset()
    setupManagedGetMock()
    managedDeleteMock.mockResolvedValue({})
    managedPostMock.mockResolvedValue({})
    managedPutMock.mockResolvedValue({})
    managedUploadMock.mockResolvedValue(skillA)
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: projectInfo(null),
      organizations: [],
      projects: [],
    })
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
    localStorage.clear()
  })

  it('does not invalidate the newly selected skill when an old security rescan completes', async () => {
    const rescan = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(rescan.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const view = renderSkillsPage(queryClient)

    const skillAButton = await view.findByRole('button', { name: 'Skill A' })
    await act(async () => {
      fireEvent.click(skillAButton)
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: /managed\.skills\.rescanSecurity/ }))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledWith(
      '/skills/a/security-scans/rescan',
      {},
      managedOptions(),
    )

    await act(async () => {
      activeProject = 'project-b'
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    const backButton = view.queryByRole('button', { name: 'managed.skills.title' })
    if (backButton) {
      await act(async () => {
        fireEvent.click(backButton)
      })
    }

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill B' }))
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill B' })).toBeTruthy()
    })

    await act(async () => {
      rescan.resolve({})
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['skill', 'org-a:project-b', 'skill_b'],
    })
    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['skill-security-scans', 'org-a:project-b', 'skill_b'],
    })
  })

  it('does not show an error toast when an old security rescan fails after the selected skill changes', async () => {
    const rescan = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(rescan.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: /managed\.skills\.rescanSecurity/ }))
      await Promise.resolve()
    })

    await act(async () => {
      activeProject = 'project-b'
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill B' }))
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill B' })).toBeTruthy()
    })

    await act(async () => {
      rescan.reject(new Error('old rescan failed'))
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(toastOperationErrorMock).not.toHaveBeenCalled()
  })

  it('does not carry the saved flash from one selected skill to another', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    managedPutMock.mockResolvedValueOnce({
      ...skillA,
      name: 'Skill A renamed',
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.metadata' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('managed.skills.namePlaceholder'), {
        target: { value: 'Skill A renamed' },
      })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('button', { name: /managed\.skills\.saveChanges/ }).disabled).toBe(
        false,
      )
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: /managed\.skills\.saveChanges/ }))
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.getByText('managed.skills.savedSuccess')).toBeTruthy()
    expect(managedPutMock).toHaveBeenCalledWith(
      '/skills/a',
      expect.objectContaining({ name: 'Skill A renamed' }),
      {
        ...managedOptions(),
        timeout: 200000,
      },
    )

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.title' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill B' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill B' })).toBeTruthy()
    })

    expect(view.queryByText('managed.skills.savedSuccess')).toBeNull()
  })

  it('does not close a new delete confirmation when an older skill delete finishes', async () => {
    const deleteSkill = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(deleteSkill.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await waitFor(() => {
      expect(view.getByRole('button', { name: 'Skill A' })).toBeTruthy()
      expect(view.getByRole('button', { name: 'Skill B' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByText('skill_a:managed.skills.deleteSkill'))
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.deleteSkill' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'cancel' }))
    })

    await act(async () => {
      fireEvent.click(view.getByText('skill_b:managed.skills.deleteSkill'))
    })

    await act(async () => {
      deleteSkill.resolve({})
      await Promise.resolve()
    })

    expect(view.getByRole('button', { name: 'cancel' })).toBeTruthy()
  })

  it('does not delete a skill that leaves the current skills list during confirmation', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await waitFor(() => {
      expect(view.getByRole('button', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByText('skill_a:managed.skills.deleteSkill'))
    })

    await act(async () => {
      queryClient.setQueryData(['skills', 'org-a:project-a', '/skills', undefined, false, 10], {
        data: [skillB],
        has_more: false,
      })
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.deleteSkill' }))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/skills/a', managedOptions())
  })

  it('does not close a new file delete confirmation when an older file delete finishes', async () => {
    const deleteFile = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(deleteFile.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByText('helper.py')).toBeTruthy()
      expect(view.getByText('helper_two.py')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getRowActionButton(view.container, 'helper.py'))
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.deleteFile' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.cancel' }))
    })

    await act(async () => {
      fireEvent.click(getRowActionButton(view.container, 'helper_two.py'))
    })

    await act(async () => {
      deleteFile.resolve({})
      await Promise.resolve()
    })

    expect(view.getByRole('button', { name: 'managed.skills.cancel' })).toBeTruthy()
  })

  it('does not delete a file that leaves the current skill files during confirmation', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByText('helper.py')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getRowActionButton(view.container, 'helper.py'))
    })

    await act(async () => {
      queryClient.setQueryData(
        ['skill-files', 'org-a:project-a', skillA.id],
        [fileA, secondHelperFileA, toolsFileA, docsFileA],
      )
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.deleteFile' }))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/skills/a/files/a_helper', managedOptions())
  })

  it('does not close a new folder delete confirmation when an older folder delete finishes', async () => {
    const deleteFolder = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(deleteFolder.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByText('tools/')).toBeTruthy()
      expect(view.getByText('docs/')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getRowActionButton(view.container, 'tools/', 1))
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.deleteFolder' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.cancel' }))
    })

    await act(async () => {
      fireEvent.click(getRowActionButton(view.container, 'docs/', 1))
    })

    await act(async () => {
      deleteFolder.resolve({})
      await Promise.resolve()
    })

    expect(view.getByRole('button', { name: 'managed.skills.cancel' })).toBeTruthy()
  })

  it('does not delete a folder after its current files leave the skill files list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByText('tools/')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(getRowActionButton(view.container, 'tools/', 1))
    })

    await act(async () => {
      queryClient.setQueryData(
        ['skill-files', 'org-a:project-a', skillA.id],
        [fileA, helperFileA, secondHelperFileA, docsFileA],
      )
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.deleteFolder' }))
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/skills/a/files/a_tools', managedOptions())
  })

  it('does not close a new version delete confirmation when an older version delete finishes', async () => {
    const deleteVersion = deferred<Record<string, never>>()
    managedDeleteMock.mockReturnValueOnce(deleteVersion.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.versionHistory' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByText('v1.1.0')).toBeTruthy()
      expect(view.getByText('v1.0.0')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getAllByRole('button', { name: 'managed.skills.deleteVersion' })[0])
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.delete' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'common.cancel' }))
    })

    await act(async () => {
      fireEvent.click(view.getAllByRole('button', { name: 'managed.skills.deleteVersion' })[1])
    })

    await act(async () => {
      deleteVersion.resolve({})
      await Promise.resolve()
    })

    expect(view.getByRole('button', { name: 'common.cancel' })).toBeTruthy()
  })

  it('does not save metadata for a skill that leaves the current skills list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.metadata' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('managed.skills.namePlaceholder'), {
        target: { value: 'Skill A renamed' },
      })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('button', { name: /managed\.skills\.saveChanges/ }).disabled).toBe(
        false,
      )
    })

    await act(async () => {
      queryClient.setQueryData(['skills', 'org-a:project-a', '/skills', undefined, false, 10], {
        data: [skillB],
        has_more: false,
      })
      fireEvent.click(view.getByRole('button', { name: /managed\.skills\.saveChanges/ }))
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalledWith('/skills/a', expect.anything(), {
      ...managedOptions(),
      timeout: 200000,
    })
  })

  it('does not save metadata from an old skill editor after the managed project changes in the same tick', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.metadata' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('managed.skills.namePlaceholder'), {
        target: { value: 'Skill A production rename' },
      })
      await Promise.resolve()
    })

    const oldSaveButton = view.getByRole('button', { name: /managed\.skills\.saveChanges/ })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(oldSaveButton)
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalledWith('/skills/a', expect.anything(), {
      ...managedOptions(),
      timeout: 200000,
    })
  })

  it('does not keyboard-save a file that leaves the current skill files list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByText('helper.py')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByText('helper.py'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.change(view.getByLabelText('code-editor'), {
        target: { value: 'print("changed helper")' },
      })
      await Promise.resolve()
    })

    await act(async () => {
      queryClient.setQueryData(
        ['skill-files', 'org-a:project-a', skillA.id],
        [fileA, secondHelperFileA, toolsFileA, docsFileA],
      )
      fireEvent.keyDown(document, { key: 's', metaKey: true })
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalledWith('/skills/a/files/a_helper', expect.anything(), {
      ...managedOptions(),
      timeout: 200000,
    })
  })

  it('does not create a version for a skill that leaves the current skills list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.createVersionBtn' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('managed.skills.releaseNotesPlaceholder'), {
        target: { value: 'stale release' },
      })
      queryClient.setQueryData(['skills', 'org-a:project-a', '/skills', undefined, false, 10], {
        data: [skillB],
        has_more: false,
      })
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.createVersionBtn' }))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/skills/a/versions',
      expect.anything(),
      managedOptions(),
    )
  })

  it('does not rescan security for a skill that leaves the current skills list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['skills', 'org-a:project-a', '/skills', undefined, false, 10], {
        data: [skillB],
        has_more: false,
      })
      fireEvent.click(view.getByRole('button', { name: /managed\.skills\.rescanSecurity/ }))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/skills/a/security-scans/rescan',
      {},
      managedOptions(),
    )
  })

  it('does not rescan security from an old skill editor after the managed project changes in the same tick', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    const oldRescanButton = view.getByRole('button', { name: /managed\.skills\.rescanSecurity/ })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(oldRescanButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/skills/a/security-scans/rescan',
      {},
      managedOptions(),
    )
  })

  it('does not delete an old project skill after the managed project changes in the same tick', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await waitFor(() => {
      expect(view.getByText('Skill A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByText('skill_a:managed.skills.deleteSkill'))
    })

    const oldDeleteButton = view.getByRole('button', { name: 'managed.skills.deleteSkill' })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(oldDeleteButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/skills/a', managedOptions())
  })

  it('does not submit a lifecycle transition for a skill that leaves the current skills list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
      expect(
        view.getByRole('button', {
          name: 'managed.skills.transition.submitForReview',
        }),
      ).toBeTruthy()
    })

    await act(async () => {
      queryClient.setQueryData(['skills', 'org-a:project-a', '/skills', undefined, false, 10], {
        data: [skillB],
        has_more: false,
      })
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(
        view.getByRole('button', {
          name: 'managed.skills.transition.submitForReview',
        }),
      )
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/skills/a/submit-review',
      {},
      managedOptions(),
    )
  })

  it('does not invalidate skills from a security rescan completion after the page unmounts', async () => {
    const rescan = deferred<Record<string, unknown>>()
    managedPostMock.mockReturnValueOnce(rescan.promise)
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: /managed\.skills\.rescanSecurity/ }))
      await Promise.resolve()
    })

    view.unmount()

    await act(async () => {
      rescan.resolve({})
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['skills'] })
  })

  it('does not offer destructive list actions for an archived skill', async () => {
    setupManagedGetMock({ skillARecord: archivedSkillA })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await waitFor(() => {
      expect(view.getByRole('button', { name: 'Skill A' })).toBeTruthy()
    })

    expect(view.getByText('skill_a:managed.skills.viewDetails')).toBeTruthy()
    expect(view.queryByText('skill_a:managed.skills.deleteSkill')).toBeNull()
  })

  it('keeps an archived skill read-only across toolbar, keyboard, and workspace mutations', async () => {
    setupManagedGetMock({ skillARecord: archivedSkillA })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
      expect(view.getByText('helper.py')).toBeTruthy()
    })

    const rescanButton = view.getByRole('button', { name: /managed\.skills\.rescanSecurity/ })
    const createVersionButton = view.getByRole('button', {
      name: 'managed.skills.createVersionBtn',
    })
    expect(rescanButton.disabled).toBe(true)
    expect(createVersionButton.disabled).toBe(true)

    await act(async () => {
      fireEvent.click(rescanButton)
      fireEvent.click(createVersionButton)
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(view.getByText('helper.py'))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.change(view.getByLabelText('code-editor'), {
        target: { value: 'print("archived write attempt")' },
      })
      await Promise.resolve()
    })

    const saveButton = view.getByRole('button', { name: /managed\.skills\.saveChanges/ })
    expect(saveButton.disabled).toBe(true)

    await act(async () => {
      fireEvent.click(saveButton)
      fireEvent.keyDown(document, { key: 's', metaKey: true })
      await Promise.resolve()
    })

    expect(() => getRowActionButton(view.container, 'helper.py')).toThrow()
    expect(() => getRowActionButton(view.container, 'tools/', 1)).toThrow()
    expect(managedPostMock).not.toHaveBeenCalled()
    expect(managedPutMock).not.toHaveBeenCalled()
    expect(managedDeleteMock).not.toHaveBeenCalled()
  })

  it('hides project write actions when the current project is archived', async () => {
    useProjectStore.setState({
      currentProject: projectInfo('2026-01-02T00:00:00Z'),
    })
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await waitFor(() => {
      expect(view.getByRole('button', { name: 'Skill A' })).toBeTruthy()
    })

    expect(view.queryByText('managed.skills.importSkill')).toBeNull()
    expect(view.queryByText('managed.skills.aiAuthor.entry')).toBeNull()
    expect(view.getByText('skill_a:managed.skills.viewDetails')).toBeTruthy()
    expect(view.queryByText('skill_a:managed.skills.deleteSkill')).toBeNull()

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
      expect(view.getByText('helper.py')).toBeTruthy()
    })

    expect(
      view.queryByRole('button', {
        name: 'managed.skills.transition.submitForReview',
      }),
    ).toBeNull()
    expect(view.getByRole('button', { name: /managed\.skills\.rescanSecurity/ }).disabled).toBe(
      true,
    )
    expect(view.getByRole('button', { name: 'managed.skills.createVersionBtn' }).disabled).toBe(
      true,
    )
    expect(view.getByRole('button', { name: /managed\.skills\.saveChanges/ }).disabled).toBe(true)
    expect(() => getRowActionButton(view.container, 'helper.py')).toThrow()
    expect(() => getRowActionButton(view.container, 'tools/', 1)).toThrow()
  })

  it('does not delete a skill from an old confirmation after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await waitFor(() => {
      expect(view.getByText('Skill A')).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByText('skill_a:managed.skills.deleteSkill'))
    })

    const oldDeleteButton = view.getByRole('button', { name: 'managed.skills.deleteSkill' })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldDeleteButton)
      await Promise.resolve()
    })

    expect(managedDeleteMock).not.toHaveBeenCalledWith('/skills/a', managedOptions())
  })

  it('does not save metadata from an old skill editor after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.metadata' }))
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('managed.skills.namePlaceholder'), {
        target: { value: 'Skill A archived-project rename' },
      })
      await Promise.resolve()
    })

    const oldSaveButton = view.getByRole('button', { name: /managed\.skills\.saveChanges/ })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldSaveButton)
      await Promise.resolve()
    })

    expect(managedPutMock).not.toHaveBeenCalledWith('/skills/a', expect.anything(), {
      ...managedOptions(),
      timeout: 200000,
    })
  })

  it('does not rescan security from an old skill editor after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    const oldRescanButton = view.getByRole('button', { name: /managed\.skills\.rescanSecurity/ })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldRescanButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/skills/a/security-scans/rescan',
      {},
      managedOptions(),
    )
  })

  it('does not submit a lifecycle transition from an old skill editor after the current project is archived', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderSkillsPage(queryClient)

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(
        view.getByRole('button', {
          name: 'managed.skills.transition.submitForReview',
        }),
      ).toBeTruthy()
    })

    const oldTransitionButton = view.getByRole('button', {
      name: 'managed.skills.transition.submitForReview',
    })

    await act(async () => {
      useProjectStore.setState({
        currentProject: projectInfo('2026-01-02T00:00:00Z'),
      })
      fireEvent.click(oldTransitionButton)
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith(
      '/skills/a/submit-review',
      {},
      managedOptions(),
    )
  })

  it('restores a version through the confirm dialog', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })
    let view!: ReturnType<typeof renderSkillsPage>
    await act(async () => {
      view = renderSkillsPage(queryClient)
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(await view.findByRole('button', { name: 'Skill A' }))
      await Promise.resolve()
    })
    await waitFor(() => {
      expect(view.getByRole('heading', { name: 'Skill A' })).toBeTruthy()
    })

    // Open the version-history tab, then trigger restore on the latest version.
    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.versionHistory' }))
      await Promise.resolve()
    })
    const restoreButtons = await view.findAllByRole('button', {
      name: 'managed.skills.restoreVersion',
    })
    await act(async () => {
      fireEvent.click(restoreButtons[0])
      await Promise.resolve()
    })

    // Confirm dialog → POST to the restore endpoint.
    await act(async () => {
      fireEvent.click(view.getByRole('button', { name: 'managed.skills.restore' }))
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedPostMock).toHaveBeenCalledWith(
        '/skills/a/versions/restore/1.1.0',
        {},
        managedOptions(),
      )
    })
  })
})
