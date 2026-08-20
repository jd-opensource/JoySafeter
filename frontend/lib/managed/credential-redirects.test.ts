import { describe, expect, it } from 'vitest'

import { resolveSecretsRedirect, resolveVaultsRedirect } from './credential-redirects'

describe('credential redirect helpers', () => {
  it('maps secrets list + create params', () => {
    expect(resolveSecretsRedirect(null)).toBe('/managed/credentials?tab=models')
    expect(resolveSecretsRedirect('llm')).toBe('/managed/credentials?tab=models&create=model')
    expect(resolveSecretsRedirect('generic')).toBe('/managed/credentials?tab=services&create=service')
    expect(resolveSecretsRedirect('custom')).toBe('/managed/credentials?tab=services&create=service')
    expect(resolveSecretsRedirect('bogus')).toBe('/managed/credentials?tab=models')
  })
  it('maps vaults list + create param', () => {
    expect(resolveVaultsRedirect(null)).toBe('/managed/credentials?tab=mcp')
    expect(resolveVaultsRedirect('1')).toBe(
      '/managed/credentials?tab=mcp&create=credential-group',
    )
  })
})
