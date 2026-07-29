import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MemoryStoreListPage, {
  DREAMING_MIN_RUNNING_MS,
  EVEROS_MEMORY_OVERVIEW_REFETCH_INTERVAL_MS,
  MEMORY_OVERVIEW_LIMIT,
  buildMemoryActivityItems,
  extractFocusedMemoryBlock,
  getActivityTimestamp,
  getPaginationItems,
  isWithinTimeRange,
  parseMemoryBlockSections,
  sourceDisplayPath,
} from './page'

const managedGetMock = vi.hoisted(() => vi.fn())
const managedPostMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api-client', () => ({
  managedGet: managedGetMock,
  managedPost: managedPostMock,
}))

function overviewFixture() {
  return {
    app_id: 'joysafeter',
    project_id: 'project-1',
    counts: {
      profiles: 2,
      episodes: 11,
      agent_cases: 2,
      agent_skills: 2,
    },
    profiles: [
      {
        id: 'profile-1',
        owner_id: 'user-1',
        summary: 'Profile activity entry',
        explicit_info_json: JSON.stringify([{ category: '饮食偏好', description: '用户明确表示自己喜欢食用香蕉。' }]),
        implicit_traits_json: JSON.stringify([{ trait: '主动记录型', description: '用户倾向于主动向系统提供个人偏好信息。' }]),
        timestamp_ms: Date.now() - 2 * 60 * 60 * 1000,
        md_path: 'profiles/profile-1.md',
      },
      {
        id: 'profile-2',
        owner_id: 'user-2',
        summary: 'Older profile activity entry',
        explicit_info_json: JSON.stringify([{ category: '工作偏好', description: '用户希望筛选自己的相关片段。' }]),
        implicit_traits_json: JSON.stringify([{ trait: '目标导向型', description: '用户倾向于围绕当前目标检查上下文。' }]),
        timestamp_ms: Date.now() - 40 * 24 * 60 * 60 * 1000,
        md_path: 'profiles/profile-2.md',
      },
    ],
    episodes: [
      {
        id: 'episode-1',
        entry_id: 'ep_20260710_00000001',
        owner_id: 'user-1',
        session_id: 'session-1',
        timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
        subject: 'Episode detail subject',
        summary: 'Episode activity entry',
        episode: 'Full episode content.',
        md_path: 'joysafeter/project-1/users/user-1/episodes/episode-2026-07-10.md',
      },
      {
        id: 'episode-2',
        entry_id: 'ep_20260710_00000002',
        owner_id: 'user-1',
        session_id: 'session-2',
        timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
        subject: 'Second episode database subject',
        summary: 'Second episode activity entry',
        episode: 'Second episode content.',
        md_path: 'joysafeter/project-1/users/user-1/episodes/episode-2026-07-10.md',
      },
      {
        id: 'episode-user-2',
        entry_id: 'ep_20260710_00000003',
        owner_id: 'user-2',
        session_id: 'session-user-2',
        timestamp: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(),
        subject: 'User two episode subject',
        summary: 'User two episode activity entry',
        episode: 'User two episode content.',
        md_path: 'joysafeter/project-1/users/user-2/episodes/episode-2026-07-10.md',
      },
      {
        id: 'episode-aggregated-1',
        entry_id: 'ep_20260711_00000001',
        owner_id: 'user-1',
        session_id: null,
        parent_type: 'cluster',
        parent_id: 'cluster-user-memory-1',
        source_session_ids: ['session-1', 'session-2'],
        source_entry_ids: ['ep_20260710_00000001', 'ep_20260710_00000002'],
        timestamp: new Date(Date.now() - 70 * 60 * 1000).toISOString(),
        subject: 'Aggregated security audit memory',
        summary: 'Aggregated memory entry',
        episode: 'Consolidated episode content.',
        md_path: 'joysafeter/project-1/users/user-1/episodes/episode-2026-07-11.md',
      },
      {
        id: 'episode-aggregated-2',
        entry_id: 'ep_20260711_00000002',
        owner_id: 'user-aggregated',
        session_id: null,
        parent_type: 'cluster',
        parent_id: 'cluster-user-memory-2',
        source_session_ids: ['session-user-2'],
        source_entry_ids: ['ep_20260710_00000003'],
        timestamp: new Date(Date.now() - 95 * 60 * 1000).toISOString(),
        subject: 'Aggregated project planning memory',
        summary: 'Second aggregated memory entry',
        episode: 'Second consolidated episode content.',
        md_path: 'joysafeter/project-1/users/user-2/episodes/episode-2026-07-11.md',
      },
      {
        id: 'episode-unscoped',
        entry_id: 'ep_20260711_00000003',
        owner_id: 'user-1',
        session_id: null,
        parent_type: 'import',
        parent_id: 'import-1',
        timestamp: new Date(Date.now() - 80 * 60 * 1000).toISOString(),
        subject: 'Imported episode without session',
        summary: 'Imported memory entry',
        episode: 'Imported episode content.',
        md_path: 'joysafeter/project-1/users/user-1/episodes/episode-2026-07-11.md',
      },
    ],
    atomic_facts: [
      {
        id: 'fact-episode-1',
        entry_id: 'af_20260710_00000001',
        owner_id: 'user-1',
        session_id: 'session-1',
        timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
        parent_type: 'episode',
        parent_id: 'ep_20260710_00000001',
        sender_ids: ['user-1', 'agent-1'],
        fact: '用户正在确认 Episode 展开时展示直接抽取的事实。',
        md_path: 'joysafeter/project-1/users/user-1/.atomic_facts/atomic_fact-2026-07-10.md',
        deprecated_by: null,
      },
      {
        id: 'fact-episode-2',
        entry_id: 'af_20260710_00000002',
        owner_id: 'user-1',
        session_id: 'session-1',
        timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
        parent_type: 'episode',
        parent_id: 'ep_20260710_00000002',
        sender_ids: ['user-1', 'agent-1'],
        fact: '这是同一 session 中另一条 Episode 的事实，不应展示在第一条下。',
        md_path: 'joysafeter/project-1/users/user-1/.atomic_facts/atomic_fact-2026-07-10.md',
        deprecated_by: null,
      },
    ],
    agent_cases: [
      {
        id: 'case-1',
        entry_id: 'case_20260707_00000001',
        owner_id: 'agent-1',
        session_id: 'session-case-1',
        timestamp: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
        task_intent: 'Case activity entry',
        approach: 'Use the selected recent activity to focus the agent memory list.',
        key_insight: 'Agent case detail should live in the agent memory tab.',
        quality_score: 0.91,
        md_path: 'cases/case-1.md',
      },
      {
        id: 'case-2',
        entry_id: 'case_20260601_00000001',
        owner_id: 'agent-2',
        session_id: 'session-case-2',
        timestamp: new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(),
        task_intent: 'Older case activity entry',
        approach: 'Older case approach.',
        key_insight: 'Older case insight.',
        quality_score: 0.72,
        md_path: 'cases/case-2.md',
      },
    ],
    agent_skills: [
      {
        id: 'skill-1',
        owner_id: 'agent-1',
        name: 'Skill activity entry',
        description: [
          'Route memory detail actions to the right memory tab.',
          'This description intentionally stays long enough to verify that the Agent Skill card does not truncate the md description field before the user opens details.',
          'The final diagnostic sentence must remain visible in the collapsed card.',
        ].join(' '),
        content: 'Skill content.',
        confidence: 0.86,
        maturity_score: 0.65,
        source_case_ids: ['case-1'],
        cluster_id: 'cluster-1',
        md_path: 'skills/skill-1.md',
      },
      {
        id: 'skill-2',
        owner_id: 'agent-2',
        name: 'Second skill entry',
        description: 'Second skill description.',
        content: 'Second skill content.',
        confidence: 0.5,
        maturity_score: 0.25,
        source_case_ids: ['case-2'],
        cluster_id: 'cluster-2',
        md_path: 'skills/skill-2.md',
      },
    ],
    recent_activity: [
      {
        id: 'profile-1',
        kind: 'profile',
        action: 'updated',
        owner_id: 'user-1',
        timestamp: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
        summary: 'Profile activity entry',
        md_path: 'profiles/profile-1.md',
      },
      {
        id: 'episode-1',
        kind: 'episode',
        action: 'created',
        owner_id: 'user-1',
        timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
        summary: 'Episode activity entry',
        md_path: 'joysafeter/project-1/users/user-1/episodes/episode-2026-07-10.md',
      },
      {
        id: 'episode-yesterday',
        kind: 'episode',
        action: 'created',
        owner_id: 'user-1',
        timestamp: new Date(Date.now() - 18 * 60 * 60 * 1000).toISOString(),
        summary: 'Yesterday but within twenty four hours entry',
        md_path: 'joysafeter/project-1/users/user-2/episodes/episode-2026-07-09.md',
      },
      {
        id: 'case-1',
        kind: 'agent_case',
        action: 'created',
        owner_id: 'agent-1',
        timestamp: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
        summary: 'Case activity entry',
        md_path: 'cases/case-1.md',
      },
      {
        id: 'skill-1',
        kind: 'agent_skill',
        action: 'created',
        owner_id: 'agent-1',
        timestamp: new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(),
        summary: 'Skill activity entry',
        md_path: 'skills/skill-1.md',
      },
      {
        id: 'profile-2',
        kind: 'profile',
        action: 'updated',
        owner_id: 'user-2',
        timestamp: new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(),
        summary: 'Older profile activity entry',
        md_path: 'profiles/profile-2.md',
      },
      {
        id: 'case-2',
        kind: 'agent_case',
        action: 'created',
        owner_id: 'agent-2',
        timestamp: new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(),
        summary: 'Older case activity entry',
        md_path: 'cases/case-2.md',
      },
      {
        id: 'episode-2',
        entry_id: 'ep_20260710_00000002',
        kind: 'episode',
        action: 'created',
        owner_id: 'user-1',
        session_id: 'session-2',
        timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
        summary: 'Second episode activity entry',
        subject: 'Second episode database subject',
        md_path: 'joysafeter/project-1/users/user-1/episodes/episode-2026-07-10.md',
      },
      {
        id: 'episode-3',
        kind: 'episode',
        action: 'created',
        owner_id: 'user-1',
        timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
        summary: 'Third episode activity entry',
        md_path: 'episodes/episode-3.md',
      },
      {
        id: 'episode-4',
        kind: 'episode',
        action: 'created',
        owner_id: 'user-1',
        timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
        summary: 'Page two episode activity entry',
        md_path: 'episodes/episode-4.md',
      },
      {
        id: 'episode-old',
        kind: 'episode',
        action: 'created',
        owner_id: 'user-2',
        timestamp: new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(),
        summary: 'Older episode activity entry',
        md_path: 'episodes/episode-old.md',
      },
    ],
  }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryStoreListPage />
    </QueryClientProvider>,
  )
}

