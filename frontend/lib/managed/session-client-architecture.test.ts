import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('managed Session client architecture', () => {
  it('keeps shared Session commands out of page components', () => {
    const consumers = [
      'app/managed/quickstart/page.tsx',
      'app/managed/sessions/page.tsx',
      'app/managed/sessions/[sessionId]/page.tsx',
      'app/managed/agents/[agentId]/page.tsx',
    ]
    const commandPathPatterns = [
      /apiResourcePath\('sessions', [^,\n]+, 'events'\)/,
      /apiResourcePath\('sessions', [^,\n]+, 'stop'\)/,
      /apiResourcePath\('sessions', [^,\n]+, 'archive'\)/,
    ]

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).toContain("from '@/lib/managed/session-client'")
      for (const pattern of commandPathPatterns) {
        expect(source).not.toMatch(pattern)
      }
    }
  })

  it('keeps Session detail query identity behind the shared client', () => {
    for (const relativePath of [
      'app/managed/quickstart/page.tsx',
      'app/managed/sessions/[sessionId]/page.tsx',
    ]) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('managedSessionQueryKey(')
      expect(source).not.toMatch(/queryKey:\s*\['session'/)
    }
  })

  it('keeps Session event history and skill usage contracts out of the detail page', () => {
    const detailPage = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const refreshHook = readProjectFile('hooks/managed/use-session-skill-usage-refresh.ts')

    expect(detailPage).toContain('fetchManagedSessionEvents(')
    expect(detailPage).toContain('fetchManagedSessionSkillUsage(')
    expect(detailPage).toContain('managedSessionSkillUsageQueryKey(')
    expect(detailPage).not.toMatch(/apiResourceSubpath\('sessions', [^\n]+, \['events'\]/)
    expect(detailPage).not.toMatch(/apiResourcePath\('sessions', [^\n]+, 'skill-usage'\)/)
    expect(detailPage).not.toContain('parseSessionEventListResponse')
    expect(detailPage).not.toContain('parseSkillUsageListResponse')
    expect(refreshHook).toContain('managedSessionSkillUsageQueryKey(')
    expect(refreshHook).not.toMatch(/queryKey:\s*\['session-skill-usage'/)
  })

  it('keeps Session creation transport and response parsing behind the shared client', () => {
    const consumers = [
      'hooks/managed/use-quickstart-controller.ts',
      'app/managed/sessions/components/create-session-dialog.tsx',
      'app/managed/agents/page.tsx',
      'app/managed/agents/[agentId]/page.tsx',
    ]

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('createManagedSession(')
      expect(source).not.toMatch(/managedPost(?:<[^>]+>)?\(\s*['"]\/sessions['"]/)
      expect(source).not.toContain('parseSessionCreateResponse')
    }

    const client = readProjectFile('lib/managed/session-client.ts')
    expect(client).toContain("managedPost<unknown>(\n    '/sessions'")
    expect(client).toContain('buildManagedSessionCreateBody(input)')
    expect(client).toContain('parseSessionCreateResponse(response).id')
  })

  it('keeps Agent Session pagination and cache identity behind the shared client', () => {
    const agentPage = readProjectFile('app/managed/agents/[agentId]/page.tsx')
    const triggerDialog = readProjectFile('components/managed/triggers/create-trigger-dialog.tsx')

    expect(agentPage).toContain('fetchManagedAgentSessions(')
    expect(agentPage).toContain('managedAgentSessionsQueryKey(')
    expect(triggerDialog).toContain('useManagedAgentSessionOptions(selectedAgentId')
    for (const source of [agentPage, triggerDialog]) {
      expect(source).not.toMatch(/queryKey:\s*\['agent-sessions'/)
      expect(source).not.toMatch(/\/agents\/\$\{agentId\}\/sessions/)
      expect(source).not.toContain('parseSessionOption')
      expect(source).not.toContain('parseSessionListResponse')
    }

    expect(agentPage).toContain('managedAgentSessionsQueryPrefix(')
    expect(agentPage).not.toMatch(/apiResourceSubpath\('agents', [^\n]+, \['sessions'\]/)
    expect(agentPage).toContain('hasNext={sessionPage?.hasMore ?? false}')
    expect(agentPage).toContain('setSessionCursor(sessionPage.lastId)')
    expect(agentPage).not.toContain('filtered.slice(page * pageSize')
    expect(triggerDialog).not.toContain("agentId, 'for-trigger'")
    expect(triggerDialog).not.toContain('triggerSessionsRequest')

    const client = readProjectFile('lib/managed/session-client.ts')
    expect(client).toContain("return ['agent-sessions', scopeKey, agentId] as const")
    expect(client).toContain("apiResourceSubpath('agents', agentId, ['sessions']")
    expect(client).toContain('parseManagedCursorPage(response, {')
    expect(client).toContain('collectManagedCursorPages<Session, SessionId>')
    expect(client).not.toContain("throw new Error('Invalid Agent Session list response')")

    const paginationHook = readProjectFile('hooks/managed/use-paginated-list.ts')
    expect(paginationHook).toContain('parseManagedCursorPage(response, {')
    expect(paginationHook).not.toContain('Array.isArray(res)')
  })

  it('keeps the global Session list contract out of its page component', () => {
    const sessionPage = readProjectFile('app/managed/sessions/page.tsx')
    const sessionListHook = readProjectFile('hooks/managed/use-managed-session-list.ts')
    const client = readProjectFile('lib/managed/session-client.ts')

    expect(sessionPage).toContain('useManagedSessionList(showArchived)')
    expect(sessionPage).toContain('managedSessionsQueryPrefix(')
    expect(sessionPage).not.toContain('usePaginatedList<Session>')
    expect(sessionPage).not.toContain("path: '/sessions'")
    expect(sessionPage).not.toContain('parseSessionResponse')
    expect(sessionPage).not.toContain('parseCursor: parseSessionId')
    expect(sessionPage).not.toContain("queryKey: ['sessions'")

    expect(sessionListHook).toContain('fetchPage: fetchManagedSessions')
    expect(sessionListHook).toContain('parseCursor: parseSessionId')
    expect(sessionListHook).not.toContain("path: '/sessions'")
    expect(sessionListHook).toContain('sourceKey: MANAGED_SESSIONS_SOURCE_KEY')
    expect(client).toContain("apiCollectionPath('sessions', {")
    expect(client).toContain("parseManagedSessionPage(response, 'Session list response')")
  })
})
