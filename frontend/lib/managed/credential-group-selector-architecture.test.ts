import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('managed Credential Group list architecture', () => {
  it('keeps list transport and selector catalogs behind the shared client', () => {
    const listPage = readProjectFile('components/managed/credentials/mcp-credential-group-list.tsx')
    const selectors = [
      'app/managed/sessions/components/create-session-dialog.tsx',
      'app/managed/quickstart/page.tsx',
    ]

    expect(listPage).toContain('useManagedCredentialGroupList({')
    expect(listPage).not.toContain("path: '/credential-groups'")
    expect(listPage).not.toContain('parseItem: parseCredentialGroupResponse')

    for (const relativePath of selectors) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useManagedCredentialGroupOptions')
      expect(source).not.toMatch(/managedGet<[^>]*>\(\s*['"]\/credential-groups['"]/)
      expect(source).not.toContain('parseCredentialGroupListResponse')
      expect(source).not.toContain('credential-groups-for-session')
      expect(source).not.toContain('credential-groups-active')
    }

    const listHook = readProjectFile('hooks/managed/use-managed-credential-group-list.ts')
    const optionsHook = readProjectFile('hooks/managed/use-managed-credential-group-options.ts')
    const client = readProjectFile('lib/managed/credential-group-client.ts')
    expect(listHook).toContain('fetchPage: fetchManagedCredentialGroups')
    expect(optionsHook).toContain('fetchManagedCredentialGroupOptions(managedScope)')
    expect(client).toContain("apiCollectionPath('credential-groups', {")
    expect(client).toContain('parseItem: parseCredentialGroupResponse')
  })

  it('keeps detail and member transport behind the same domain client', () => {
    const consumers = [
      'components/managed/credentials/mcp-credential-group-detail.tsx',
      'app/managed/sessions/components/create-session-dialog.tsx',
      'app/managed/sessions/[sessionId]/page.tsx',
      'app/managed/quickstart/page.tsx',
    ]

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).not.toMatch(/apiResourceSubpath\('credential-groups',[\s\S]*?\['members'\]/)
      expect(source).not.toContain('parseCredentialGroupCredentialListResponse')
      expect(source).not.toContain("['credential-group-members'")
    }

    const detail = readProjectFile('components/managed/credentials/mcp-credential-group-detail.tsx')
    const client = readProjectFile('lib/managed/credential-group-client.ts')
    expect(detail).toContain('fetchManagedCredentialGroup(')
    expect(detail).toContain('fetchManagedCredentialGroupMembers(')
    expect(client).toContain("apiResourcePath('credential-groups', credentialGroupId)")
    expect(client).toContain(
      "apiResourceSubpath('credential-groups', credentialGroupId, ['members']",
    )
    expect(client).toContain('include_archived: includeArchived')
    expect(client).not.toContain('limit: 100')
  })
})
