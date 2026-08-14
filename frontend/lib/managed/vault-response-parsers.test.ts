import { describe, expect, it } from 'vitest'

import {
  parseVaultCredentialListResponse,
  parseVaultCredentialResponse,
  parseVaultListResponse,
  parseVaultResponse,
} from './vault-response-parsers'

const GROUP_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f030'
const CREDENTIAL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f031'

const rawVault = () => ({
  id: `credgrp_${GROUP_UUID}`,
  name: 'mcp-prod',
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

const rawCredential = () => ({
  id: `cred_${CREDENTIAL_UUID}`,
  group_id: `credgrp_${GROUP_UUID}`,
  name: 'github-mcp',
  mcp_server_url: 'https://mcp.example.com',
  data: { token_value: '********' },
  created_at: '2026-08-06T00:00:00Z',
  updated_at: '2026-08-06T00:00:00Z',
})

describe('vault response parsers', () => {
  it('parses group and nested member IDs', () => {
    expect(parseVaultResponse(rawVault()).id).toBe(`credgrp_${GROUP_UUID}`)
    expect(parseVaultListResponse([rawVault()])[0].id).toBe(`credgrp_${GROUP_UUID}`)
    expect(parseVaultCredentialResponse(rawCredential()).id).toBe(`cred_${CREDENTIAL_UUID}`)
    expect(parseVaultCredentialListResponse([rawCredential()])[0].group_id).toBe(
      `credgrp_${GROUP_UUID}`,
    )
  })

  it('rejects bare and cross-entity IDs', () => {
    expect(() => parseVaultResponse({ ...rawVault(), id: GROUP_UUID })).toThrow()
    expect(() =>
      parseVaultCredentialResponse({ ...rawCredential(), id: `credgrp_${CREDENTIAL_UUID}` }),
    ).toThrow()
  })
})
