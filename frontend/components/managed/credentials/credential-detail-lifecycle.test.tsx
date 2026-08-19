import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routerPush = vi.fn()
const scopeMock = { orgId: 'o', projectId: 'p', key: 'o:p' }
const scopedActionControl = {
  allowBegin: true,
  current: true,
}

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('@/lib/api-client', () => ({
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
  managedDelete: vi.fn(),
}))
vi.mock('@/lib/managed/request-scope', () => ({
  useManagedRequestScope: () => scopeMock,
  managedRequestOptions: () => ({}),
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({
  useCurrentProjectReadOnly: () => false,
  currentProjectAllowsWrite: () => true,
}))
vi.mock('@/hooks/managed/use-scoped-actions', () => ({
  useScopedActions: () => ({
    scopeRef: { current: scopeMock.key },
    requestScopeRef: { current: scopeMock },
    scope: scopeMock,
    readOnly: false,
    beginAction: () =>
      scopedActionControl.allowBegin
        ? { runId: 1, scope: scopeMock.key, requestScope: scopeMock }
        : null,
    isCurrentAction: () => scopedActionControl.current,
    scopeIsActive: () => scopedActionControl.current,
    bumpRun: () => {},
  }),
}))
vi.mock('@/hooks/managed/use-llm-catalog', () => ({
  useLlmCatalog: () => ({
    isSuccess: true,
    isError: false,
    data: { version: 'v1' },
    refetch: vi.fn(),
  }),
}))
vi.mock('@/lib/managed/llm-catalog', () => ({
  findCredentialProfileForBinding: () => ({
    fields: [{ key: 'api_key', label: 'API key', type: 'secret', required: true, options: [] }],
  }),
}))
vi.mock('@/components/managed/shared/compatible-engine-badges', () => ({
  CompatibleEngineBadges: () => null,
}))
const referencesControl: { data: unknown; isLoading: boolean } = {
  data: undefined,
  isLoading: false,
}
vi.mock('@/hooks/managed/use-credential-references', () => ({
  useCredentialReferences: () => ({ data: referencesControl.data, isLoading: referencesControl.isLoading }),
  useCredentialGroupReferences: () => ({ data: referencesControl.data, isLoading: referencesControl.isLoading }),
}))

import { managedDelete, managedPost } from '@/lib/api-client'
import type { SecretDetail } from '@/types/managed'

import { ModelConnectionDetail } from './model-connection-detail'
import { ServiceCredentialDetail } from './service-credential-detail'

const managedPostMock = managedPost as unknown as ReturnType<typeof vi.fn>
const managedDeleteMock = managedDelete as unknown as ReturnType<typeof vi.fn>
const MODEL_ID = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f061'
const SERVICE_ID = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f062'

function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function credential(kind: 'model' | 'service', archivedAt: string | null): SecretDetail {
  return {
    id: (kind === 'model' ? MODEL_ID : SERVICE_ID) as SecretDetail['id'],
    name: kind === 'model' ? 'Primary model' : 'Payments service',
    kind,
    provider: kind === 'model' ? 'openai' : null,
    protocol: kind === 'model' ? 'responses' : null,
    model: kind === 'model' ? 'gpt-5' : null,
    compatible_engine_ids: [],
    is_default: false,
    data: kind === 'model' ? { api_key: 'masked' } : { token: 'masked' },
    archived_at: archivedAt,
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:00:00Z',
  }
}

function confirm(label: string) {
  const buttons = screen.getAllByRole('button', { name: label })
  fireEvent.click(buttons[buttons.length - 1])
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('credential detail lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    scopedActionControl.allowBegin = true
    scopedActionControl.current = true
    managedPostMock.mockResolvedValue({})
    managedDeleteMock.mockResolvedValue(undefined)
    referencesControl.data = undefined
    referencesControl.isLoading = false
  })

  it('blocks archive when the credential is referenced', async () => {
    referencesControl.data = {
      references: [
        { surface: 'agent_model_binding', resourceType: 'agent', id: 'a1', name: '客服机器人' },
      ],
      otherCount: 0,
      canArchive: false,
      canDelete: false,
    }
    render(
      <Wrap>
        <ModelConnectionDetail credential={credential('model', null)} />
      </Wrap>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.archive' }))

    expect(screen.getAllByText('客服机器人').length).toBeGreaterThan(0)
    const archiveButtons = screen.getAllByRole('button', { name: /archive|归档|common\.archive/i })
    expect(archiveButtons[archiveButtons.length - 1]).toBeDisabled()
  })

  it('archives and sets default from an active model connection detail', async () => {
    render(
      <Wrap>
        <ModelConnectionDetail credential={credential('model', null)} />
      </Wrap>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.archive' }))
    expect(managedPostMock).not.toHaveBeenCalled()
    confirm('common.archive')
    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credentials/${MODEL_ID}/archive`,
        {},
        expect.anything(),
      ),
    )

    fireEvent.click(screen.getByRole('button', { name: 'managed.secrets.setDefault' }))
    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credentials/${MODEL_ID}/default`,
        {},
        expect.anything(),
      ),
    )
  })

  it('makes an archived model connection read-only and restores it', async () => {
    render(
      <Wrap>
        <ModelConnectionDetail credential={credential('model', '2026-08-12T00:00:00Z')} />
      </Wrap>,
    )

    expect(screen.queryByRole('button', { name: 'common.save' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'managed.secrets.setDefault' })).toBeNull()
    expect(screen.getByDisplayValue('masked')).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'common.restore' }))
    confirm('common.restore')
    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credentials/${MODEL_ID}/restore`,
        {},
        expect.anything(),
      ),
    )
  })

  it('blocks archive of a referenced service credential', async () => {
    referencesControl.data = {
      references: [
        { surface: 'environment_injection', resourceType: 'environment', id: 'e1', name: '生产环境' },
      ],
      otherCount: 0,
      canArchive: false,
      canDelete: false,
    }
    render(
      <Wrap>
        <ServiceCredentialDetail credential={credential('service', null)} />
      </Wrap>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.archive' }))

    expect(screen.getAllByText('生产环境').length).toBeGreaterThan(0)
    const archiveButtons = screen.getAllByRole('button', { name: /archive|归档|common\.archive/i })
    expect(archiveButtons[archiveButtons.length - 1]).toBeDisabled()
  })

  it('archives an active service credential and restores an archived one', async () => {
    const view = render(
      <Wrap>
        <ServiceCredentialDetail credential={credential('service', null)} />
      </Wrap>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.archive' }))
    confirm('common.archive')
    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credentials/${SERVICE_ID}/archive`,
        {},
        expect.anything(),
      ),
    )

    view.rerender(
      <Wrap>
        <ServiceCredentialDetail credential={credential('service', '2026-08-12T00:00:00Z')} />
      </Wrap>,
    )
    expect(screen.queryByRole('button', { name: 'common.save' })).toBeNull()
    expect(screen.getByDisplayValue('masked')).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'common.restore' }))
    confirm('common.restore')
    await waitFor(() =>
      expect(managedPostMock).toHaveBeenCalledWith(
        `/credentials/${SERVICE_ID}/restore`,
        {},
        expect.anything(),
      ),
    )
  })

  it('deletes a credential from detail and returns to its kind list', async () => {
    render(
      <Wrap>
        <ServiceCredentialDetail credential={credential('service', null)} />
      </Wrap>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.delete' }))
    confirm('common.delete')

    await waitFor(() =>
      expect(managedDeleteMock).toHaveBeenCalledWith(
        `/credentials/${SERVICE_ID}`,
        expect.anything(),
      ),
    )
    expect(routerPush).toHaveBeenCalledWith('/managed/credentials?tab=services')
  })

  it('allows permanent delete from an archived credential detail', async () => {
    render(
      <Wrap>
        <ServiceCredentialDetail credential={credential('service', '2026-08-12T00:00:00Z')} />
      </Wrap>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.delete' }))
    confirm('common.delete')

    await waitFor(() =>
      expect(managedDeleteMock).toHaveBeenCalledWith(
        `/credentials/${SERVICE_ID}`,
        expect.anything(),
      ),
    )
  })

  it('does not start a lifecycle request after the managed scope becomes stale', async () => {
    render(
      <Wrap>
        <ModelConnectionDetail credential={credential('model', null)} />
      </Wrap>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.archive' }))
    scopedActionControl.allowBegin = false
    confirm('common.archive')

    await waitFor(() => expect(managedPostMock).not.toHaveBeenCalled())
  })

  it.each([
    ['model', ModelConnectionDetail, MODEL_ID, '/managed/credentials?tab=models'],
    ['service', ServiceCredentialDetail, SERVICE_ID, '/managed/credentials?tab=services'],
  ] as const)(
    'ignores a stale %s delete completion instead of navigating the new scope',
    async (kind, Detail, id, destination) => {
      const pendingDelete = deferred<void>()
      managedDeleteMock.mockReturnValueOnce(pendingDelete.promise)
      render(
        <Wrap>
          <Detail credential={credential(kind, null)} />
        </Wrap>,
      )

      fireEvent.click(screen.getByRole('button', { name: 'common.delete' }))
      confirm('common.delete')
      await waitFor(() =>
        expect(managedDeleteMock).toHaveBeenCalledWith(`/credentials/${id}`, expect.anything()),
      )

      scopedActionControl.current = false
      await act(async () => {
        pendingDelete.resolve()
        await pendingDelete.promise
      })

      expect(routerPush).not.toHaveBeenCalledWith(destination)
    },
  )

  it('syncs refreshed model data only while the form is pristine', () => {
    const initial = credential('model', null)
    const view = render(
      <Wrap>
        <ModelConnectionDetail credential={initial} />
      </Wrap>,
    )

    view.rerender(
      <Wrap>
        <ModelConnectionDetail credential={{ ...initial, data: { api_key: 'refreshed' } }} />
      </Wrap>,
    )
    expect(screen.getByDisplayValue('refreshed')).toBeInTheDocument()

    fireEvent.change(screen.getByDisplayValue('refreshed'), { target: { value: 'local edit' } })
    view.rerender(
      <Wrap>
        <ModelConnectionDetail credential={{ ...initial, data: { api_key: 'new server value' } }} />
      </Wrap>,
    )
    expect(screen.getByDisplayValue('local edit')).toBeInTheDocument()
  })

  it('syncs refreshed service data only while the form is pristine', () => {
    const initial = credential('service', null)
    const view = render(
      <Wrap>
        <ServiceCredentialDetail credential={initial} />
      </Wrap>,
    )

    view.rerender(
      <Wrap>
        <ServiceCredentialDetail credential={{ ...initial, data: { token: 'refreshed' } }} />
      </Wrap>,
    )
    expect(screen.getByDisplayValue('refreshed')).toBeInTheDocument()

    fireEvent.change(screen.getByDisplayValue('refreshed'), { target: { value: 'local edit' } })
    view.rerender(
      <Wrap>
        <ServiceCredentialDetail credential={{ ...initial, data: { token: 'new server value' } }} />
      </Wrap>,
    )
    expect(screen.getByDisplayValue('local edit')).toBeInTheDocument()
  })
})
