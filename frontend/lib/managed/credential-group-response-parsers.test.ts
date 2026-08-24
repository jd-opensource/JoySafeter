import { describe, expect, it } from 'vitest'

import { parseCredentialGroupCredentialResponse } from './credential-group-response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'
const GROUP_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'

function rawMember() {
  return {
    id: `cred_${UUID}`,
    kind: 'mcp',
    name: 'docs',
    data: { token_value: '********' },
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    mcp_server_url: 'https://example.com/mcp',
    group_id: `credgrp_${GROUP_UUID}`,
    auth_scheme: 'header_api_key',
    archived_at: null,
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
  }
}

describe('credential group response parsers', () => {
  it('accepts canonical masked MCP members', () => {
    expect(parseCredentialGroupCredentialResponse(rawMember())).toMatchObject({
      id: `cred_${UUID}`,
      group_id: `credgrp_${GROUP_UUID}`,
      auth_scheme: 'header_api_key',
      data: { token_value: '********' },
    })
  })

  it('rejects legacy MCP authentication aliases', () => {
    expect(() =>
      parseCredentialGroupCredentialResponse({ ...rawMember(), auth_scheme: 'bearer' }),
    ).toThrow()
  })
})
