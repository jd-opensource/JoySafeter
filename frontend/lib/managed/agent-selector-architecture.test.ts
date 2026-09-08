import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('managed Agent list architecture', () => {
  it('keeps Agent list transport and selector catalogs behind the shared client', () => {
    const agentPage = readProjectFile('app/managed/agents/page.tsx')
    const selectors = [
      'app/managed/sessions/components/create-session-dialog.tsx',
      'components/managed/triggers/create-trigger-dialog.tsx',
      'app/managed/analytics/page.tsx',
      'app/managed/analytics/calls/page.tsx',
    ]

    expect(agentPage).toContain('useManagedAgentList(showArchived)')
    expect(agentPage).not.toContain("path: '/agents'")
    expect(agentPage).not.toContain('parseItem: parseAgentResponse')

    for (const relativePath of selectors) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useManagedAgentOptions')
      expect(source).not.toMatch(/managedGet<[^>]*>\(\s*['"]\/agents/)
      expect(source).not.toContain('parseAgentListResponse')
      expect(source).not.toContain('parseAgentOption')
      expect(source).not.toContain('agents-for-session')
      expect(source).not.toContain("['agents', scope.key, 'for-trigger']")
      expect(source).not.toContain('/agents?limit=100')
    }

    expect(readProjectFile('lib/managed/analytics/hooks.ts')).not.toContain('useAgentsForFilters')

    const listHook = readProjectFile('hooks/managed/use-managed-agent-list.ts')
    const optionsHook = readProjectFile('hooks/managed/use-managed-agent-options.ts')
    const client = readProjectFile('lib/managed/agent-client.ts')
    expect(listHook).toContain('fetchPage: fetchManagedAgents')
    expect(optionsHook).toContain('fetchManagedAgentOptions(managedScope)')
    expect(client).toContain("apiCollectionPath('agents', {")
    expect(client).toContain('parseItem: parseAgentResponse')
  })

  it('keeps Agent detail transport and cache identity behind the shared client', () => {
    const consumers = [
      'app/managed/agents/[agentId]/page.tsx',
      'app/managed/agents/[agentId]/edit/page.tsx',
      'app/managed/sessions/[sessionId]/page.tsx',
    ]

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('fetchManagedAgent(')
      expect(source).toContain('managedAgentQueryKey(')
      expect(source).not.toMatch(
        /managedGet<[^>]*>\(\s*apiResourcePath\('agents',\s*agentId[^,]*\)/,
      )
      expect(source).not.toContain("queryKey: ['agent'")
    }

    const sessionPage = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const client = readProjectFile('lib/managed/agent-client.ts')
    expect(sessionPage).not.toContain("['agent', sessionScope")
    expect(client).toContain("apiResourcePath('agents', agentId)")
    expect(client).toContain('return parseAgentResponse(response)')
  })

  it('keeps complete Agent version history behind one project-scoped query identity', () => {
    const agentPage = readProjectFile('app/managed/agents/[agentId]/page.tsx')
    const editPage = readProjectFile('app/managed/agents/[agentId]/edit/page.tsx')
    const sessionPage = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const client = readProjectFile('lib/managed/agent-client.ts')

    expect(agentPage).toContain('fetchManagedAgentVersionHistory(agentId, managedScope)')
    expect(sessionPage).toContain('fetchManagedAgentVersionHistory(agentId!, requestScope)')
    expect(editPage).toContain('managedAgentVersionsQueryKey(requestScope.key, agentId)')
    expect(agentPage).not.toContain("queryKey: ['agent-versions'")
    expect(sessionPage).not.toContain("queryKey: ['agent-versions'")
    expect(sessionPage).not.toContain("['agent-versions', queryScope")
    expect(client).toContain('before_version: request.beforeVersion')
    expect(client).toContain('page.versions.at(-1)?.version')
  })
})
