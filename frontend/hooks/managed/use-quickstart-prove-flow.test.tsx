import { act, renderHook } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { beforeAll, describe, expect, it } from 'vitest'

import type { SessionEvent } from '@/types/managed'

import {
  filterAndMergeQuickstartPreviewEvents,
  useQuickstartProveFlow,
} from './use-quickstart-prove-flow'

beforeAll(() => {
  if (typeof document === 'undefined') {
    const dom = new JSDOM('<!doctype html><html><body></body></html>')
    Object.assign(globalThis, {
      window: dom.window,
      document: dom.window.document,
      navigator: dom.window.navigator,
    })
  }
})

function event(id: string, type: string, content?: string): SessionEvent {
  return { id, type, ...(content ? { content } : {}) } as SessionEvent
}

function renderProveFlow(scopeKey = 'org-a/project-a', events: SessionEvent[] = []) {
  return renderHook(
    ({ scope, sessionEvents }) =>
      useQuickstartProveFlow({
        scopeKey: scope,
        isSessionActive: true,
        events: sessionEvents,
        task: null,
        environmentId: null,
        externalToolsAuthorized: false,
        agentConfig: {},
        agentMcpServerUrls: [],
        availableSkills: [],
      }),
    { initialProps: { scope: scopeKey, sessionEvents: events } },
  )
}

describe('filterAndMergeQuickstartPreviewEvents', () => {
  it('filters transcript events and merges adjacent message chunks', () => {
    const result = filterAndMergeQuickstartPreviewEvents({
      events: [
        event('1', 'agent.message', 'hello '),
        event('2', 'agent.message', 'world'),
        event('3', 'agent.thinking', 'hidden'),
      ],
      tab: 'transcript',
      filter: new Set(),
      search: '',
    })

    expect(result).toHaveLength(1)
    expect(result[0].content).toEqual([{ type: 'text', text: 'hello world' }])
  })

  it('applies debug filters and search before merging', () => {
    const result = filterAndMergeQuickstartPreviewEvents({
      events: [
        event('1', 'agent.message', 'alpha'),
        event('2', 'agent.tool_use', 'beta'),
        event('3', 'agent.tool_use', 'needle'),
      ],
      tab: 'debug',
      filter: new Set(['agent.tool_use']),
      search: 'needle',
    })

    expect(result.map((item) => item.id)).toEqual(['3'])
  })
})

describe('useQuickstartProveFlow', () => {
  it('owns preview interactions and resets them across scopes', () => {
    const selected = event('1', 'agent.message', 'hello')
    const view = renderProveFlow('org-a/project-a', [selected])

    act(() => {
      view.result.current.preview.setFilter(new Set(['agent.message']))
      view.result.current.preview.setSearch('hello')
      view.result.current.preview.toggleSearch()
      view.result.current.preview.selectEvent(selected)
    })
    expect(view.result.current.preview).toMatchObject({
      tab: 'debug',
      search: 'hello',
      showSearch: true,
      selectedEvent: selected,
    })

    view.rerender({ scope: 'org-a/project-b', sessionEvents: [] })

    expect(view.result.current.preview).toMatchObject({
      tab: 'debug',
      search: '',
      showSearch: false,
      selectedEvent: null,
    })
    expect(view.result.current.preview.filter.size).toBe(0)
  })

  it('switches transcript and event selection through controller actions', () => {
    const selected = event('1', 'agent.message', 'hello')
    const view = renderProveFlow('org-a/project-a', [selected])

    act(() => view.result.current.preview.selectEvent(selected))
    act(() => view.result.current.preview.showTranscript())
    expect(view.result.current.preview.tab).toBe('transcript')
    expect(view.result.current.preview.selectedEvent).toBeNull()

    act(() => view.result.current.preview.showDebug())
    expect(view.result.current.preview.tab).toBe('debug')
  })
})
