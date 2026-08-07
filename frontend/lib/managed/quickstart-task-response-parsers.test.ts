import { describe, expect, it } from 'vitest'

import { parseQuickstartTaskPage } from './quickstart-task-response-parsers'

const TASK_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f001'

function task(id: string) {
  return {
    id,
    status: 'running',
    created_at: '2026-08-07T00:00:00Z',
    started_at: null,
    completed_at: null,
    error: null,
  }
}

describe('quickstart task response parser', () => {
  it('accepts canonical task IDs and validates every page item', () => {
    const response = parseQuickstartTaskPage({
      data: [task(`task_${TASK_UUID}`), task(`task_${TASK_UUID.replace(/1$/, '2')}`)],
      has_more: false,
    })

    expect(response.data.map(({ id }) => id)).toEqual([
      `task_${TASK_UUID}`,
      `task_${TASK_UUID.replace(/1$/, '2')}`,
    ])
    expect(response.has_more).toBe(false)
  })

  it.each([TASK_UUID, `agent_${TASK_UUID}`])('rejects noncanonical task ID %s', (id) => {
    expect(() => parseQuickstartTaskPage({ data: [task(id)] })).toThrow(TypeError)
  })

  it('rejects a noncanonical ID anywhere in the task page', () => {
    expect(() =>
      parseQuickstartTaskPage({ data: [task(`task_${TASK_UUID}`), task(`agent_${TASK_UUID}`)] }),
    ).toThrow(TypeError)
  })

  it.each([null, {}, { data: null }, { data: {}, has_more: false }, { data: [], has_more: 'no' }])(
    'rejects invalid task page envelope %#',
    (response) => {
      expect(() => parseQuickstartTaskPage(response)).toThrow(TypeError)
    },
  )
})
