import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedGet, managedPost } from '@/lib/api-client'
import {
  AGENT_ID,
  ENVIRONMENT_ID,
  EVENT_ID,
  FILE_ID,
  ORGANIZATION_ID,
  OTHER_SESSION_ID,
  PROJECT_ID,
  SESSION_ID,
  VAULT_ID,
} from '@/test-utils/entity-ids'
import { parseMemoryStoreId } from '@/types/entity-id'

import {
  appendManagedSessionEvents,
  archiveManagedSession,
  buildManagedSessionCreateBody,
  createManagedSession,
  fetchManagedAgentSessionOptions,
  fetchManagedAgentSessions,
  fetchManagedSessions,
  fetchManagedSessionEvents,
  fetchManagedSession,
  fetchManagedSessionSkillUsage,
  managedAgentSessionOptionsQueryKey,
  managedAgentSessionsQueryKey,
  managedAgentSessionsQueryPrefix,
  managedSessionsQueryPrefix,
  managedSessionQueryKey,
  managedSessionSkillUsageQueryKey,
  sendManagedSessionUserMessage,
  stopManagedSession,
} from './session-client'

vi.mock('@/lib/api-client', () => ({
  managedGet: vi.fn(),
  managedPost: vi.fn(),
}))

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

describe('managed Session client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
    vi.mocked(managedPost).mockReset()
  })

  it('owns Session create serialization and validates the created id', async () => {
    const memoryStoreId = parseMemoryStoreId('memstore_018f6f42-0a51-7cc4-98c8-4f6f0ca5f030')
    const input = {
      agentId: AGENT_ID,
      title: 'Security review',
      environmentId: ENVIRONMENT_ID,
      credentialGroupIds: [VAULT_ID],
      fileResources: [{ fileId: FILE_ID, mountPath: '/workspace/report.md' }],
      memoryStoreResources: [{ memoryStoreId }],
      repositoryResources: [
        {
          url: 'https://github.com/example/project.git',
          branch: 'main',
          mountPath: '/workspace/project',
          authorizationToken: 'token',
        },
      ],
    }
    const expectedBody = {
      agent: AGENT_ID,
      title: 'Security review',
      environment_id: ENVIRONMENT_ID,
      credential_group_ids: [VAULT_ID],
      file_resources: [{ type: 'file', file_id: FILE_ID, mount_path: '/workspace/report.md' }],
      resources: [{ memory_store_id: memoryStoreId, access: 'read_write' }],
      repo_resources: [
        {
          type: 'github_repository',
          url: 'https://github.com/example/project.git',
          branch: 'main',
          mount_path: '/workspace/project',
          authorization_token: 'token',
        },
      ],
    }
    vi.mocked(managedPost).mockResolvedValue({ id: SESSION_ID, status: 'idle' })

    expect(buildManagedSessionCreateBody(input)).toEqual(expectedBody)
    await expect(createManagedSession(input, requestScope)).resolves.toBe(SESSION_ID)
    expect(managedPost).toHaveBeenCalledWith('/sessions', expectedBody, {
      headers: {
        'X-Org-Id': ORGANIZATION_ID,
        'X-Project-Id': PROJECT_ID,
      },
      skipManagedContext: true,
    })
  })

  it('rejects non-canonical Session create responses', async () => {
    vi.mocked(managedPost).mockResolvedValue({ session: { id: SESSION_ID } })

    await expect(createManagedSession({ agentId: AGENT_ID }, requestScope)).rejects.toThrow(
      /session id/,
    )
  })

  it('uses one scoped query identity and validates fetched Session ids', async () => {
    vi.mocked(managedGet).mockResolvedValue({ id: SESSION_ID, status: 'idle' })

    await expect(fetchManagedSession(SESSION_ID, requestScope)).resolves.toMatchObject({
      id: SESSION_ID,
      status: 'idle',
    })
    expect(managedSessionQueryKey(requestScope.key, SESSION_ID)).toEqual([
      'session',
      requestScope.key,
      SESSION_ID,
    ])
    expect(managedGet).toHaveBeenCalledWith(`/sessions/${SESSION_ID}`, {
      headers: {
        'X-Org-Id': ORGANIZATION_ID,
        'X-Project-Id': PROJECT_ID,
      },
      skipManagedContext: true,
    })
  })

  it('owns Agent-scoped Session pagination, parsing, and cache identity', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [{ id: SESSION_ID, status: 'idle' }],
      has_more: true,
      first_id: SESSION_ID,
      last_id: SESSION_ID,
    })

    expect(managedAgentSessionsQueryPrefix(requestScope.key, AGENT_ID)).toEqual([
      'agent-sessions',
      requestScope.key,
      AGENT_ID,
    ])
    expect(managedAgentSessionsQueryKey(requestScope.key, AGENT_ID)).toEqual([
      'agent-sessions',
      requestScope.key,
      AGENT_ID,
      20,
      null,
      false,
    ])
    expect(managedAgentSessionsQueryKey(requestScope.key, null, { limit: 100 })).toEqual([
      'agent-sessions',
      requestScope.key,
      null,
      100,
      null,
      false,
    ])
    expect(
      managedAgentSessionsQueryKey(requestScope.key, AGENT_ID, {
        limit: 100,
        afterId: SESSION_ID,
        includeArchived: true,
      }),
    ).toEqual(['agent-sessions', requestScope.key, AGENT_ID, 100, SESSION_ID, true])

    await expect(
      fetchManagedAgentSessions(
        AGENT_ID,
        { limit: 100, afterId: SESSION_ID, includeArchived: true },
        requestScope,
      ),
    ).resolves.toEqual({
      sessions: [{ id: SESSION_ID, status: 'idle' }],
      hasMore: true,
      firstId: SESSION_ID,
      lastId: SESSION_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/agents/${AGENT_ID}/sessions?limit=100&after_id=${SESSION_ID}&include_archived=true`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns global Session pagination and its invalidation prefix', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [{ id: SESSION_ID, status: 'idle' }],
      has_more: false,
      first_id: SESSION_ID,
      last_id: SESSION_ID,
    })

    expect(managedSessionsQueryPrefix(requestScope.key)).toEqual(['sessions', requestScope.key])
    await expect(
      fetchManagedSessions({ limit: 25, afterId: SESSION_ID, includeArchived: true }, requestScope),
    ).resolves.toEqual({
      items: [{ id: SESSION_ID, status: 'idle' }],
      hasMore: false,
      firstId: SESSION_ID,
      lastId: SESSION_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/sessions?limit=25&after_id=${SESSION_ID}&include_archived=true`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every active Agent Session option page under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [{ id: SESSION_ID, status: 'idle', archived_at: null }],
        has_more: true,
        first_id: SESSION_ID,
        last_id: SESSION_ID,
      })
      .mockResolvedValueOnce({
        data: [{ id: OTHER_SESSION_ID, status: 'completed', archived_at: null }],
        has_more: false,
        first_id: OTHER_SESSION_ID,
        last_id: OTHER_SESSION_ID,
      })

    expect(managedAgentSessionOptionsQueryKey(requestScope.key, AGENT_ID)).toEqual([
      'agent-sessions',
      requestScope.key,
      AGENT_ID,
      'options',
      false,
    ])
    await expect(fetchManagedAgentSessionOptions(AGENT_ID, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: SESSION_ID }),
      expect.objectContaining({ id: OTHER_SESSION_ID }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/agents/${AGENT_ID}/sessions?limit=100&after_id=${SESSION_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects Agent Session option pagination that does not advance', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [{ id: SESSION_ID, status: 'idle' }],
        has_more: true,
        first_id: SESSION_ID,
        last_id: SESSION_ID,
      })
      .mockResolvedValueOnce({
        data: [{ id: SESSION_ID, status: 'idle' }],
        has_more: true,
        first_id: SESSION_ID,
        last_id: SESSION_ID,
      })

    await expect(fetchManagedAgentSessionOptions(AGENT_ID, requestScope)).rejects.toThrow(
      /Agent Session options pagination returned an invalid cursor/,
    )
  })

  it('rejects non-canonical Agent Session list responses', async () => {
    vi.mocked(managedGet).mockResolvedValue([{ id: SESSION_ID, status: 'idle' }])

    await expect(fetchManagedAgentSessions(AGENT_ID, {}, requestScope)).rejects.toThrow(
      /Agent Session list response/,
    )

    vi.mocked(managedGet).mockResolvedValue({
      data: [],
      has_more: false,
      first_id: 123,
      last_id: null,
    })
    await expect(fetchManagedAgentSessions(AGENT_ID, {}, requestScope)).rejects.toThrow(
      /Agent Session list response/,
    )
  })

  it('owns Session event history pagination and response parsing', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [{ id: EVENT_ID, type: 'agent.message', seq: 12 }],
      has_more: true,
    })

    await expect(
      fetchManagedSessionEvents(
        SESSION_ID,
        { limit: 25, order: 'desc', cursor: { direction: 'before', sequence: 12 } },
        requestScope,
      ),
    ).resolves.toEqual({
      events: [{ id: EVENT_ID, type: 'agent.message', seq: 12 }],
      hasMore: true,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/sessions/${SESSION_ID}/events?limit=25&order=desc&before_seq=12`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns Session skill-usage identity and response parsing', async () => {
    vi.mocked(managedGet).mockResolvedValue({ data: [] })

    expect(managedSessionSkillUsageQueryKey(requestScope.key, SESSION_ID)).toEqual([
      'session-skill-usage',
      requestScope.key,
      SESSION_ID,
    ])
    await expect(fetchManagedSessionSkillUsage(SESSION_ID, requestScope)).resolves.toEqual([])
    expect(managedGet).toHaveBeenCalledWith(`/sessions/${SESSION_ID}/skill-usage`, {
      headers: {
        'X-Org-Id': ORGANIZATION_ID,
        'X-Project-Id': PROJECT_ID,
      },
      skipManagedContext: true,
    })
  })

  it('owns the Session event envelope and message idempotency key', async () => {
    vi.mocked(managedPost).mockResolvedValue(undefined)

    await sendManagedSessionUserMessage(SESSION_ID, 'Review this change', requestScope)

    expect(managedPost).toHaveBeenCalledWith(
      `/sessions/${SESSION_ID}/events`,
      {
        events: [
          {
            type: 'user.message',
            content: [{ type: 'text', text: 'Review this change' }],
          },
        ],
      },
      {
        headers: {
          'X-Org-Id': ORGANIZATION_ID,
          'X-Project-Id': PROJECT_ID,
          'Idempotency-Key': expect.stringMatching(/^session-message:/),
        },
        skipManagedContext: true,
      },
    )
  })

  it('posts generic events and lifecycle commands through canonical paths', async () => {
    vi.mocked(managedPost).mockResolvedValue(undefined)
    const confirmation = {
      type: 'user.tool_confirmation',
      tool_use_id: 'call-1',
      approved: true,
    }

    await appendManagedSessionEvents(SESSION_ID, [confirmation], requestScope)
    await stopManagedSession(SESSION_ID, requestScope)
    await archiveManagedSession(SESSION_ID, requestScope)

    expect(managedPost).toHaveBeenNthCalledWith(
      1,
      `/sessions/${SESSION_ID}/events`,
      { events: [confirmation] },
      {
        headers: {
          'X-Org-Id': ORGANIZATION_ID,
          'X-Project-Id': PROJECT_ID,
        },
        skipManagedContext: true,
      },
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      2,
      `/sessions/${SESSION_ID}/stop`,
      {},
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      3,
      `/sessions/${SESSION_ID}/archive`,
      {},
      expect.objectContaining({ skipManagedContext: true }),
    )
  })
})
