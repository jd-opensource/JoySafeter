import { describe, expect, it } from 'vitest'

import { dataTableSelectionKey } from './data-table'

describe('dataTableSelectionKey', () => {
  it('uses stable row ids so pagination does not select same-index rows', () => {
    const selected = new Set([dataTableSelectionKey({ id: 'sess_page_1' }, 0)])

    expect(selected.has(dataTableSelectionKey({ id: 'sess_page_1' }, 0))).toBe(true)
    expect(selected.has(dataTableSelectionKey({ id: 'sess_page_2' }, 0))).toBe(false)
  })

  it('falls back to row index when no stable id exists', () => {
    expect(dataTableSelectionKey({ name: 'row' }, 3)).toBe(3)
  })
})
