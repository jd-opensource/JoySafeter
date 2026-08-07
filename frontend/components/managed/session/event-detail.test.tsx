import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SessionEvent } from '@/types/managed'
import { EVENT_ID } from '@/test-utils/entity-ids'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    onClick,
  }: {
    children: React.ReactNode
    onClick?: React.MouseEventHandler<HTMLButtonElement>
  }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage
globalThis.Blob = dom.window.Blob

const writeTextMock = vi.fn()
globalThis.navigator.clipboard = {
  writeText: writeTextMock,
} as unknown as Clipboard

function event(): SessionEvent {
  return {
    id: EVENT_ID,
    type: 'assistant.message',
    created_at: '2026-01-01T00:00:00Z',
    content: 'hello',
  } as SessionEvent
}

describe('EventDetail copy feedback lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    writeTextMock.mockReset()
    writeTextMock.mockResolvedValue(undefined)
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('keeps copied feedback visible for two seconds after the latest copy', async () => {
    const eventDetailModulePath = './event-detail.tsx?copy-feedback-test'
    const { EventDetail } = await import(eventDetailModulePath)

    const { getByText, queryByText } = render(
      <EventDetail event={event()} mode="transcript" onClose={() => {}} />,
    )

    await act(async () => {
      fireEvent.click(getByText('common.copy'))
      await Promise.resolve()
    })

    expect(getByText('common.copied')).toBeTruthy()

    await act(async () => {
      vi.advanceTimersByTime(1000)
      fireEvent.click(getByText('common.copied'))
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(1500)
      await Promise.resolve()
    })

    expect(getByText('common.copied')).toBeTruthy()
    expect(queryByText('common.copy')).toBeNull()
  })
})
