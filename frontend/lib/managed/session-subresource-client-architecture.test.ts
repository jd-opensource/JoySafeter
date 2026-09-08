import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('managed Session subresource client architecture', () => {
  it('keeps resource transport and parsing out of the Session page', () => {
    const page = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const client = readProjectFile('lib/managed/session-resource-client.ts')

    expect(page).toContain("from '@/lib/managed/session-resource-client'")
    expect(page).not.toMatch(/apiResourcePath\('sessions', [^\n]+, 'resources'/)
    expect(page).not.toContain('parseSessionResourceListResponse')
    expect(page).not.toContain('parseSessionFileResourceResponse')
    expect(page).not.toContain('parseSessionRepoResourceResponse')
    expect(client).toContain("apiResourcePath('sessions', sessionId, 'resources'")
    expect(client).toContain('parseSessionResourceListResponse(response.data)')
  })

  it('keeps sandbox file transport, types, and query keys out of the Session page', () => {
    const page = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const client = readProjectFile('lib/managed/session-sandbox-client.ts')

    expect(page).toContain("from '@/lib/managed/session-sandbox-client'")
    expect(page).not.toMatch(/apiResourceSubpath\('sessions', [^\n]+, \['sandbox', 'files'/)
    expect(page).not.toContain("file_type: 'file' | 'directory'")
    expect(page).not.toContain('entry.file_type')
    expect(client).toContain("type: 'file' | 'directory' | string")
    expect(client).toContain("['sandbox', 'files', options.archive ? 'archive' : 'raw']")
  })
})
