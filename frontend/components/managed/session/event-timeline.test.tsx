import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EventTimeline } from './event-timeline'

describe('EventTimeline', () => {
  it('keeps the hover tooltip inside reserved layout space', () => {
    const events = [
      {
        id: 'evt_019f4619e72a00000000000000000000',
        type: 'user.message',
        created_at: '2026-07-15T10:00:00.000Z',
      },
      {
        id: 'evt_019f4619e72b00000000000000000000',
        type: 'agent.message',
        created_at: '2026-07-15T10:00:05.000Z',
      },
    ]

    const { container } = render(
      <EventTimeline
        events={events}
        sessionStart="2026-07-15T10:00:00.000Z"
      />,
    )

    const track = container.querySelector('.cursor-pointer')
    expect(track).toBeInstanceOf(HTMLElement)

    fireEvent.mouseMove(track as HTMLElement, { clientX: 0 })

    const tooltip = screen.getByText('user.message')
    expect(tooltip.className).not.toContain('-top-')
  })
})
