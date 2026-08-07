import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const TEST_FILE_PATTERN = /\.(?:test|spec)\.(?:ts|tsx)$/
const QUOTED_CORE_ID_PATTERN =
  /["'`]((?:agent_|sess_|task_|trig_|env_|secret_|vault_|cred_|sbx_|memstore_|memver_|mem_|skill_|sklfile_|sklscan_|sklver_|sklvfile_|skluse_|file_|sesrsc_|evt_)[^"'`\s]*)["'`]/g
const CANONICAL_CORE_ID_PATTERN =
  /^(?:agent_|sess_|task_|trig_|env_|secret_|vault_|cred_|sbx_|memstore_|memver_|mem_|skill_|sklfile_|sklscan_|sklver_|sklvfile_|skluse_|file_|sesrsc_|evt_)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function collectTestFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) return []
    const entryPath = path.join(directory, entry.name)
    if (entry.isDirectory()) return collectTestFiles(entryPath)
    return TEST_FILE_PATTERN.test(entry.name) ? [entryPath] : []
  })
}

function readProjectFile(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), 'utf8')
}

describe('typed entity id architecture', () => {
  it('keeps core entity fixtures canonical', () => {
    const violations: string[] = []
    for (const file of collectTestFiles(process.cwd())) {
      if (file.endsWith('entity-id.test.ts') || file.endsWith('entity-id-architecture.test.ts')) {
        continue
      }
      const source = readFileSync(file, 'utf8')
      for (const match of source.matchAll(QUOTED_CORE_ID_PATTERN)) {
        if (
          match[1].includes('${') ||
          match[1].startsWith('agent_toolset_') ||
          ['secret_ref', 'secret_key', 'secret_data'].includes(match[1])
        )
          continue
        if (!CANONICAL_CORE_ID_PATTERN.test(match[1])) {
          violations.push(`${path.relative(process.cwd(), file)}: ${match[1]}`)
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('parses route and stream ids at the frontend boundary', () => {
    expect(readProjectFile('lib/managed/sse.ts')).toContain('sessionId: SessionId | null')
    expect(readProjectFile('app/managed/agents/[agentId]/page.tsx')).toContain(
      'parseAgentId(rawAgentId)',
    )
    expect(readProjectFile('app/managed/agents/[agentId]/edit/page.tsx')).toContain(
      'parseAgentId(rawAgentId)',
    )
    expect(readProjectFile('app/managed/sessions/[sessionId]/page.tsx')).toContain(
      'parseSessionId(rawSessionId)',
    )
    expect(readProjectFile('app/managed/triggers/[triggerId]/page.tsx')).toContain(
      'parseTriggerId(rawId)',
    )
    expect(readProjectFile('app/managed/environments/[envId]/page.tsx')).toContain(
      'parseEnvironmentId(rawId)',
    )
  })

  it('does not strip canonical session ids in quickstart runtime flows', () => {
    const source = readProjectFile('app/managed/quickstart/page.tsx')

    expect(source).toContain('parseSessionId(rawSessionId)')
    expect(source).not.toContain('stripIdPrefix(currentSession.id)')
  })

  it('runtime-validates Agent and Session responses at every core ingress', () => {
    const agentParsers = readProjectFile('lib/managed/agent-response-parsers.ts')
    const sessionParsers = readProjectFile('lib/managed/session-response-parsers.ts')
    const agentList = readProjectFile('app/managed/agents/page.tsx')
    const agentDetail = readProjectFile('app/managed/agents/[agentId]/page.tsx')
    const sessionList = readProjectFile('app/managed/sessions/page.tsx')
    const sessionDetail = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')

    expect(agentParsers).toContain('id: parseAgentId(raw.id)')
    expect(agentParsers).toContain('skill_id: parseSkillId(skill.skill_id)')
    expect(sessionParsers).toContain('id: parseSessionId(raw.id)')
    expect(sessionParsers).toContain('vault_ids: raw.vault_ids?.map(parseVaultId)')
    expect(agentList).toContain('parseItem: parseAgentResponse')
    expect(agentDetail).toContain('.then(parseAgentResponse)')
    expect(sessionList).toContain('parseItem: parseSessionResponse')
    expect(sessionDetail).toContain('.then(parseSessionResponse)')
  })

  it('runtime-validates analytics response ids before branding them', () => {
    const hooks = readProjectFile('lib/managed/analytics/hooks.ts')
    const parsers = readProjectFile('lib/managed/analytics/response-parsers.ts')

    expect(hooks).toContain('parseCallsListResponse')
    expect(hooks).toContain('parseAgentMetricsResponse')
    expect(hooks).toContain('parseHealthCheckResponse')
    expect(hooks).toContain('parseAgentRankingResponse')
    expect(parsers).toContain('id: parseTaskId(record.id)')
    expect(parsers).toContain('session_id: parseNullableId<SessionId>')
    expect(parsers).toContain('agent_id: parseNullableId<AgentId>')
  })

  it('keeps trigger hooks and response data typed end-to-end', () => {
    const hooks = readProjectFile('lib/managed/triggers.ts')
    const parsers = readProjectFile('lib/managed/trigger-response-parsers.ts')

    expect(hooks).toContain('useTestFireWebhook(triggerId: TriggerId)')
    expect(hooks).toContain('useWebhookSample(triggerId: TriggerId | undefined')
    expect(hooks).toContain('parseItem: parseTriggerRunResponse')
    expect(hooks).not.toMatch(/triggerId:\s*string/)
    expect(parsers).toContain('id: parseTriggerId(response.id)')
    expect(parsers).toContain('trigger_id: parseNullableId<TriggerId>')
    expect(parsers).toContain('id: parseTaskId(raw.id)')
  })

  it('keeps environment routes and response data typed end-to-end', () => {
    const listPage = readProjectFile('app/managed/environments/page.tsx')
    const parsers = readProjectFile('lib/managed/environment-response-parsers.ts')
    const storageParsers = readProjectFile('lib/managed/storage-mount-response-parsers.ts')

    expect(listPage).toContain('parseItem: parseEnvironmentResponse')
    expect(parsers).toContain('id: parseEnvironmentId(raw.id)')
    expect(readProjectFile('lib/managed/api-paths.ts')).toContain(
      "isEntityId(value, 'environment')",
    )
    expect(storageParsers).toContain('environment_id: parseOptionalId<EnvironmentId>')
  })

  it('keeps secret routes and response data typed end-to-end', () => {
    const listPage = readProjectFile('app/managed/secrets/page.tsx')
    const detailPage = readProjectFile('app/managed/secrets/[secretId]/page.tsx')
    const parsers = readProjectFile('lib/managed/secret-response-parsers.ts')

    expect(listPage).toContain('parseItem: parseSecretResponse')
    expect(detailPage).toContain('const secretId = parseSecretId(rawSecretId)')
    expect(detailPage).toContain('.then(parseSecretDetailResponse)')
    expect(parsers).toContain('id: parseSecretId(raw.id)')
    expect(readProjectFile('lib/managed/api-paths.ts')).toContain("isEntityId(value, 'secret')")
  })

  it('keeps vault and credential routes typed end-to-end', () => {
    const listPage = readProjectFile('app/managed/vaults/page.tsx')
    const detailPage = readProjectFile('app/managed/vaults/[vaultId]/page.tsx')
    const parsers = readProjectFile('lib/managed/vault-response-parsers.ts')

    expect(listPage).toContain('parseItem: parseVaultResponse')
    expect(detailPage).toContain('const vaultId = parseVaultId(rawVaultId)')
    expect(detailPage).toContain('parseVaultCredentialListResponse(response.data)')
    expect(parsers).toContain('id: parseCredentialId(raw.id)')
    expect(parsers).toContain('vault_id: parseVaultId(raw.vault_id)')
    expect(readProjectFile('lib/managed/api-paths.ts')).toContain("isEntityId(value, 'vault')")
    expect(readProjectFile('lib/managed/api-paths.ts')).toContain("isEntityId(value, 'credential')")
  })

  it('keeps sandbox diagnostics typed at the API boundary', () => {
    const page = readProjectFile('app/managed/platform/network-policies/page.tsx')
    const parsers = readProjectFile('lib/managed/network-policy-response-parsers.ts')

    expect(readProjectFile('types/managed.ts')).toContain('sandbox_id: SandboxId')
    expect(page).toContain('managedGet<unknown>')
    expect(page).toContain('.then(parseNetworkPolicyListResponse)')
    expect(parsers).toContain('sandbox_id: parseSandboxId(raw.sandbox_id)')
    expect(parsers).toContain('session_id: parseOptionalId<SessionId>')
    expect(parsers).toContain('task_id: parseOptionalId<TaskId>')
  })

  it('keeps memory resources typed at API boundaries', () => {
    const listPage = readProjectFile('app/managed/memory-stores/page.tsx')
    const detailPage = readProjectFile('app/managed/memory-stores/[storeId]/page.tsx')
    const parsers = readProjectFile('lib/managed/memory-response-parsers.ts')

    expect(listPage).toContain('parseItem: parseMemoryStoreResponse')
    expect(detailPage).toContain('parseMemoryStoreId(rawId ||')
    expect(detailPage).toContain('.then(parseMemoryListResponse)')
    expect(parsers).toContain('id: parseMemoryId(raw.id)')
    expect(parsers).toContain('memory_store_id: parseMemoryStoreId(raw.memory_store_id)')
  })

  it('keeps the complete Skill identity chain typed at API boundaries', () => {
    const page = readProjectFile('app/managed/skills/page.tsx')
    const detailPage = readProjectFile('app/managed/skills/[skillId]/page.tsx')
    const authoring = readProjectFile('hooks/managed/use-skill-authoring.ts')
    const lifecycle = readProjectFile('components/managed/skills/skill-lifecycle-actions.tsx')
    const parsers = readProjectFile('lib/managed/skill-response-parsers.ts')

    expect(page).toContain('parseItem: parseSkillResponse')
    expect(page).toContain('parseSkillVersionFileListResponse(res)')
    expect(page).toContain('parseSkillUsageListResponse(res)')
    expect(detailPage).toContain('parseSkillId(rawSkillId)')
    expect(authoring).toContain('parseSkillAuthoringSaveResponse(')
    expect(authoring).toContain('parseSkillSecurityScanResponse(')
    expect(lifecycle).toContain('parseSkillLifecycleTransitionResponse(')
    expect(authoring).not.toMatch(/draftSkillId:\s*string/)
    expect(parsers).toContain('id: parseSkillFileId(raw.id)')
    expect(parsers).toContain('id: parseSkillVersionFileId(raw.id)')
    expect(parsers).toContain('id: parseSkillUsageId(raw.id)')
  })

  it('keeps file and session-resource identities typed at API boundaries', () => {
    const filesPage = readProjectFile('app/managed/files/page.tsx')
    const sessionPage = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const createDialog = readProjectFile(
      'app/managed/sessions/components/create-session-dialog.tsx',
    )
    const parsers = readProjectFile('lib/managed/file-response-parsers.ts')
    const apiPaths = readProjectFile('lib/managed/api-paths.ts')

    expect(readProjectFile('types/managed.ts')).toContain('id: FileId')
    expect(readProjectFile('types/managed.ts')).toContain('id: SessionResourceId')
    expect(filesPage).toContain('parseItem: parseFileResponse')
    expect(filesPage).toContain("apiResourcePath('files', file.id)")
    expect(createDialog).toContain('parseFileListResponse(response.data)')
    expect(sessionPage).toContain('parseSessionResourceListResponse(response.data)')
    expect(parsers).toContain('id: parseFileId(raw.id)')
    expect(parsers).toContain('id: parseSessionResourceId(raw.id)')
    expect(apiPaths).toContain("isEntityId(value, 'file')")
    expect(apiPaths).toContain("isEntityId(value, 'sessionResource')")
  })

  it('keeps persisted event identities typed across REST and SSE boundaries', () => {
    const page = readProjectFile('app/managed/sessions/[sessionId]/page.tsx')
    const sse = readProjectFile('lib/managed/sse.ts')
    const parsers = readProjectFile('lib/managed/event-response-parsers.ts')
    const eventHelpers = readProjectFile('lib/managed/session-events.ts')

    expect(readProjectFile('types/managed.ts')).toContain('id?: EventId')
    expect(page).toContain('parseSessionEventListResponse(')
    expect(sse).toContain('parseSessionEventResponse(parsed)')
    expect(parsers).toContain('id: raw.id ? parseEventId(raw.id) : undefined')
    expect(eventHelpers).not.toContain("replace(/^evt_/")
  })
})
