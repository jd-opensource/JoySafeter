import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('MCP credential member lifecycle', () => {
  it('archives members without deleting their history', () => {
    const source = readFileSync(
      path.join(process.cwd(), 'components/managed/credentials/mcp-vault-detail.tsx'),
      'utf8',
    )

    expect(source).toContain(
      "apiResourcePath('credential-groups', vaultId, 'members', credId!, 'archive')",
    )
    expect(source).not.toContain(
      "managedDelete(\n        apiResourcePath('credential-groups', vaultId, 'members', credId!)",
    )
  })
})
