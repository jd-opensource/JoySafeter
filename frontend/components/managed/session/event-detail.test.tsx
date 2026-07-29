import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { EventDetail } from './event-detail'

describe('EventDetail', () => {
  it('renders structured session error details in transcript mode', () => {
    const { container } = render(
      <EventDetail
        mode="transcript"
        onClose={vi.fn()}
        event={{
          id: 'evt_error',
          type: 'session.error',
          created_at: '2026-07-20T10:00:00.000Z',
          error: {
            type: 'model_service_error',
            message: 'API Error: 400 模型服务调用失败',
            status_code: 400,
            upstream_body: '{"error":{"message":"invalid model: claude-4"}}',
            retry_status: { type: 'terminal' },
          },
        }}
      />,
    )

    expect(screen.getByText(/API Error: 400 模型服务调用失败/)).toBeInTheDocument()
    expect(container.textContent).toContain('status: 400')
    expect(screen.getByText(/invalid model: claude-4/)).toBeInTheDocument()
  })
})
