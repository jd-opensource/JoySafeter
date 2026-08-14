import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const replaceMock = vi.fn()
const pushMock = vi.fn()
// Real Next useRouter() returns a STABLE reference; a fresh object per render would
// re-fire the shell's router-dependent effects every render (infinite loop / OOM).
const routerMock = { replace: replaceMock, push: pushMock }
let searchParamsValue = new URLSearchParams('')
let readOnlyValue = false

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
  useSearchParams: () => searchParamsValue,
}))
vi.mock('@/hooks/managed/use-current-project-read-only', () => ({ useCurrentProjectReadOnly: () => readOnlyValue }))
vi.mock('@/lib/managed/request-scope', () => ({ useManagedRequestScope: () => ({ orgId: 'o', projectId: 'p', key: 'o:p' }) }))
vi.mock('./model-connection-list', () => ({ ModelConnectionList: ({ onCreate }: { onCreate: () => void }) => <button onClick={onCreate}>model-add</button> }))
vi.mock('./service-credential-list', () => ({ ServiceCredentialList: ({ onCreate }: { onCreate: () => void }) => <button onClick={onCreate}>service-add</button> }))
vi.mock('./mcp-vault-list', () => ({ McpVaultList: ({ onCreate }: { onCreate: () => void }) => <button onClick={onCreate}>vault-add</button> }))
vi.mock('./credential-kind-chooser', () => ({ CredentialKindChooser: ({ open }: { open: boolean }) => (open ? <div>chooser-open</div> : null) }))
vi.mock('@/app/managed/secrets/components/create-secret-dialog', () => ({
  CreateSecretDialog: ({ open, initialKind, lockKind }: { open: boolean; initialKind?: string; lockKind?: boolean }) =>
    open ? <div>{`secret-dialog:${initialKind}:${String(lockKind)}`}</div> : null,
}))
vi.mock('@/app/managed/vaults/components/create-vault-dialog', () => ({
  CreateVaultDialog: ({ open }: { open: boolean }) => (open ? <div>vault-dialog</div> : null),
}))
vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children, value }: { children: ReactNode; value: string }) => <button data-tab={value}>{children}</button>,
}))

import { CredentialManagementShell } from './credential-management-shell'

function Wrap({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('CredentialManagementShell', () => {
  beforeEach(() => {
    replaceMock.mockClear()
    pushMock.mockClear()
    searchParamsValue = new URLSearchParams('')
    readOnlyValue = false
  })

  it('normalizes an illegal tab to models via replace', async () => {
    searchParamsValue = new URLSearchParams('tab=bogus')
    render(<Wrap><CredentialManagementShell /></Wrap>)
    await waitFor(() => expect((replaceMock.mock.calls.at(-1)?.[0] as string) ?? '').toContain('tab=models'))
  })

  it('consumes create=vault: opens vault dialog, normalizes tab=mcp, strips create', async () => {
    searchParamsValue = new URLSearchParams('tab=models&create=vault')
    const { getByText } = render(<Wrap><CredentialManagementShell /></Wrap>)
    await waitFor(() => expect(getByText('vault-dialog')).toBeTruthy())
    const url = replaceMock.mock.calls.at(-1)![0] as string
    expect(url).toContain('tab=mcp')
    expect(url).not.toContain('create=')
  })

  it('consumes create=service: opens generic secret dialog locked', async () => {
    searchParamsValue = new URLSearchParams('tab=models&create=service')
    const { getByText } = render(<Wrap><CredentialManagementShell /></Wrap>)
    await waitFor(() => expect(getByText('secret-dialog:generic:true')).toBeTruthy())
  })

  it('does NOT open a create dialog from create=* for a read-only project', async () => {
    readOnlyValue = true
    searchParamsValue = new URLSearchParams('tab=services&create=service')
    const { queryByText } = render(<Wrap><CredentialManagementShell /></Wrap>)
    await waitFor(() => expect(replaceMock).toHaveBeenCalled())
    expect(queryByText('secret-dialog:generic:true')).toBeNull()
    expect((replaceMock.mock.calls.at(-1)![0] as string)).not.toContain('create=')
  })

  it('per-tab Add on services tab opens generic locked dialog', async () => {
    searchParamsValue = new URLSearchParams('tab=services')
    const { getByText } = render(<Wrap><CredentialManagementShell /></Wrap>)
    fireEvent.click(getByText('service-add'))
    await waitFor(() => expect(getByText('secret-dialog:generic:true')).toBeTruthy())
  })
})
