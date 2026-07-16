import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import React, { type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedPatch: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/managed/schedules/cron-editor', () => ({
  CronEditor: () => <div data-testid="cron-editor" />,
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
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) =>
    open ? <div>{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h1>{children}</h1>,
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

vi.mock('@/components/ui/label', () => ({
  Label: ({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) => (
    <label htmlFor={htmlFor}>{children}</label>
  ),
}))

const SelectContext = React.createContext<(value: string) => void>(() => {})

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
  }: {
    children: ReactNode
    onValueChange?: (value: string) => void
    value?: string
  }) => (
    <SelectContext.Provider value={onValueChange ?? (() => {})}>
      <div data-testid={value ? `select-${value}` : undefined}>{children}</div>
    </SelectContext.Provider>
  ),
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: ReactNode; value: string }) => {
    const onValueChange = React.useContext(SelectContext)
    return (
      <button type="button" onClick={() => onValueChange(value)}>
        {children}
      </button>
    )
  },
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

vi.mock('@/components/ui/switch', () => ({
  Switch: ({
    checked,
    onCheckedChange,
  }: {
    checked: boolean
    onCheckedChange?: (checked: boolean) => void
  }) => (
    <input
      type="checkbox"
      role="switch"
      checked={checked}
      onChange={(e) => onCheckedChange?.(e.target.checked)}
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

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage

import { managedGet, managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import { CreateScheduleDialog } from './create-schedule-dialog'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>
const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function projectInfo(id = 'project-a', archivedAt: string | null = null) {
  return {
    id,
    org_id: 'org-a',
    name: id,
    slug: id,
    is_default: true,
    archived_at: archivedAt,
  }
}

function activeProject(id = 'project-a') {
  useProjectStore.setState({
    currentOrgId: 'org-a',
    currentProjectId: id,
    currentProject: projectInfo(id),
    organizations: [],
    projects: [],
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function renderDialog(onOpenChange = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const result = render(
    <QueryClientProvider client={queryClient}>
      <CreateScheduleDialog open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  )
  return { ...result, onOpenChange }
}

describe('CreateScheduleDialog managed lifecycle', () => {
  beforeEach(() => {
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    activeProject()
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    useProjectStore.setState({
      currentOrgId: null,
      currentProjectId: null,
      currentProject: null,
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('refetches agents and environments instead of reusing previous project options', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents?limit=200') {
        return [{ id: 'agent-a', name: 'Agent A', archived_at: null }]
      }
      if (path === '/environments?limit=200') {
        return [{ id: 'env-a', name: 'Env A', archived_at: null }]
      }
      return []
    })

    renderDialog()

    await waitFor(() => {
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/agents?limit=200')).toHaveLength(1)
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/environments?limit=200')).toHaveLength(1)
    })

    await act(async () => {
      activeProject('project-b')
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/agents?limit=200')).toHaveLength(2)
      expect(managedGetMock.mock.calls.filter(([path]) => path === '/environments?limit=200')).toHaveLength(2)
    })
  })

  it('does not apply stale submit completion after the managed scope changes', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents?limit=200') {
        return [{ id: 'agent-a', name: 'Agent A', archived_at: null }]
      }
      if (path === '/environments?limit=200') return []
      return []
    })
    const create = deferred<{ id: string }>()
    managedPostMock.mockReturnValue(create.promise)
    const { getByLabelText, getByText, onOpenChange } = renderDialog()

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })
    fireEvent.change(getByLabelText('managed.table.name'), {
      target: { value: 'Daily report' },
    })
    fireEvent.click(getByText('Agent A'))
    fireEvent.change(getByLabelText('managed.schedules.prompt'), {
      target: { value: 'Summarize yesterday' },
    })

    await act(async () => {
      fireEvent.click(getByText('common.create'))
    })
    expect(managedPostMock).toHaveBeenCalledWith('/schedules', expect.objectContaining({
      name: 'Daily report',
      agent_id: 'agent-a',
      prompt: 'Summarize yesterday',
    }))

    await act(async () => {
      activeProject('project-b')
      await Promise.resolve()
    })
    expect(onOpenChange).toHaveBeenCalledTimes(1)
    expect(onOpenChange).toHaveBeenLastCalledWith(false)

    await act(async () => {
      create.resolve({ id: 'schedule-created' })
      await create.promise
    })

    expect(onOpenChange).toHaveBeenCalledTimes(1)
  })

  it('blocks submit when the project becomes archived before the user saves', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path === '/agents?limit=200') {
        return [{ id: 'agent-a', name: 'Agent A', archived_at: null }]
      }
      if (path === '/environments?limit=200') return []
      return []
    })
    const { getByLabelText, getByText, onOpenChange } = renderDialog()

    await waitFor(() => {
      expect(getByText('Agent A')).toBeTruthy()
    })
    fireEvent.change(getByLabelText('managed.table.name'), {
      target: { value: 'Daily report' },
    })
    fireEvent.click(getByText('Agent A'))
    fireEvent.change(getByLabelText('managed.schedules.prompt'), {
      target: { value: 'Summarize yesterday' },
    })
    useProjectStore.setState({
      currentProject: projectInfo('project-a', '2026-07-01T00:00:00Z'),
    })

    await act(async () => {
      fireEvent.click(getByText('common.create'))
    })

    expect(managedPostMock).not.toHaveBeenCalled()
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
