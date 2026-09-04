import { describe, expect, it, vi } from 'vitest'

import { SESSION_ID } from '@/test-utils/entity-ids'
import { parseSessionId } from '@/types/entity-id'

import { collectManagedCursorPages, parseManagedCursorPage } from './cursor-page'

describe('managed cursor page contract', () => {
  it('parses the canonical cursor page envelope', () => {
    expect(
      parseManagedCursorPage(
        {
          data: [{ id: SESSION_ID, label: 'Session' }],
          has_more: true,
          first_id: SESSION_ID,
          last_id: SESSION_ID,
        },
        {
          parseItem: (item) => item as { id: string; label: string },
          parseCursor: parseSessionId,
        },
      ),
    ).toEqual({
      items: [{ id: SESSION_ID, label: 'Session' }],
      hasMore: true,
      firstId: SESSION_ID,
      lastId: SESSION_ID,
    })
  })

  it.each([
    [{ data: [], has_more: 'false' }],
    [[{ id: SESSION_ID }]],
    [{ data: [], has_more: false, first_id: 123 }],
    [{ data: [], has_more: true, last_id: SESSION_ID }],
    [{ data: [{ id: SESSION_ID }], has_more: true }],
  ])('rejects non-canonical cursor page response %#', (response) => {
    expect(() =>
      parseManagedCursorPage(response, {
        parseItem: (item) => item,
        parseCursor: parseSessionId,
      }),
    ).toThrow(/managed cursor page response/)
  })

  it('collects every page through the canonical last cursor', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({
        items: ['first'],
        hasMore: true,
        lastId: SESSION_ID,
      })
      .mockResolvedValueOnce({
        items: ['second'],
        hasMore: false,
      })

    await expect(collectManagedCursorPages({ fetchPage })).resolves.toEqual(['first', 'second'])
    expect(fetchPage).toHaveBeenNthCalledWith(1, undefined)
    expect(fetchPage).toHaveBeenNthCalledWith(2, SESSION_ID)
  })

  it.each([
    { items: [], hasMore: true },
    { items: ['again'], hasMore: true, lastId: SESSION_ID },
  ])('rejects missing or repeated pagination cursors', async (terminalPage) => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce({ items: ['first'], hasMore: true, lastId: SESSION_ID })
      .mockResolvedValueOnce(terminalPage)

    await expect(
      collectManagedCursorPages({ fetchPage, responseName: 'Test pagination' }),
    ).rejects.toThrow(/Test pagination returned an invalid cursor/)
  })
})
