import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { useState, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/api-client', () => ({
  managedPost: vi.fn(),
}))

vi.mock('@/lib/managed/errors', () => ({
  toastOperationError: vi.fn(),
}))

vi.mock('@/components/ui/button', () => ({
  buttonVariants: () => '',
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
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({ onChange, onKeyDown, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
      onKeyDown={onKeyDown}
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

import { managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import { CreateMemoryStoreDialog } from './create-memory-store-dialog'

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function Harness({ onCreated = () => {} }: { onCreated?: () => void }) {
  const [open, setOpen] = useState(true)
  return <CreateMemoryStoreDialog open={open} onOpenChange={setOpen} onCreated={onCreated} />
}

describe('CreateMemoryStoreDialog managed scope lifecycle', () => {
  beforeEach(() => {
    managedPostMock.mockReset()
    managedPostMock.mockResolvedValue({})
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
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
      organizations: [],
      projects: [],
    })
    localStorage.clear()
  })

  it('does not submit a create draft after the managed project changes', async () => {
    const { getByPlaceholderText, queryByText } = render(<Harness />)

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.memoryStores.namePlaceholder'), {
        target: { value: 'Project A memory store' },
      })
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      await Promise.resolve()
    })

    const createButton = queryByText('common.create')
    if (createButton) {
      await act(async () => {
        fireEvent.click(createButton)
      })
    }

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('does not create a memory store from old dialog state in the same turn as a project switch', async () => {
    const { getByPlaceholderText, getByText } = render(<Harness />)

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.memoryStores.namePlaceholder'), {
        target: { value: 'Project A memory store' },
      })
      fireEvent.input(getByPlaceholderText('managed.memoryStores.descriptionPlaceholder'), {
        target: { value: 'Important project A notes' },
      })
    })

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      fireEvent.click(getByText('common.create'))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalledWith('memory_stores', expect.anything())
  })

  it('ignores a create completion after the managed project changes', async () => {
    const create = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const onCreated = vi.fn()
    const { getByPlaceholderText, getByText } = render(<Harness onCreated={onCreated} />)

    await act(async () => {
      fireEvent.input(getByPlaceholderText('managed.memoryStores.namePlaceholder'), {
        target: { value: 'Project A memory store' },
      })
    })

    await act(async () => {
      fireEvent.click(getByText('common.create'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      useProjectStore.setState({ currentOrgId: 'org-a', currentProjectId: 'project-b' })
      create.resolve({})
      await Promise.resolve()
    })

    expect(onCreated).not.toHaveBeenCalled()
  })

  it('ignores a create completion after the dialog unmounts', async () => {
    const create = deferred<Record<string, never>>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const onOpenChange = vi.fn()
    const onCreated = vi.fn()
    const view = render(
      <CreateMemoryStoreDialog open onOpenChange={onOpenChange} onCreated={onCreated} />,
    )

    await act(async () => {
      fireEvent.input(view.getByPlaceholderText('managed.memoryStores.namePlaceholder'), {
        target: { value: 'Unmounted memory store' },
      })
    })

    await act(async () => {
      fireEvent.click(view.getByText('common.create'))
      await Promise.resolve()
    })

    expect(managedPostMock).toHaveBeenCalledTimes(1)

    view.unmount()

    await act(async () => {
      create.resolve({})
      await Promise.resolve()
    })

    expect(onOpenChange).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
  })
})
