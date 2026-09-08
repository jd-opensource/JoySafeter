import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedDelete, managedGet, managedPatch, managedPost } from '@/lib/api-client'
import { ORGANIZATION_ID, PROJECT_ID } from '@/test-utils/entity-ids'
import { parseCredentialId } from '@/types/entity-id'

import {
  changeManagedCredentialLifecycle,
  createManagedCredential,
  deleteManagedCredential,
  fetchManagedCredential,
  fetchManagedCredentials,
  managedCredentialQueryKey,
  managedCredentialsQueryPrefix,
  serviceCredentialsQueryKey,
  setManagedCredentialDefault,
  testManagedCredential,
  updateManagedCredential,
} from './credential-client'

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPatch: vi.fn(),
  managedPost: vi.fn(),
}))

const CREDENTIAL_ID = parseCredentialId('cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f120')
const scope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}
const requestOptions = expect.objectContaining({ skipManagedContext: true })

function rawCredential() {
  return {
    id: CREDENTIAL_ID,
    name: 'service-token',
    kind: 'service',
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    data: { TOKEN: '********' },
    archived_at: null,
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
  }
}

describe('managed Credential client', () => {
  beforeEach(() => {
    vi.mocked(managedDelete).mockReset()
    vi.mocked(managedGet).mockReset()
    vi.mocked(managedPatch).mockReset()
    vi.mocked(managedPost).mockReset()
  })

  it('owns list, detail, and canonical cache identities', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawCredential()],
        has_more: false,
        first_id: CREDENTIAL_ID,
        last_id: CREDENTIAL_ID,
      })
      .mockResolvedValueOnce(rawCredential())

    await expect(
      fetchManagedCredentials({ limit: 25, kind: 'service', includeArchived: false }, scope),
    ).resolves.toMatchObject({ items: [expect.objectContaining({ id: CREDENTIAL_ID })] })
    expect(managedGet).toHaveBeenNthCalledWith(
      1,
      '/credentials?limit=25&kind=service&include_archived=false',
      requestOptions,
    )

    await expect(fetchManagedCredential(CREDENTIAL_ID, scope)).resolves.toMatchObject({
      id: CREDENTIAL_ID,
    })
    expect(managedGet).toHaveBeenNthCalledWith(2, `/credentials/${CREDENTIAL_ID}`, requestOptions)
    expect(managedCredentialQueryKey(scope.key, CREDENTIAL_ID)).toEqual([
      'credential-detail',
      scope.key,
      CREDENTIAL_ID,
    ])
    expect(managedCredentialsQueryPrefix(scope.key)).toEqual(['credentials', scope.key])
    expect(serviceCredentialsQueryKey(scope.key)).toEqual([
      'credentials',
      scope.key,
      'options',
      'service',
      false,
    ])
  })

  it('owns create, update, default, lifecycle, and delete contracts', async () => {
    vi.mocked(managedPost).mockResolvedValue(rawCredential())
    vi.mocked(managedPatch).mockResolvedValue(rawCredential())
    vi.mocked(managedDelete).mockResolvedValue(undefined)

    await createManagedCredential(
      { kind: 'service', name: 'service-token', data: { TOKEN: 'secret' }, isDefault: false },
      scope,
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      1,
      '/credentials',
      {
        kind: 'service',
        name: 'service-token',
        data: { TOKEN: 'secret' },
        is_default: false,
      },
      requestOptions,
    )

    await updateManagedCredential(CREDENTIAL_ID, { data: { TOKEN: 'rotated' } }, scope)
    expect(managedPatch).toHaveBeenCalledWith(
      `/credentials/${CREDENTIAL_ID}`,
      { data: { TOKEN: 'rotated' } },
      requestOptions,
    )

    await setManagedCredentialDefault(CREDENTIAL_ID, scope)
    expect(managedPost).toHaveBeenNthCalledWith(
      2,
      `/credentials/${CREDENTIAL_ID}/default`,
      {},
      requestOptions,
    )

    await changeManagedCredentialLifecycle(CREDENTIAL_ID, 'archive', scope)
    expect(managedPost).toHaveBeenNthCalledWith(
      3,
      `/credentials/${CREDENTIAL_ID}/archive`,
      {},
      requestOptions,
    )

    await deleteManagedCredential(CREDENTIAL_ID, scope)
    expect(managedDelete).toHaveBeenCalledWith(`/credentials/${CREDENTIAL_ID}`, requestOptions)
  })

  it('owns connectivity test payload mapping and validation', async () => {
    vi.mocked(managedPost).mockResolvedValue({ ok: true, message: 'Connected' })

    await expect(
      testManagedCredential(
        {
          provider: 'anthropic',
          protocol: 'anthropic_messages',
          data: { ANTHROPIC_API_KEY: 'secret' },
          authScheme: 'x-api-key',
        },
        scope,
      ),
    ).resolves.toEqual({ ok: true, message: 'Connected' })
    expect(managedPost).toHaveBeenCalledWith(
      '/credentials/test',
      {
        provider: 'anthropic',
        protocol: 'anthropic_messages',
        data: { ANTHROPIC_API_KEY: 'secret' },
        auth_scheme: 'x-api-key',
      },
      requestOptions,
    )

    vi.mocked(managedPost).mockResolvedValueOnce({ ok: 'yes', message: 'Connected' })
    await expect(
      testManagedCredential({ provider: 'openai', protocol: 'openai_responses', data: {} }, scope),
    ).rejects.toThrow('Expected Credential test response fields to be valid')
  })
})
