import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('MCP credential member lifecycle', () => {
  it('uses the archive operation for the archive action', () => {
    const source = readFileSync(
      path.join(process.cwd(), 'components/managed/credentials/mcp-credential-group-detail.tsx'),
      'utf8',
    )

    expect(source).toContain(
      "apiResourcePath('credential-groups', credentialGroupId, 'members', credId!, 'archive')",
    )
  })

  it('exposes restore and delete operations for archived members', () => {
    const source = readFileSync(
      path.join(process.cwd(), 'components/managed/credentials/mcp-credential-group-detail.tsx'),
      'utf8',
    )

    expect(source).toContain("apiResourcePath('credentials', credId!, 'restore')")
    expect(source).toContain(
      "apiResourcePath('credential-groups', credentialGroupId, 'members', credId!)",
    )
  })

  it('exposes restore and delete operations for archived groups', () => {
    const source = readFileSync(
      path.join(process.cwd(), 'components/managed/credentials/mcp-credential-group-list.tsx'),
      'utf8',
    )

    expect(source).toContain("apiResourcePath('credential-groups', credentialGroup.id, 'restore')")
    expect(source).toContain("apiResourcePath('credential-groups', credentialGroup.id)")
  })
})
