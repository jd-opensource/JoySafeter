import { describe, expect, it } from 'vitest'

import {
  parseVaultCredentialListResponse,
  parseVaultCredentialResponse,
  parseVaultListResponse,
  parseVaultResponse,
} from './vault-response-parsers'

const VAULT_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f030'
const CREDENTIAL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f031'

const rawVault = () => ({
  id: `vault_${VAULT_UUID}`,
  name: 'mcp-prod',
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

const rawCredential = () => ({
  id: `cred_${CREDENTIAL_UUID}`,
  vault_id: `vault_${VAULT_UUID}`,
  name: 'github-mcp',
  credential_type: 'static_bearer',
  mcp_server_url: 'https://mcp.example.com',
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

describe('vault response parsers', () => {
  it('parses vault and nested credential IDs', () => {
    expect(parseVaultResponse(rawVault()).id).toBe(`vault_${VAULT_UUID}`)
    expect(parseVaultListResponse([rawVault()])[0].id).toBe(`vault_${VAULT_UUID}`)
    expect(parseVaultCredentialResponse(rawCredential()).id).toBe(`cred_${CREDENTIAL_UUID}`)
    expect(parseVaultCredentialListResponse([rawCredential()])[0].vault_id).toBe(
      `vault_${VAULT_UUID}`,
    )
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseVaultResponse({ ...rawVault(), id: VAULT_UUID })).toThrow()
    expect(() =>
      parseVaultCredentialResponse({ ...rawCredential(), id: `vault_${CREDENTIAL_UUID}` }),
    ).toThrow()
  })
})
