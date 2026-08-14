import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedPost } from '@/lib/api-client'
import { useProjectStore } from '@/stores/managed/project-store'

import { CreateSecretDialog } from './create-secret-dialog'

vi.mock('@/lib/api-client', () => ({ managedPost: vi.fn() }))
vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/components/managed/llm/llm-secret-configurator', () => ({
  LlmSecretConfigurator: () => <div data-testid="llm-configurator">llm</div>,
}))
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: any) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: any) => <div>{children}</div>,
  DialogHeader: ({ children }: any) => <div>{children}</div>,
  DialogTitle: ({ children }: any) => <h2>{children}</h2>,
  DialogDescription: ({ children }: any) => <p>{children}</p>,
}))

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function setProject(id: string, archivedAt: string | null = null) {
  useProjectStore.setState({
    currentOrgId: 'org-a',
    currentProjectId: id,
    currentProject: {
      id,
      org_id: 'org-a',
      name: id,
      slug: id,
      is_default: true,
      archived_at: archivedAt,
      capability: 'write',
    },
    organizations: [],
    projects: [],
  })
}

function fillGenericForm() {
  fireEvent.change(screen.getByLabelText('managed.llm.configurationName'), {
    target: { value: 'github-token' },
  })
  fireEvent.change(screen.getByLabelText('managed.llm.genericKey'), {
    target: { value: 'GITHUB_TOKEN' },
  })
  fireEvent.change(screen.getByLabelText('managed.llm.genericValue'), {
    target: { value: 'ghp-secret' },
  })
}

describe('CreateSecretDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setProject('project-a')
  })

  it('defaults to inline LLM configuration', () => {
    render(<CreateSecretDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />)

    expect(screen.getByTestId('llm-configurator')).toBeTruthy()
  })

  it('hides the kind tablist when lockKind is set', () => {
    const { queryByRole } = render(
      <CreateSecretDialog
        open
        onOpenChange={() => {}}
        onCreated={() => {}}
        initialKind="generic"
        lockKind
      />,
    )
    expect(queryByRole('tablist')).toBeNull()
  })

  it('uses a specific title when the model kind is locked', () => {
    render(
      <CreateSecretDialog
        open
        onOpenChange={() => {}}
        onCreated={() => {}}
        initialKind="llm"
        lockKind
      />,
    )
    expect(
      screen.getByRole('heading', { name: 'managed.credentials.createModelConnection' }),
    ).toBeTruthy()
  })

  it('uses a specific title when the service kind is locked', () => {
    render(
      <CreateSecretDialog
        open
        onOpenChange={() => {}}
        onCreated={() => {}}
        initialKind="generic"
        lockKind
      />,
    )
    expect(
      screen.getByRole('heading', { name: 'managed.credentials.createServiceCredential' }),
    ).toBeTruthy()
  })

  it('creates an explicit service credential without provider or protocol', async () => {
    managedPostMock.mockResolvedValueOnce({
      id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
      name: 'github-token',
      kind: 'service',
      provider: null,
      protocol: null,
      model: null,
      compatible_engine_ids: [],
      is_default: false,
      data: { GITHUB_TOKEN: '********' },
      created_at: '2026-08-07T00:00:00Z',
      updated_at: '2026-08-07T00:00:00Z',
    })
    render(<CreateSecretDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />)

    fireEvent.click(screen.getByRole('tab', { name: 'managed.llm.genericSecret' }))
    fillGenericForm()
    fireEvent.click(screen.getByRole('button', { name: 'common.create' }))

    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())
    expect(managedPostMock.mock.calls[0][0]).toBe('/credentials')
    expect(managedPostMock.mock.calls[0][1]).toEqual({
      kind: 'service',
      name: 'github-token',
      data: { GITHUB_TOKEN: 'ghp-secret' },
      is_default: false,
    })
  })

  it('does not create from stale form state in the same turn as a project switch', async () => {
    render(
      <CreateSecretDialog
        open
        initialKind="generic"
        lockKind
        onOpenChange={vi.fn()}
        onCreated={vi.fn()}
      />,
    )
    fillGenericForm()

    await act(async () => {
      setProject('project-b')
      fireEvent.click(screen.getByRole('button', { name: 'common.create' }))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })

  it('ignores a create completion after the project changes', async () => {
    const create = deferred<unknown>()
    managedPostMock.mockReturnValueOnce(create.promise)
    const onCreated = vi.fn()
    const onOpenChange = vi.fn()
    render(
      <CreateSecretDialog
        open
        initialKind="generic"
        lockKind
        onOpenChange={onOpenChange}
        onCreated={onCreated}
      />,
    )
    fillGenericForm()
    fireEvent.click(screen.getByRole('button', { name: 'common.create' }))
    await waitFor(() => expect(managedPostMock).toHaveBeenCalledOnce())

    await act(async () => {
      setProject('project-b')
      await Promise.resolve()
    })
    const closeCallsAfterSwitch = onOpenChange.mock.calls.length

    await act(async () => {
      create.resolve({
        id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f099',
        name: 'github-token',
        kind: 'service',
        provider: null,
        protocol: null,
        model: null,
        compatible_engine_ids: [],
        is_default: false,
        data: { GITHUB_TOKEN: '********' },
        archived_at: null,
        created_at: '2026-08-13T00:00:00Z',
        updated_at: '2026-08-13T00:00:00Z',
      })
      await create.promise
    })

    expect(onCreated).not.toHaveBeenCalled()
    expect(onOpenChange).toHaveBeenCalledTimes(closeCallsAfterSwitch)
  })

  it('blocks submission when the current project becomes archived', async () => {
    render(
      <CreateSecretDialog
        open
        initialKind="generic"
        lockKind
        onOpenChange={vi.fn()}
        onCreated={vi.fn()}
      />,
    )
    fillGenericForm()

    await act(async () => {
      setProject('project-a', '2026-08-13T01:00:00Z')
      fireEvent.click(screen.getByRole('button', { name: 'common.create' }))
      await Promise.resolve()
    })

    expect(managedPostMock).not.toHaveBeenCalled()
  })
})
