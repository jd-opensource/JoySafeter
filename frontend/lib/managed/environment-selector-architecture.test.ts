import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('managed Environment selector architecture', () => {
  it('keeps selector transport, parsing, pagination, and cache identity centralized', () => {
    const environmentPage = readProjectFile('app/managed/environments/page.tsx')
    const consumers = [
      'app/managed/sessions/components/create-session-dialog.tsx',
      'components/managed/triggers/create-trigger-dialog.tsx',
      'app/managed/quickstart/page.tsx',
      'app/managed/agents/components/create-agent-dialog.tsx',
      'app/managed/agents/[agentId]/edit/page.tsx',
    ]

    expect(environmentPage).toContain('useManagedEnvironmentList(showArchived)')
    expect(environmentPage).not.toContain("path: '/environments'")
    expect(environmentPage).not.toContain('parseItem: parseEnvironmentResponse')

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useManagedEnvironmentOptions')
      expect(source).not.toMatch(/managedGet<[^>]*>\(\s*['"]\/environments/)
      expect(source).not.toContain('parseEnvironmentListResponse')
      expect(source).not.toContain('parseEnvironmentOption')
      expect(source).not.toContain('envs-for-session')
      expect(source).not.toContain('environments-active')
      expect(source).not.toContain("['environments', scope.key, 'for-trigger']")
    }

    const listHook = readProjectFile('hooks/managed/use-managed-environment-list.ts')
    const hook = readProjectFile('hooks/managed/use-managed-environment-options.ts')
    const client = readProjectFile('lib/managed/environment-client.ts')
    expect(listHook).toContain('fetchPage: fetchManagedEnvironments')
    expect(hook).toContain('managedEnvironmentOptionsQueryKey(managedScope.key)')
    expect(hook).toContain('fetchManagedEnvironmentOptions(managedScope)')
    expect(client).toContain("apiCollectionPath('environments', {")
    expect(client).toContain('collectManagedCursorPages<Environment, EnvironmentId>')
    expect(client).toContain('parseManagedCursorPage(response, {')
  })

  it('keeps Environment detail transport and project-scoped cache identity centralized', () => {
    const consumers = [
      'app/managed/environments/[envId]/page.tsx',
      'app/managed/sessions/[sessionId]/page.tsx',
    ]

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('fetchManagedEnvironment(')
      expect(source).toContain('managedEnvironmentQueryKey(')
      expect(source).not.toMatch(
        /managedGet<[^>]*>\(\s*apiResourcePath\('environments',\s*envId[^,]*\)/,
      )
      expect(source).not.toContain("queryKey: ['environment'")
    }

    const sessionPage = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const client = readProjectFile('lib/managed/environment-client.ts')
    expect(sessionPage).not.toContain("['environment', sessionScope")
    expect(client).toContain("apiResourcePath('environments', environmentId)")
    expect(client).toContain('return parseEnvironmentResponse(response)')
  })
})
