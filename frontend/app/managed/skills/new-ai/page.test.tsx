import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SkillDraft } from '@/hooks/managed/use-skill-authoring'

let skillAuthoringSendMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string, _params?: unknown) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
}))

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('@/hooks/managed/use-skill-authoring', () => ({
  useSkillAuthoring: () => {
    const draft: SkillDraft = {
      name: 'Draft skill',
      description: '',
      tags: [],
      visibility: 'private',
      content: '# Draft',
      files: [],
    }
    return {
      messages: [],
      draft,
      draftSkillId: null,
      streaming: false,
      scanRunning: false,
      scanResult: null,
      publishing: false,
      hydrated: true,
      setDraft: vi.fn(),
      send: (...args: Parameters<typeof skillAuthoringSendMock>) =>
        skillAuthoringSendMock(...args),
      cancel: vi.fn(),
      saveDraft: vi.fn(),
      runScan: vi.fn(),
      publish: vi.fn(),
      reset: vi.fn(),
    }
  },
}))

vi.mock('@/components/managed/skills/skill-code-editor', () => ({
  SkillCodeEditor: ({
    onChange,
    readOnly,
    value,
  }: {
    onChange: (value: string) => void
    readOnly?: boolean
    value: string
  }) => (
    <textarea
      aria-label="code-editor"
      disabled={readOnly}
      value={value}
      onChange={(event) => onChange(event.currentTarget.value)}
    />
  ),
}))

vi.mock('@/components/managed/skills/skill-workspace', () => ({
  FileTreeNode: () => null,
  buildFileTree: () => ({ children: [] }),
}))

vi.mock('@/lib/managed/skill-draft-zip', () => ({
  downloadDraftZip: vi.fn(),
}))

vi.mock('react-markdown', () => ({
  default: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

vi.mock('remark-gfm', () => ({
  default: () => null,
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

vi.mock('@/components/ui/input', () => ({
  Input: ({ onChange, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
    />
  ),
}))

vi.mock('@/components/ui/textarea', () => ({
  Textarea: ({ onChange, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLTextAreaElement>}
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

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedGet } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import SkillAiAuthoringPage from './page'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>

function renderPage(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <SkillAiAuthoringPage />
    </QueryClientProvider>,
  )
}

function projectInfo(archivedAt: string | null = null) {
  return {
    id: 'project-a',
    org_id: 'org-a',
    name: 'Project A',
    slug: 'project-a',
    is_default: true,
    archived_at: archivedAt,
  }
}

describe('SkillAiAuthoringPage managed scope lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    skillAuthoringSendMock = vi.fn()
    managedGetMock.mockResolvedValue({ data: [{ id: 'secret-a', name: 'secret-a', is_default: true }] })
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

  it('refetches secrets instead of reusing the previous project secret list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    renderPage(queryClient)

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/secrets')
    })
    expect(managedGetMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledTimes(2)
    })
  })

  it('sends chat requests with the current secret after the secrets list changes', async () => {
    let secretName = 'secret-a'
    managedGetMock.mockImplementation(async () => ({
      data: [{ id: secretName, name: secretName, is_default: true }],
    }))
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    })

    const view = renderPage(queryClient)

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledTimes(1)
    })

    await act(async () => {
      const input = view.getByPlaceholderText(
        'managed.skills.aiAuthor.inputPlaceholder',
      ) as HTMLTextAreaElement
      input.value = 'First skill'
      fireEvent.input(input, { target: { value: 'First skill' } })
    })

    await act(async () => {
      view.getByTitle('managed.skills.aiAuthor.send').click()
      await Promise.resolve()
    })

    expect(skillAuthoringSendMock).toHaveBeenCalledWith('First skill', 'secret-a')

    secretName = 'secret-b'
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['secrets', 'org-a:project-a'] })
    })

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledTimes(2)
    })

    await act(async () => {
      const input = view.getByPlaceholderText(
        'managed.skills.aiAuthor.inputPlaceholder',
      ) as HTMLTextAreaElement
      input.value = 'Second skill'
      fireEvent.input(input, { target: { value: 'Second skill' } })
    })

    await act(async () => {
      view.getByTitle('managed.skills.aiAuthor.send').click()
      await Promise.resolve()
    })

    expect(skillAuthoringSendMock).toHaveBeenNthCalledWith(2, 'Second skill', 'secret-b')
  })

  it('renders the authoring workspace read-only when the current project is archived', async () => {
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

    const view = renderPage(queryClient)

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/secrets')
    })

    const input = view.getByPlaceholderText(
      'managed.skills.aiAuthor.inputPlaceholder',
    ) as HTMLTextAreaElement
    expect(input.disabled).toBe(true)
    expect(
      (view.getByText('managed.skills.aiAuthor.saveDraft').closest('button') as HTMLButtonElement)
        .disabled,
    ).toBe(true)
    expect(
      (view.getByText('managed.skills.aiAuthor.publish').closest('button') as HTMLButtonElement)
        .disabled,
    ).toBe(true)
    expect(
      (view.getByText('managed.skills.aiAuthor.scan.run').closest('button') as HTMLButtonElement)
        .disabled,
    ).toBe(true)
    expect((view.getByLabelText('code-editor') as HTMLTextAreaElement).disabled).toBe(true)

    await act(async () => {
      fireEvent.input(input, { target: { value: 'Should not send' } })
      view.getByTitle('managed.skills.aiAuthor.send').click()
      await Promise.resolve()
    })

    expect(skillAuthoringSendMock).not.toHaveBeenCalled()
  })
})