async function clickActivityDetailByTitle(user: ReturnType<typeof userEvent.setup>, container: HTMLElement, title: string | RegExp) {
  const titleElement = within(container).getByText(title)
  const row = titleElement.closest('tr')
  expect(row).not.toBeNull()
  await user.click(within(row as HTMLElement).getByRole('button', { name: '详情' }))
}

describe('MemoryStoreListPage', () => {
  beforeEach(() => {
    vi.setSystemTime(new Date('2026-07-10T12:00:00+08:00'))
    managedGetMock.mockReset()
    managedPostMock.mockReset()
    managedPostMock.mockResolvedValue({
      status: 'started',
      name: 'reflect_episodes',
      run_id: 'run-1',
      run_ids: ['run-1'],
      display_name: 'Dreaming',
    })
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.startsWith('/everos_memory/dreaming/runs/')) {
        return {
          run_id: 'run-1',
          strategy_name: 'reflect_episodes',
          status: 'running',
          attempt: 0,
          started_at: '2026-07-10T04:00:00Z',
          finished_at: null,
          error: null,
          event_topic: 'app.everos.infra.ome.events:ManualTick',
          event_payload: '{}',
          max_retries_snapshot: 1,
          event_id: 'event-1',
          display_name: 'Dreaming',
        }
      }
      if (path.startsWith('/everos_memory/document')) {
        if (path.includes('profiles%2Fprofile-1.md')) {
          return {
            md_path: 'profiles/profile-1.md',
            content: [
              '---',
              'id: profile-user-1',
              'type: user_profile',
              'summary: Complete profile markdown summary.',
              'explicit_info:',
              '- category: 饮食偏好',
              '  description: 用户明确表示自己喜欢食用香蕉。',
              'implicit_traits:',
              '- trait: 主动记录型',
              '  description: 用户倾向于主动向系统提供个人偏好信息。',
              'profile_timestamp_ms: 1783656000000',
              '---',
              '',
              'Complete profile markdown body.',
            ].join('\n'),
          }
        }
        if (path.includes('profiles%2Fprofile-2.md')) {
          return {
            md_path: 'profiles/profile-2.md',
            content: [
              '---',
              'id: profile-user-2',
              'type: user_profile',
              'summary: Older profile markdown summary.',
              'explicit_info:',
              '- category: 工作偏好',
              '  description: 用户希望筛选自己的相关片段。',
              'implicit_traits:',
              '- trait: 目标导向型',
              '  description: 用户倾向于围绕当前目标检查上下文。',
              'profile_timestamp_ms: 1780200000000',
              '---',
              '',
              'Older profile markdown body.',
            ].join('\n'),
          }
        }
        if (path.includes('skills%2Fskill-1.md')) {
          return {
            md_path: 'skills/skill-1.md',
            content: [
              'Name',
              'Skill activity entry',
              '',
              'Description',
              'Route memory detail actions to the right memory tab.',
              '',
              'Content',
              'id: skill-1 type: agent_skill',
              'schema_version: 1 agent_id: agent-1 track: agent',
              'source_case_ids:',
              '- case-1 cluster_id: cluster-1 created_at: null updated_at: null',
              '',
              '## Potential Steps',
              '',
              '**Complete skill markdown body.**',
              '',
              '- Rendered skill step',
            ].join('\n'),
          }
        }
        if (path.includes('cases%2Fcase-1.md')) {
          return {
            md_path: 'cases/case-1.md',
            content: [
              '<!-- entry:case_20260707_00000001 -->',
              'case_20260707_00000001',
              '**owner_id**: agent-1',
              '**session_id**: session-case-1',
              '',
              'TaskIntent',
              'Case activity entry',
              '',
              'Approach',
              'Complete case markdown body.',
              '<!-- /entry:case_20260707_00000001 -->',
            ].join('\n'),
          }
        }
        if (path.includes('users%2Fuser-2%2Fepisodes%2Fepisode-2026-07-10.md')) {
          return {
            md_path: 'joysafeter/project-1/users/user-2/episodes/episode-2026-07-10.md',
            content: [
              '<!-- entry:ep_20260710_00000003 -->',
              'ep_20260710_00000003',
              '**owner_id**: user-2',
              '**session_id**: session-user-2',
              '',
              'Subject',
              'User two episode subject',
              '',
              'Summary',
              'User two full markdown summary.',
              '',
              'Content',
              'User two complete markdown body.',
              '<!-- /entry:ep_20260710_00000003 -->',
            ].join('\n'),
          }
        }
        return {
          md_path: 'episodes/episode-1.md',
          content: [
            '<!-- entry:ep_20260710_00000001 -->',
            'ep_20260710_00000001',
            '**owner_id**: user-1',
            '**session_id**: session-1',
            '**sender_ids**: [user-1, agent-1]',
            '',
            'Subject',
            'Episode detail subject',
            '',
            'Summary',
            'Full markdown summary.',
            '',
            'Content',
            'Complete markdown body.',
            '<!-- /entry:ep_20260710_00000001 -->',
            '',
            '<!-- entry:ep_20260710_00000002 -->',
            'ep_20260710_00000002',
            '**owner_id**: user-1',
            '**session_id**: session-1',
            '',
            'Subject',
            'Second episode database subject',
            '',
            'Summary',
            'Second full markdown summary.',
            '',
            'Content',
            'Second complete markdown body.',
            '<!-- /entry:ep_20260710_00000002 -->',
          ].join('\n'),
        }
      }
      return overviewFixture()
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('builds compact page number controls for longer pagination ranges', () => {
    expect(getPaginationItems(1, 10)).toEqual([1, 2, 3, 'ellipsis-end', 8, 9, 10])
    expect(getPaginationItems(5, 10)).toEqual([1, 2, 3, 4, 5, 6, 'ellipsis-end', 8, 9, 10])
    expect(getPaginationItems(10, 10)).toEqual([1, 2, 3, 'ellipsis-start', 8, 9, 10])
  })

  it('uses a short automatic refresh interval for EverOS memory overview', () => {
    expect(EVEROS_MEMORY_OVERVIEW_REFETCH_INTERVAL_MS).toBe(5000)
  })

  it('keeps the memory overview request within the backend limit cap', async () => {
    renderPage()

    await screen.findByTestId('recent-memory-activity')

    expect(MEMORY_OVERVIEW_LIMIT).toBeLessThanOrEqual(500)
    expect(managedGetMock).toHaveBeenCalledWith(`/everos_memory/overview?limit=${MEMORY_OVERVIEW_LIMIT}`)
  })

  it('filters activity by local calendar day week and month boundaries', () => {
    const now = new Date('2026-07-10T12:00:00+08:00')

    expect(isWithinTimeRange('2026-07-10T00:00:00+08:00', 'daily', now)).toBe(true)
    expect(isWithinTimeRange('2026-07-10T23:59:59+08:00', 'daily', now)).toBe(true)
    expect(isWithinTimeRange('2026-07-09T23:59:59+08:00', 'daily', now)).toBe(false)
    expect(isWithinTimeRange('2026-07-11T00:00:00+08:00', 'daily', now)).toBe(false)

    expect(isWithinTimeRange('2026-07-06T00:00:00+08:00', 'weekly', now)).toBe(true)
    expect(isWithinTimeRange('2026-07-12T23:59:59+08:00', 'weekly', now)).toBe(true)
    expect(isWithinTimeRange('2026-07-05T23:59:59+08:00', 'weekly', now)).toBe(false)
    expect(isWithinTimeRange('2026-07-13T00:00:00+08:00', 'weekly', now)).toBe(false)

    expect(isWithinTimeRange('2026-07-01T00:00:00+08:00', 'monthly', now)).toBe(true)
    expect(isWithinTimeRange('2026-07-31T23:59:59+08:00', 'monthly', now)).toBe(true)
    expect(isWithinTimeRange('2026-06-30T23:59:59+08:00', 'monthly', now)).toBe(false)
    expect(isWithinTimeRange('2026-08-01T00:00:00+08:00', 'monthly', now)).toBe(false)
  })

  it('treats July 2026 monthly range as July 1 inclusive to August 1 exclusive on July 13', () => {
    const now = new Date('2026-07-13T12:00:00+08:00')

    expect(isWithinTimeRange('2026-06-30T23:59:59+08:00', 'monthly', now)).toBe(false)
    expect(isWithinTimeRange('2026-07-01T00:00:00+08:00', 'monthly', now)).toBe(true)
    expect(isWithinTimeRange('2026-07-13T12:00:00+08:00', 'monthly', now)).toBe(true)
    expect(isWithinTimeRange('2026-07-31T23:59:59+08:00', 'monthly', now)).toBe(true)
    expect(isWithinTimeRange('2026-08-01T00:00:00+08:00', 'monthly', now)).toBe(false)
  })

  it('uses embedded timestamp before memory file date for recent activity filtering', () => {
    const timestamp = getActivityTimestamp({
      id: '019f4619-e72a-7eb3-b0cc-d0791661c9cc_ep_20260709_00000006',
      kind: 'episode',
      action: 'Create',
      owner_id: '019f4619-e72a-7eb3-b0cc-d0791661c9cc',
      timestamp: '2025-07-09T10:05:30+00:00',
      summary: 'Episode with old embedded timestamp',
      md_path: 'joysafeter/project/users/user/episodes/episode-2026-07-09.md',
    })

    expect(timestamp).toBe('2025-07-09T10:05:30+00:00')
    expect(isWithinTimeRange(timestamp, 'weekly', new Date('2026-07-10T12:00:00+08:00'))).toBe(false)
    expect(isWithinTimeRange(timestamp, 'monthly', new Date('2026-07-10T12:00:00+08:00'))).toBe(false)
  })

  it('keeps user or agent path context when source files share the same basename', () => {
    expect(sourceDisplayPath('joysafeter/project-1/users/user-1/episodes/episode-2026-07-09.md'))
      .toBe('users/user-1/episodes/episode-2026-07-09.md')
    expect(sourceDisplayPath('joysafeter/project-1/users/user-2/episodes/episode-2026-07-09.md'))
      .toBe('users/user-2/episodes/episode-2026-07-09.md')
    expect(sourceDisplayPath('joysafeter/project-1/agents/agent-1/.cases/agent_case-2026-07-09.md'))
      .toBe('agents/agent-1/.cases/agent_case-2026-07-09.md')
  })

  it('extracts a focused markdown entry by entry id or structured title', () => {
    const content = [
      '<!-- entry:first -->',
      '### Name',
      'First skill',
      '',
      '### Content',
      'First skill body.',
      '<!-- /entry:first -->',
      '',
      '<!-- entry:second -->',
      '### Name',
      'Second skill',
      '',
      '### Content',
      'Second skill body.',
      '<!-- /entry:second -->',
    ].join('\n')

    expect(extractFocusedMemoryBlock(content, {
      id: 'skill-2',
      kind: 'agent_skill',
      action: 'Update',
      owner_id: 'agent-1',
      timestamp: null,
      summary: 'Second skill',
      name: 'Second skill',
      md_path: 'skills/shared.md',
    })).toContain('Second skill body.')
    expect(extractFocusedMemoryBlock(content, {
      id: 'case-1',
      kind: 'agent_case',
      action: 'Create',
      owner_id: 'agent-1',
      timestamp: null,
      summary: 'First case',
      entry_id: 'first',
      md_path: 'cases/shared.md',
    })).toContain('First skill body.')
  })

  it('uses the structured title when one markdown file reuses an entry id', () => {
    const content = [
      '<!-- entry:ep_20260720_00000005 -->',
      '### Subject',
      '小杰表达喜爱三国演义并询问孙权关系图谱 2026年7月20日',
      '',
      '### Content',
      '三国关系图谱内容。',
      '<!-- /entry:ep_20260720_00000005 -->',
      '',
      '<!-- entry:ep_20260720_00000005 -->',
      '### Subject',
      'User Asks About Available Skills in EverOS and Receives API Error',
      '',
      '### Content',
      'EverOS skills API error content.',
      '<!-- /entry:ep_20260720_00000005 -->',
    ].join('\n')

    const focused = extractFocusedMemoryBlock(content, {
      id: '019f64b7-bdb8-7520-a780-ecc5fa152549_ep_20260720_00000005',
      kind: 'episode',
      action: 'Create',
      owner_id: 'huajie_Sun',
      session_id: '019f64b7-bdb8-7520-a780-ecc5fa152549',
      timestamp: '2026-07-20T06:59:17.782Z',
      summary: 'The user asked what EverOS skills were available, but the system returned a model service API error before answering.',
      subject: 'User Asks About Available Skills in EverOS and Receives API Error',
      entry_id: 'ep_20260720_00000005',
      md_path: 'joysafeter/project/users/huajie_Sun/episodes/episode-2026-07-20.md',
    })

    expect(focused).toContain('EverOS skills API error content.')
    expect(focused).not.toContain('三国关系图谱内容。')
  })

  it('does not return an episode markdown block when the reused entry id belongs to another session', () => {
    const content = [
      '<!-- entry:ep_20260720_00000005 -->',
      '## ep_20260720_00000005',
      '',
      '**session_id**: 019f7d5b-00f9-7502-b411-0f94f8d95400',
      '',
      '### Subject',
      '小杰表达喜爱三国演义并询问孙权关系图谱 2026年7月20日',
      '',
      '### Content',
      '三国关系图谱内容。',
      '<!-- /entry:ep_20260720_00000005 -->',
    ].join('\n')

    const focused = extractFocusedMemoryBlock(content, {
      id: '019f64b7-bdb8-7520-a780-ecc5fa152549_ep_20260720_00000005',
      kind: 'episode',
      action: 'Create',
      owner_id: 'huajie_Sun',
      session_id: '019f64b7-bdb8-7520-a780-ecc5fa152549',
      timestamp: '2026-07-20T06:59:17.782Z',
      summary: 'The user asked what EverOS skills were available, but the system returned a model service API error before answering.',
      subject: 'User Asks About Available Skills in EverOS and Receives API Error',
      entry_id: 'ep_20260720_00000005',
      md_path: 'joysafeter/project/users/huajie_Sun/episodes/episode-2026-07-20.md',
    })

    expect(focused).toBe('')
  })

  it('removes agent skill metadata before markdown body headings', () => {
    const sections = parseMemoryBlockSections([
      'id: skill-1 type: agent_skill',
      'schema_version: 1 agent_id: agent-1 track: agent name: EverOS memory API extraction failure',
      'description: metadata description confidence: 0.5 maturity_score: 1.0',
      'source_case_ids:',
      '- ac_20260709_00000002 cluster_id: cl_a0cfeff2705d created_at: null updated_at: null',
      '',
      '## Potential Steps',
      '',
      '1. Verify existing memory content before and after write attempts',
    ].join('\n'))

    expect(sections).toEqual([
      {
        label: '内容',
        content: [
          '## Potential Steps',
          '',
          '1. Verify existing memory content before and after write attempts',
        ].join('\n'),
      },
    ])
  })

  it('builds activity rows from all memory records instead of recent activity', () => {
    const fixture = overviewFixture()
    fixture.recent_activity = []

    const items = buildMemoryActivityItems(fixture)

    expect(items.filter((item) => item.kind === 'profile')).toHaveLength(fixture.profiles.length)
    expect(items.filter((item) => item.kind === 'episode')).toHaveLength(fixture.episodes.length)
    expect(items.filter((item) => item.kind === 'agent_case')).toHaveLength(fixture.agent_cases.length)
    expect(items.filter((item) => item.kind === 'agent_skill')).toHaveLength(fixture.agent_skills.length)
    expect(items.map((item) => item.id)).toContain('episode-user-2')
    expect(items.map((item) => item.id)).toContain('skill-2')
  })

  it('does not render the memory composition summary on the overview tab', async () => {
    renderPage()

    expect(await screen.findByRole('tab', { name: '总览' })).toBeInTheDocument()
    expect(await screen.findByText('Episode detail subject')).toBeInTheDocument()
    expect(screen.queryByText('记忆构成')).not.toBeInTheDocument()
    expect(screen.queryByText(/total$/)).not.toBeInTheDocument()
  })

  it('filters recent activity by clicking overview memory categories', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('tab', { name: '总览' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '用户记忆' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '智能体记忆' })).toBeInTheDocument()
    expect(await screen.findByText('Episode detail subject')).toBeInTheDocument()
    expect(screen.getByText('Profile activity entry')).toBeInTheDocument()
    expect(screen.getByText('Case activity entry')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Episodes' }))
    const recentActivity = screen.getByTestId('recent-memory-activity')
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Case activity entry')).not.toBeInTheDocument()
    expect(within(recentActivity).queryByText('Skill activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Episodes' }))
    expect(within(recentActivity).getByText('Profile activity entry')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Cases' }))
    expect(within(recentActivity).queryByText('Episode detail subject')).not.toBeInTheDocument()
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Skill activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Profiles' }))
    expect(within(recentActivity).getByText('Profile activity entry')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Older profile activity entry')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Episode detail subject')).not.toBeInTheDocument()
    expect(within(recentActivity).queryByText('Case activity entry')).not.toBeInTheDocument()
    expect(within(recentActivity).queryByText('Skill activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '总览' }))
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()
  })

  it('shows memory category metric cards only on the overview tab', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('button', { name: 'Filter recent activity by Profiles' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Filter recent activity by Episodes' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Filter recent activity by Cases' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Filter recent activity by Skills' })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '用户记忆' }))
    expect(screen.queryByRole('button', { name: 'Filter recent activity by Profiles' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Filter recent activity by Episodes' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Filter recent activity by Cases' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Filter recent activity by Skills' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))
    expect(screen.queryByRole('button', { name: 'Filter recent activity by Profiles' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Filter recent activity by Episodes' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Filter recent activity by Cases' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Filter recent activity by Skills' })).not.toBeInTheDocument()
  })

  it('filters recent activity with type dropdown and time range controls', async () => {
    const user = userEvent.setup()
    renderPage()

    const recentActivity = await screen.findByTestId('recent-memory-activity')
    expect(within(recentActivity).getByText('Profile activity entry')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter memory activity by type' }))
    expect(screen.getByRole('menuitemcheckbox', { name: /Profile/ })).not.toBeChecked()
    expect(screen.getByRole('menuitemcheckbox', { name: /Episode/ })).not.toBeChecked()
    expect(screen.getByRole('menuitemcheckbox', { name: /Case/ })).not.toBeChecked()
    expect(screen.getByRole('menuitemcheckbox', { name: /Skill/ })).not.toBeChecked()

    await user.click(screen.getByRole('menuitemcheckbox', { name: /Episode/ }))
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Case activity entry')).not.toBeInTheDocument()
    expect(within(recentActivity).queryByText('Skill activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter memory activity by type' }))
    await user.click(screen.getByRole('menuitemcheckbox', { name: /Case/ }))
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Skill activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '当天' }))
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Yesterday but within twenty four hours entry')).not.toBeInTheDocument()
    expect(within(recentActivity).queryByText('Case activity entry')).not.toBeInTheDocument()
    expect(within(recentActivity).queryByText('Skill activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '本周' }))
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Skill activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter memory activity by type' }))
    await user.click(screen.getByRole('menuitemcheckbox', { name: /Skill/ }))
    await user.click(screen.getByRole('tab', { name: '全部时间' }))
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Filter memory activity by type' }))
    await user.click(screen.getByRole('menuitemcheckbox', { name: /Episode/ }))
    await user.click(screen.getByRole('button', { name: 'Filter memory activity by type' }))
    await user.click(screen.getByRole('menuitemcheckbox', { name: /Case/ }))
    expect(within(recentActivity).getByText('Skill activity entry')).toBeInTheDocument()
  })

  it('shows only the current page between pagination arrows and right page size controls', async () => {
    const fixture = overviewFixture()
    for (let index = 3; index <= 25; index += 1) {
      fixture.episodes.push({
        id: `episode-extra-${index}`,
        entry_id: `ep_20260710_extra_${index}`,
        owner_id: 'user-1',
        session_id: `session-extra-${index}`,
        timestamp: new Date(Date.now() - (index + 1) * 60 * 1000).toISOString(),
        subject: `Extra episode subject ${index}`,
        summary: `Extra episode summary ${index}`,
        episode: `Extra episode content ${index}.`,
        md_path: `episodes/episode-extra-${index}.md`,
      })
    }
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.startsWith('/everos_memory/document')) {
        return {
          md_path: 'episodes/episode-1.md',
          content: 'Content\nComplete markdown body.',
        }
      }
      return fixture
    })

    const user = userEvent.setup()
    renderPage()

    const recentActivity = await screen.findByTestId('recent-memory-activity')
    expect(within(recentActivity).getByText('Extra episode subject 3')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Skill activity entry')).not.toBeInTheDocument()
    expect(within(recentActivity).getByRole('button', { name: 'Show 10 per page' })).toHaveAttribute('aria-current', 'page')
    expect(within(recentActivity).getByRole('button', { name: 'Show 25 per page' })).toBeInTheDocument()
    expect(within(recentActivity).getByRole('button', { name: 'Show 50 per page' })).toBeInTheDocument()
    expect(within(recentActivity).getByRole('button', { name: 'Go to page 1' })).toHaveAttribute('aria-current', 'page')
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 2' })).not.toBeInTheDocument()
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 3' })).not.toBeInTheDocument()
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 7' })).not.toBeInTheDocument()
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 9' })).not.toBeInTheDocument()

    await user.click(within(recentActivity).getByRole('button', { name: 'Next page' }))
    expect(within(recentActivity).getByRole('button', { name: 'Go to page 2' })).toHaveAttribute('aria-current', 'page')
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 1' })).not.toBeInTheDocument()
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 3' })).not.toBeInTheDocument()

    await user.click(within(recentActivity).getByRole('button', { name: 'Show 25 per page' }))
    expect(within(recentActivity).getByRole('button', { name: 'Show 25 per page' })).toHaveAttribute('aria-current', 'page')
    expect(within(recentActivity).getByRole('button', { name: 'Go to page 1' })).toHaveAttribute('aria-current', 'page')
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 2' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter memory activity by type' }))
    await user.click(screen.getByRole('menuitemcheckbox', { name: /Case/ }))
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Older case activity entry')).toBeInTheDocument()
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 2' })).not.toBeInTheDocument()
  })

  it('resets time range when selecting a memory category card', async () => {
    const user = userEvent.setup()
    renderPage()

    const recentActivity = await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '本周' }))
    expect(within(recentActivity).queryByText('Older profile activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Profiles' }))
    expect(screen.getByRole('tab', { name: '全部时间' })).toHaveAttribute('data-state', 'active')
    expect(within(recentActivity).getByText('Profile activity entry')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Older profile activity entry')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '本周' }))
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Episodes' }))
    expect(screen.getByRole('tab', { name: '全部时间' })).toHaveAttribute('data-state', 'active')
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getByRole('button', { name: 'Go to page 1' })).toHaveAttribute('aria-current', 'page')
    expect(within(recentActivity).queryByRole('button', { name: 'Go to page 2' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '本周' }))
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Cases' }))
    expect(screen.getByRole('tab', { name: '全部时间' })).toHaveAttribute('data-state', 'active')
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Older case activity entry')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '本周' }))
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Skills' }))
    expect(screen.getByRole('tab', { name: '全部时间' })).toHaveAttribute('data-state', 'active')
    expect(within(recentActivity).getByText('Skill activity entry')).toBeInTheDocument()
  })

  it('renders recent activity table with Chinese headers and one-line absolute time', async () => {
    renderPage()

    const recentActivity = await screen.findByTestId('recent-memory-activity')
    expect(within(recentActivity).getByRole('columnheader', { name: '时间' })).toBeInTheDocument()
    expect(within(recentActivity).getByRole('columnheader', { name: '操作' })).toBeInTheDocument()
    expect(within(recentActivity).getByRole('columnheader', { name: '记忆类型' })).toBeInTheDocument()
    expect(within(recentActivity).getByRole('columnheader', { name: '标题' })).toBeInTheDocument()
    expect(within(recentActivity).queryByRole('columnheader', { name: '摘要' })).not.toBeInTheDocument()
    expect(within(recentActivity).getByRole('columnheader', { name: '详情' })).toBeInTheDocument()
    expect(within(recentActivity).getByText('2026-07-10 10:00')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getAllByText('源文件：users/user-1/episodes/episode-2026-07-10.md').length).toBeGreaterThan(0)
    expect(within(recentActivity).getByText('源文件：users/user-2/episodes/episode-2026-07-10.md')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('源文件：episode-2026-07-10.md')).not.toBeInTheDocument()
  })

  it('uses each memory type structured title fields in recent activity rows', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Episodes' }))
    const recentActivity = screen.getByTestId('recent-memory-activity')

    expect(within(recentActivity).getByText('Episode detail subject')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Second episode database subject')).toBeInTheDocument()
    expect(within(recentActivity).queryByText('Second episode activity entry')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Cases' }))
    expect(within(recentActivity).getByText('Case activity entry')).toBeInTheDocument()
    expect(within(recentActivity).getByText('Older case activity entry')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Skills' }))
    expect(within(recentActivity).getByText('Skill activity entry')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Profiles' }))
    expect(within(recentActivity).getByText('Profile activity entry')).toBeInTheDocument()
  })

  it('renders user memory episodes as a compact timeline', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const timeline = screen.getByTestId('user-episode-timeline')
    expect(timeline.querySelector('.bg-amber-500')).not.toBeNull()
    expect(within(timeline).getAllByText(/07\/10\/2026/).length).toBeGreaterThan(0)
    expect(within(timeline).getByRole('heading', { name: 'Episode detail subject' })).toBeInTheDocument()
    expect(within(timeline).getAllByText('user ID: user-1').length).toBeGreaterThan(0)
    expect(within(timeline).getAllByText(/session ID: session-1/).length).toBeGreaterThan(0)
    expect(within(timeline).getByRole('button', { name: '按来源会话筛选 session-1' })).toHaveTextContent('来源会话: session-1')
    expect(within(timeline).getByRole('button', { name: '按来源会话筛选 session-2' })).toHaveTextContent('session-2')
    expect(within(timeline).queryByText('Episode activity entry')).not.toBeInTheDocument()
    expect(within(timeline).queryByText('Second episode activity entry')).not.toBeInTheDocument()
    expect(within(timeline).queryByText(/episode-2026-07-10\.md/)).not.toBeInTheDocument()
  })

  it('starts Dreaming from the Episodes header and polls the run status', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const episodeSection = screen.getByTestId('episode-memory-section')
    const dreamingButton = within(episodeSection).getByRole('button', { name: 'Start Dreaming for Episodes' })

    await user.click(dreamingButton)

    expect(managedPostMock).toHaveBeenCalledWith('/everos_memory/dreaming', { timeout: 120 })
    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/dreaming/runs/run-1')
    })
    expect(dreamingButton).toHaveTextContent('Dreaming run...')
    expect(dreamingButton).toHaveClass('min-w-[180px]')
  })

  it('keeps Dreaming running while the run status request is still loading', async () => {
    let resolveRunStatus: (value: unknown) => void = () => {}
    managedGetMock.mockImplementation((path: string) => {
      if (path.startsWith('/everos_memory/dreaming/runs/')) {
        return new Promise((resolve) => {
          resolveRunStatus = resolve
        })
      }
      return Promise.resolve(overviewFixture())
    })
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const episodeSection = screen.getByTestId('episode-memory-section')
    await user.click(within(episodeSection).getByRole('button', { name: 'Start Dreaming for Episodes' }))

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/dreaming/runs/run-1')
    })
    expect(within(episodeSection).getByRole('button', { name: 'Start Dreaming for Episodes' })).toHaveTextContent('Dreaming run...')
    expect(within(episodeSection).queryByText('Dreaming queued')).not.toBeInTheDocument()

    resolveRunStatus({
      run_id: 'run-1',
      strategy_name: 'reflect_episodes',
      status: 'running',
      error: null,
    })
  })

  it('keeps Dreaming running visible briefly when a fast run finishes before the first status poll returns', async () => {
    vi.useRealTimers()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-07-10T12:00:00+08:00'))
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.startsWith('/everos_memory/dreaming/runs/')) {
        return {
          run_id: 'run-1',
          strategy_name: 'reflect_episodes',
          status: 'success',
          attempt: 0,
          started_at: '2026-07-10T04:00:00Z',
          finished_at: '2026-07-10T04:00:00.070Z',
          error: null,
          event_topic: 'app.everos.infra.ome.events:ManualTick',
          event_payload: '{}',
          max_retries_snapshot: 1,
          event_id: 'event-1',
          display_name: 'Dreaming',
        }
      }
      return overviewFixture()
    })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const episodeSection = screen.getByTestId('episode-memory-section')
    await user.click(within(episodeSection).getByRole('button', { name: 'Start Dreaming for Episodes' }))

    await waitFor(() => {
      expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/dreaming/runs/run-1')
    })
    const dreamingButton = within(episodeSection).getByRole('button', { name: 'Start Dreaming for Episodes' })
    expect(dreamingButton).toHaveTextContent('Dreaming run...')
    expect(dreamingButton).not.toHaveTextContent('Dreaming Complete')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(DREAMING_MIN_RUNNING_MS + 1)
    })

    await waitFor(() => {
      expect(dreamingButton).toHaveTextContent('Dreaming Complete')
    })
  })

  it('filters the episode timeline to all aggregated memories from the aggregated badge', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const timeline = screen.getByTestId('user-episode-timeline')
    await user.click(within(timeline).getAllByRole('button', { name: '筛选聚合记忆' })[0])

    expect(screen.getByText('aggregated: 聚合记忆')).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Aggregated security audit memory' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Aggregated project planning memory' })).toBeInTheDocument()
    expect(within(timeline).queryByRole('heading', { name: 'Episode detail subject' })).not.toBeInTheDocument()
    expect(within(timeline).queryByRole('heading', { name: 'Imported episode without session' })).not.toBeInTheDocument()
  })

  it('filters aggregated memories from a source session badge', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const timeline = screen.getByTestId('user-episode-timeline')
    await user.click(within(timeline).getByRole('button', { name: '按来源会话筛选 session-user-2' }))

    expect(screen.getByText('session: session-user-2')).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'User two episode subject' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Aggregated project planning memory' })).toBeInTheDocument()
    expect(within(timeline).queryByRole('heading', { name: 'Aggregated security audit memory' })).not.toBeInTheDocument()
  })

  it('shows explicit info and implicit traits when a user profile is expanded', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    expect(screen.getByText('Profile activity entry')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: '展开 Profile 详情' })[0])

    expect(screen.getByText('显式信息')).toBeInTheDocument()
    expect(screen.getByText('隐式特征')).toBeInTheDocument()
    expect(screen.getByText(/饮食偏好/)).toBeInTheDocument()
    expect(screen.getByText(/用户明确表示自己喜欢食用香蕉。/)).toBeInTheDocument()
    expect(screen.getByText(/主动记录型/)).toBeInTheDocument()
    expect(screen.getByText(/用户倾向于主动向系统提供个人偏好信息。/)).toBeInTheDocument()
    expect(screen.queryByText(/profiles\/profile-1\.md/)).not.toBeInTheDocument()
  })

  it('selects a user profile card to filter episodes without expanding profile details', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const profileCard = screen.getByRole('button', { name: /选择 Profile User user-2/ })
    await user.click(profileCard)

    expect(screen.getByText('user: user-2')).toBeInTheDocument()
    expect(screen.queryByText('显式信息')).not.toBeInTheDocument()

    const timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'User two episode subject' })).toBeInTheDocument()
    expect(within(timeline).queryByRole('heading', { name: 'Episode detail subject' })).not.toBeInTheDocument()
  })

  it('clears the episode owner filter by clicking the selected profile card again', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const profileCard = screen.getByRole('button', { name: /选择 Profile User user-2/ })
    await user.click(profileCard)

    expect(screen.getByText('user: user-2')).toBeInTheDocument()

    await user.click(profileCard)

    expect(screen.queryByText('user: user-2')).not.toBeInTheDocument()

    const timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Episode detail subject' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'User two episode subject' })).toBeInTheDocument()
  })

  it('expands a user profile from its arrow without selecting it', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    await user.click(screen.getAllByRole('button', { name: '展开 Profile 详情' })[1])

    expect(screen.queryByText('user: user-2')).not.toBeInTheDocument()
    expect(screen.getByText('显式信息')).toBeInTheDocument()
    expect(screen.getByText('隐式特征')).toBeInTheDocument()

    const timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'User two episode subject' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Episode detail subject' })).toBeInTheDocument()
  })

  it('keeps the selected profile episode filter when expanding an episode detail', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))
    await user.click(screen.getByRole('button', { name: /选择 Profile User user-2/ }))

    let timeline = screen.getByTestId('user-episode-timeline')
    expect(screen.getByText('user: user-2')).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'User two episode subject' })).toBeInTheDocument()
    expect(within(timeline).queryByRole('heading', { name: 'Episode detail subject' })).not.toBeInTheDocument()

    await user.click(within(timeline).getByRole('button', { name: '展开 Episode 详情' }))

    expect(screen.getByText('user: user-2')).toBeInTheDocument()
    timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'User two episode subject' })).toBeInTheDocument()
    expect(within(timeline).queryByRole('heading', { name: 'Episode detail subject' })).not.toBeInTheDocument()
    expect(await screen.findByText('User two complete markdown body.')).toBeInTheDocument()
  })

  it('routes profile detail actions to the inline user profile entry', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Profiles' }))
    const recentActivity = screen.getByTestId('recent-memory-activity')
    await user.click(within(recentActivity).getAllByRole('button', { name: '详情' })[0])

    expect(screen.getByRole('tab', { name: '用户记忆' })).toHaveAttribute('data-state', 'active')
    expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/document?md_path=profiles%2Fprofile-1.md')
    expect(await screen.findByText(/Complete profile markdown body\./)).toBeInTheDocument()
    expect(screen.queryByText('内容')).not.toBeInTheDocument()
    expect(screen.queryByText(/type: user_profile/)).not.toBeInTheDocument()
    expect(screen.queryByText(/explicit_info/)).not.toBeInTheDocument()
    expect(screen.queryByText(/implicit_traits/)).not.toBeInTheDocument()
    expect(screen.queryByText(/profile_timestamp_ms/)).not.toBeInTheDocument()
    expect(screen.queryByText(/profiles\/profile-1\.md/)).not.toBeInTheDocument()
  })

  it('filters user memory episodes by clicking owner or session chips', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    let timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Episode detail subject' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Second episode database subject' })).toBeInTheDocument()
    expect(within(timeline).getAllByText('user ID: user-1').length).toBeGreaterThan(0)

    await user.click(within(timeline).getByRole('button', { name: '按会话筛选 session-1' }))

    expect(screen.getByText('session: session-1')).toBeInTheDocument()
    timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Episode detail subject' })).toBeInTheDocument()
    expect(within(timeline).queryByRole('heading', { name: 'Second episode database subject' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '清除 Episode 筛选' }))

    timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Episode detail subject' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Second episode database subject' })).toBeInTheDocument()

    await user.click(within(timeline).getAllByRole('button', { name: '按用户筛选 user-1' })[0])
    expect(screen.getByText('user: user-1')).toBeInTheDocument()
  })

  it('expands a user memory episode from the timeline row', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const timeline = screen.getByTestId('user-episode-timeline')
    await user.click(within(timeline).getAllByRole('button', { name: '展开 Episode 详情' })[0])

    expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/document?md_path=joysafeter%2Fproject-1%2Fusers%2Fuser-1%2Fepisodes%2Fepisode-2026-07-10.md')
    expect(await within(timeline).findByText('Subject')).toBeInTheDocument()
    expect(within(timeline).getByText('Summary')).toBeInTheDocument()
    expect(within(timeline).getByText('Content')).toBeInTheDocument()
    expect(within(timeline).getByText(/Complete markdown body\./)).toBeInTheDocument()
    expect(within(timeline).getByText('关联事实')).toBeInTheDocument()
    expect(within(timeline).getByText('用户正在确认 Episode 展开时展示直接抽取的事实。')).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Second episode database subject' })).toBeInTheDocument()
    expect(within(timeline).queryByText(/Second complete markdown body\./)).not.toBeInTheDocument()
    expect(within(timeline).queryByText('这是同一 session 中另一条 Episode 的事实，不应展示在第一条下。')).not.toBeInTheDocument()
  })

  it('filters and expands agent cases from the timeline row', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))

    let timeline = screen.getByTestId('agent-case-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Case activity entry' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Older case activity entry' })).toBeInTheDocument()
    expect(within(timeline).getByText('质量 91%')).toBeInTheDocument()
    expect(within(timeline).getByText('agent ID: agent-1')).toBeInTheDocument()
    expect(within(timeline).queryByText(/quality/i)).not.toBeInTheDocument()
    expect(within(timeline).queryByText('Use the selected recent activity to focus the agent memory list.')).not.toBeInTheDocument()

    await user.click(within(timeline).getByRole('button', { name: '按会话筛选 session-case-1' }))
    expect(screen.getByText('session: session-case-1')).toBeInTheDocument()
    timeline = screen.getByTestId('agent-case-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Case activity entry' })).toBeInTheDocument()
    expect(within(timeline).queryByRole('heading', { name: 'Older case activity entry' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '清除 Agent Case 筛选' }))
    timeline = screen.getByTestId('agent-case-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Older case activity entry' })).toBeInTheDocument()

    await user.click(within(timeline).getAllByRole('button', { name: '展开 Case 详情' })[0])
    expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/document?md_path=cases%2Fcase-1.md')
    expect(await within(timeline).findByText('TaskIntent')).toBeInTheDocument()
    expect(within(timeline).getByText(/Complete case markdown body\./)).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Older case activity entry' })).toBeInTheDocument()
  })

  it('filters and expands agent skills from the skill cards', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))

    let skills = screen.getByTestId('agent-skill-list')
    expect(within(skills).getByRole('heading', { name: 'Skill activity entry' })).toBeInTheDocument()
    expect(within(skills).getByRole('heading', { name: 'Second skill entry' })).toBeInTheDocument()
    expect(within(skills).getByText('质量 80%')).toBeInTheDocument()
    expect(within(skills).queryByText('置信度')).not.toBeInTheDocument()
    expect(within(skills).queryByText('成熟度')).not.toBeInTheDocument()
    expect(within(skills).getByRole('button', { name: '按智能体筛选 agent-1' })).toBeInTheDocument()
    expect(within(skills).getByText(/The final diagnostic sentence must remain visible/)).toBeInTheDocument()
    expect(within(skills).queryByText('Skill')).not.toBeInTheDocument()
    expect(within(skills).queryByText(/cluster/)).not.toBeInTheDocument()
    expect(within(skills).queryByText(/source cases/)).not.toBeInTheDocument()
    expect(within(skills).queryByText(/skills\/skill-1\.md/)).not.toBeInTheDocument()

    await user.click(within(skills).getByRole('button', { name: '按智能体筛选 agent-1' }))
    expect(screen.getByText('agent: agent-1')).toBeInTheDocument()
    skills = screen.getByTestId('agent-skill-list')
    expect(within(skills).getByRole('heading', { name: 'Skill activity entry' })).toBeInTheDocument()
    expect(within(skills).queryByRole('heading', { name: 'Second skill entry' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '清除 Agent Skill 筛选' }))
    skills = screen.getByTestId('agent-skill-list')
    await user.click(within(skills).getAllByRole('button', { name: '展开 Skill 详情' })[0])

    expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/document?md_path=skills%2Fskill-1.md')
    expect(await within(skills).findByText('Name')).toBeInTheDocument()
    expect(within(skills).getByText('Description')).toBeInTheDocument()
    expect(within(skills).getByText('Content')).toBeInTheDocument()
    expect(within(skills).getByRole('heading', { name: 'Potential Steps' })).toBeInTheDocument()
    expect(within(skills).getByText(/Complete skill markdown body\./)).toBeInTheDocument()
    expect(within(skills).getByText('Rendered skill step').closest('li')).not.toBeNull()
    expect(within(skills).queryByText(/schema_version/)).not.toBeInTheDocument()
    expect(within(skills).queryByText(/source_case_ids/)).not.toBeInTheDocument()
    expect(within(skills).queryByText(/cluster_id/)).not.toBeInTheDocument()
    expect(within(skills).getByRole('heading', { name: 'Second skill entry' })).toBeInTheDocument()
  })

  it('paginates profile episode case and skill panels independently', async () => {
    const fixture = overviewFixture()
    fixture.profiles = Array.from({ length: 12 }, (_, index) => {
      const number = index + 1
      return {
        id: `profile-page-${number}`,
        owner_id: `user-page-${number}`,
        summary: `Paged profile ${number}`,
        explicit_info_json: '[]',
        implicit_traits_json: '[]',
        timestamp_ms: Date.now() - number * 60 * 1000,
        md_path: `profiles/paged-profile-${number}.md`,
      }
    })
    fixture.episodes = Array.from({ length: 12 }, (_, index) => {
      const number = index + 1
      return {
        id: `episode-page-${number}`,
        entry_id: `ep_20260710_page_${number}`,
        owner_id: 'user-page-1',
        session_id: `session-page-${number}`,
        timestamp: new Date(Date.now() - number * 60 * 1000).toISOString(),
        subject: `Paged episode ${number}`,
        summary: `Paged episode summary ${number}`,
        episode: `Paged episode content ${number}.`,
        md_path: `episodes/paged-episode-${number}.md`,
      }
    })
    fixture.agent_cases = Array.from({ length: 12 }, (_, index) => {
      const number = index + 1
      return {
        id: `case-page-${number}`,
        entry_id: `case_20260710_page_${number}`,
        owner_id: 'agent-page-1',
        session_id: `case-session-page-${number}`,
        timestamp: new Date(Date.now() - number * 60 * 1000).toISOString(),
        task_intent: `Paged case ${number}`,
        approach: `Paged case approach ${number}`,
        key_insight: `Paged case insight ${number}`,
        quality_score: 0.5,
        md_path: `cases/paged-case-${number}.md`,
      }
    })
    fixture.agent_skills = Array.from({ length: 12 }, (_, index) => {
      const number = index + 1
      return {
        id: `skill-page-${number}`,
        owner_id: 'agent-page-1',
        name: `Paged skill ${number}`,
        description: `Paged skill description ${number}`,
        content: `Paged skill content ${number}.`,
        confidence: 0.5,
        maturity_score: 0.5,
        source_case_ids: [],
        cluster_id: `skill-cluster-${number}`,
        md_path: `skills/paged-skill-${number}.md`,
      }
    })
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.startsWith('/everos_memory/document')) {
        return { md_path: 'paged.md', content: 'Content\nPaged markdown body.' }
      }
      return fixture
    })

    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const profiles = screen.getByTestId('profile-memory-section')
    const episodes = screen.getByTestId('episode-memory-section')
    expect(within(profiles).getByText('Paged profile 1')).toBeInTheDocument()
    expect(within(profiles).queryByText('Paged profile 11')).not.toBeInTheDocument()
    expect(within(episodes).getByRole('heading', { name: 'Paged episode 1' })).toBeInTheDocument()
    expect(within(episodes).queryByRole('heading', { name: 'Paged episode 11' })).not.toBeInTheDocument()

    await user.click(within(profiles).getByRole('button', { name: 'Next page' }))
    expect(within(profiles).getByText('Paged profile 11')).toBeInTheDocument()
    expect(within(episodes).getByRole('heading', { name: 'Paged episode 1' })).toBeInTheDocument()

    await user.click(within(episodes).getByRole('button', { name: 'Next page' }))
    expect(within(episodes).getByRole('heading', { name: 'Paged episode 11' })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))
    const cases = screen.getByTestId('agent-case-section')
    const skills = screen.getByTestId('agent-skill-section')
    expect(within(cases).getByRole('heading', { name: 'Paged case 1' })).toBeInTheDocument()
    expect(within(cases).queryByRole('heading', { name: 'Paged case 11' })).not.toBeInTheDocument()
    expect(within(skills).getByRole('heading', { name: 'Paged skill 1' })).toBeInTheDocument()
    expect(within(skills).queryByRole('heading', { name: 'Paged skill 11' })).not.toBeInTheDocument()

    await user.click(within(cases).getByRole('button', { name: 'Next page' }))
    expect(within(cases).getByRole('heading', { name: 'Paged case 11' })).toBeInTheDocument()
    expect(within(skills).getByRole('heading', { name: 'Paged skill 1' })).toBeInTheDocument()

    await user.click(within(skills).getByRole('button', { name: 'Next page' }))
    expect(within(skills).getByRole('heading', { name: 'Paged skill 11' })).toBeInTheDocument()
  })

  it('shows disabled pagination arrows for single-page memory panels', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '用户记忆' }))

    const profiles = screen.getByTestId('profile-memory-section')
    const episodes = screen.getByTestId('episode-memory-section')
    expect(within(profiles).getByRole('button', { name: 'Previous page' })).toBeDisabled()
    expect(within(profiles).getByRole('button', { name: 'Go to page 1' })).toHaveAttribute('aria-current', 'page')
    expect(within(profiles).getByRole('button', { name: 'Next page' })).toBeDisabled()
    expect(within(episodes).getByRole('button', { name: 'Previous page' })).toBeDisabled()
    expect(within(episodes).getByRole('button', { name: 'Go to page 1' })).toHaveAttribute('aria-current', 'page')
    expect(within(episodes).getByRole('button', { name: 'Next page' })).toBeDisabled()

    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))

    const cases = screen.getByTestId('agent-case-section')
    const skills = screen.getByTestId('agent-skill-section')
    expect(within(cases).getByRole('button', { name: 'Previous page' })).toBeDisabled()
    expect(within(cases).getByRole('button', { name: 'Go to page 1' })).toHaveAttribute('aria-current', 'page')
    expect(within(cases).getByRole('button', { name: 'Next page' })).toBeDisabled()
    expect(within(skills).getByRole('button', { name: 'Previous page' })).toBeDisabled()
    expect(within(skills).getByRole('button', { name: 'Go to page 1' })).toHaveAttribute('aria-current', 'page')
    expect(within(skills).getByRole('button', { name: 'Next page' })).toBeDisabled()
  })

  it('selects an agent skill card to filter agent cases by agent id without expanding skill details', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))

    const skills = screen.getByTestId('agent-skill-list')
    await user.click(within(skills).getByRole('button', { name: /选择 Agent Skill Skill activity entry/ }))

    expect(screen.getByText('agent: agent-1')).toBeInTheDocument()
    expect(within(skills).queryByText('Name')).not.toBeInTheDocument()

    const cases = screen.getByTestId('agent-case-timeline')
    expect(within(cases).getByRole('heading', { name: 'Case activity entry' })).toBeInTheDocument()
    expect(within(cases).queryByRole('heading', { name: 'Older case activity entry' })).not.toBeInTheDocument()
  })

  it('clears the agent case agent filter by clicking the selected agent skill card again', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))

    const skills = screen.getByTestId('agent-skill-list')
    const skillCard = within(skills).getByRole('button', { name: /选择 Agent Skill Skill activity entry/ })
    await user.click(skillCard)
    expect(screen.getByText('agent: agent-1')).toBeInTheDocument()

    await user.click(skillCard)

    expect(screen.queryByText('agent: agent-1')).not.toBeInTheDocument()
    const cases = screen.getByTestId('agent-case-timeline')
    expect(within(cases).getByRole('heading', { name: 'Case activity entry' })).toBeInTheDocument()
    expect(within(cases).getByRole('heading', { name: 'Older case activity entry' })).toBeInTheDocument()
  })

  it('expands an agent skill without selecting it', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))

    const skills = screen.getByTestId('agent-skill-list')
    await user.click(within(skills).getAllByRole('button', { name: '展开 Skill 详情' })[0])

    expect(screen.queryByText('agent: agent-1')).not.toBeInTheDocument()
    expect(await within(skills).findByText('Name')).toBeInTheDocument()

    const cases = screen.getByTestId('agent-case-timeline')
    expect(within(cases).getByRole('heading', { name: 'Case activity entry' })).toBeInTheDocument()
    expect(within(cases).getByRole('heading', { name: 'Older case activity entry' })).toBeInTheDocument()
  })

  it('does not render the generic content label above agent skill markdown body', async () => {
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.startsWith('/everos_memory/document')) {
        return {
          md_path: 'skills/skill-1.md',
          content: [
            'id: skill-1 type: agent_skill',
            'schema_version: 1 agent_id: agent-1 track: agent',
            'source_case_ids:',
            '- case-1 cluster_id: cluster-1 created_at: null updated_at: null',
            '',
            '## Potential Steps',
            '',
            '**Complete skill markdown body.**',
          ].join('\n'),
        }
      }
      return overviewFixture()
    })

    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('tab', { name: '智能体记忆' }))

    const skills = screen.getByTestId('agent-skill-list')
    await user.click(within(skills).getAllByRole('button', { name: '展开 Skill 详情' })[0])

    expect(await within(skills).findByRole('heading', { name: 'Potential Steps' })).toBeInTheDocument()
    expect(within(skills).queryByText('内容')).not.toBeInTheDocument()
  })

  it('routes episode detail actions to the focused user memory entry', async () => {
    const user = userEvent.setup()
    const scrollIntoViewMock = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoViewMock
    renderPage()

    const recentActivity = await screen.findByTestId('recent-memory-activity')
    await clickActivityDetailByTitle(user, recentActivity, 'Episode detail subject')

    expect(screen.getByRole('tab', { name: '用户记忆' })).toHaveAttribute('data-state', 'active')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByText('Profile activity entry')).toBeInTheDocument()
    const timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Episode detail subject' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Second episode database subject' })).toBeInTheDocument()
    expect(within(timeline).getAllByText(/07\/10\/2026/).length).toBeGreaterThan(0)
    expect(within(timeline).getAllByText('user ID: user-1').length).toBeGreaterThan(0)
    expect(within(timeline).getByText(/session ID: session-1/)).toBeInTheDocument()
    expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/document?md_path=joysafeter%2Fproject-1%2Fusers%2Fuser-1%2Fepisodes%2Fepisode-2026-07-10.md')
    expect(await within(timeline).findByText('Subject')).toBeInTheDocument()
    expect(within(timeline).getByText('Summary')).toBeInTheDocument()
    expect(within(timeline).getByText('Content')).toBeInTheDocument()
    expect(within(timeline).getByText(/Complete markdown body\./)).toBeInTheDocument()
    await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalled())
    expect(within(timeline).queryAllByRole('button', { name: '展开 Episode 详情' })).toHaveLength(0)
    expect(within(timeline).getByRole('button', { name: '收起 Episode 详情' })).toBeInTheDocument()
    expect(screen.queryByText(/### Subject/)).not.toBeInTheDocument()
    expect(screen.queryByText(/<!-- entry:/)).not.toBeInTheDocument()
    expect(screen.queryByText('ep_20260710_00000001')).not.toBeInTheDocument()
    expect(screen.queryByText(/\*\*owner_id\*\*/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\*\*session_id\*\*/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\*\*sender_ids\*\*/)).not.toBeInTheDocument()
    expect(screen.queryByText(/源文件：/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Second complete markdown body\./)).not.toBeInTheDocument()
  })

  it('shows the matching entry block when two episode rows share one md file', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Episodes' }))
    const recentActivity = screen.getByTestId('recent-memory-activity')
    await clickActivityDetailByTitle(user, recentActivity, 'Second episode database subject')

    expect(screen.getByRole('tab', { name: '用户记忆' })).toHaveAttribute('data-state', 'active')
    const timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Episode detail subject' })).toBeInTheDocument()
    expect(within(timeline).getByRole('heading', { name: 'Second episode database subject' })).toBeInTheDocument()
    expect(await within(timeline).findByText(/Second complete markdown body\./)).toBeInTheDocument()
    expect(screen.queryByText(/Complete markdown body\./)).not.toBeInTheDocument()
  })

  it('expands only the matching episode entry when rows share an id', async () => {
    const fixture = overviewFixture()
    fixture.episodes[0].id = 'shared-episode-id'
    fixture.episodes[1].id = 'shared-episode-id'
    fixture.recent_activity[7].id = 'shared-episode-id'
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.startsWith('/everos_memory/document')) {
        return {
          md_path: 'episodes/episode-1.md',
          content: [
            '<!-- entry:ep_20260710_00000001 -->',
            'Subject',
            'Episode detail subject',
            '',
            'Content',
            'Complete markdown body.',
            '<!-- /entry:ep_20260710_00000001 -->',
            '',
            '<!-- entry:ep_20260710_00000002 -->',
            'Subject',
            'Second episode database subject',
            '',
            'Content',
            'Second complete markdown body.',
            '<!-- /entry:ep_20260710_00000002 -->',
          ].join('\n'),
        }
      }
      return fixture
    })

    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Episodes' }))
    const recentActivity = screen.getByTestId('recent-memory-activity')
    await clickActivityDetailByTitle(user, recentActivity, 'Second episode database subject')

    const timeline = screen.getByTestId('user-episode-timeline')
    expect(await within(timeline).findByText(/Second complete markdown body\./)).toBeInTheDocument()
    expect(within(timeline).queryByText(/Complete markdown body\./)).not.toBeInTheDocument()
    expect(within(timeline).getAllByRole('button', { name: '收起 Episode 详情' })).toHaveLength(1)
  })

  it('does not expand episode rows that share an entry id across different md files', async () => {
    const fixture = overviewFixture()
    fixture.episodes.push({
      id: 'episode-duplicate-entry-id',
      entry_id: 'ep_20260710_00000001',
      owner_id: 'user-2',
      session_id: 'session-duplicate',
      timestamp: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(),
      subject: 'Duplicate entry id in another memory file',
      summary: 'Different memory file with reused entry id.',
      episode: 'Different episode content.',
      md_path: 'joysafeter/project-1/users/user-2/episodes/episode-2026-07-10.md',
    })
    managedGetMock.mockImplementation(async (path: string) => {
      if (path.startsWith('/everos_memory/document')) {
        return {
          md_path: 'joysafeter/project-1/users/user-1/episodes/episode-2026-07-10.md',
          content: [
            '<!-- entry:ep_20260710_00000001 -->',
            'Subject',
            'Episode detail subject',
            '',
            'Content',
            'Complete markdown body.',
            '<!-- /entry:ep_20260710_00000001 -->',
          ].join('\n'),
        }
      }
      return fixture
    })

    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Episodes' }))
    const recentActivity = screen.getByTestId('recent-memory-activity')
    await user.click(within(recentActivity).getAllByRole('button', { name: '详情' })[0])

    const timeline = screen.getByTestId('user-episode-timeline')
    expect(within(timeline).getByRole('heading', { name: 'Duplicate entry id in another memory file' })).toBeInTheDocument()
    expect(await within(timeline).findByText(/Complete markdown body\./)).toBeInTheDocument()
    expect(within(timeline).getAllByRole('button', { name: '收起 Episode 详情' })).toHaveLength(1)
  })

  it('routes case detail actions to the focused agent memory entry', async () => {
    const user = userEvent.setup()
    const scrollIntoViewMock = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoViewMock
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Cases' }))
    const recentActivity = screen.getByTestId('recent-memory-activity')
    await user.click(within(recentActivity).getAllByRole('button', { name: '详情' })[0])

    expect(screen.getByRole('tab', { name: '智能体记忆' })).toHaveAttribute('data-state', 'active')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const caseTimeline = screen.getByTestId('agent-case-timeline')
    expect(within(caseTimeline).getByRole('heading', { name: 'Case activity entry' })).toBeInTheDocument()
    expect(within(caseTimeline).getByRole('heading', { name: 'Older case activity entry' })).toBeInTheDocument()
    expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/document?md_path=cases%2Fcase-1.md')
    expect(await within(caseTimeline).findByText('TaskIntent')).toBeInTheDocument()
    expect(within(caseTimeline).getByText(/Complete case markdown body\./)).toBeInTheDocument()
    await waitFor(() => expect(scrollIntoViewMock).toHaveBeenCalled())
    expect(within(caseTimeline).queryAllByRole('button', { name: '展开 Case 详情' })).toHaveLength(0)
    expect(within(caseTimeline).getByRole('button', { name: '收起 Case 详情' })).toBeInTheDocument()
    expect(within(caseTimeline).queryByText('Use the selected recent activity to focus the agent memory list.')).not.toBeInTheDocument()
  })

  it('routes skill detail actions to the inline agent skill entry', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByTestId('recent-memory-activity')
    await user.click(screen.getByRole('button', { name: 'Filter recent activity by Skills' }))
    const recentActivity = screen.getByTestId('recent-memory-activity')
    await user.click(within(recentActivity).getAllByRole('button', { name: '详情' })[0])

    expect(screen.getByRole('tab', { name: '智能体记忆' })).toHaveAttribute('data-state', 'active')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const skills = screen.getByTestId('agent-skill-list')
    expect(within(skills).getByRole('heading', { name: 'Skill activity entry' })).toBeInTheDocument()
    expect(within(skills).getByRole('heading', { name: 'Second skill entry' })).toBeInTheDocument()
    expect(managedGetMock).toHaveBeenCalledWith('/everos_memory/document?md_path=skills%2Fskill-1.md')
    expect(await within(skills).findByText(/Complete skill markdown body\./)).toBeInTheDocument()
  })
})
