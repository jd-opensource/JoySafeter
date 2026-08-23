import { describe, expect, it } from 'vitest'

import { quickstartCredentialGroupRecommendation } from './quickstart-credential-group-recommendation'

describe('quickstartCredentialGroupRecommendation', () => {
  it('extracts name, MCP server URL, and credential name and requires a credential', () => {
    expect(
      quickstartCredentialGroupRecommendation({
        name: '  GitHub tools  ',
        description: 'Authorize GitHub MCP',
        mcp_server_url: '  https://mcp.github.example  ',
        credential_name: '  GitHub token  ',
      }),
    ).toEqual({
      name: 'GitHub tools',
      mcpServerUrl: 'https://mcp.github.example',
      credentialName: 'GitHub token',
      requiresCredential: true,
    })
  })

  it('does not require a credential when no MCP server URL is recommended', () => {
    expect(quickstartCredentialGroupRecommendation({ name: 'Named group' })).toEqual({
      name: 'Named group',
      mcpServerUrl: '',
      credentialName: '',
      requiresCredential: false,
    })
  })

  it('returns empty defaults for missing config', () => {
    expect(quickstartCredentialGroupRecommendation(undefined)).toEqual({
      name: '',
      mcpServerUrl: '',
      credentialName: '',
      requiresCredential: false,
    })
  })
})
