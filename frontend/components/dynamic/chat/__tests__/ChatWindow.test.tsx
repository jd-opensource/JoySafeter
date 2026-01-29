/**
 * ChatWindow component tests
 * ChatWindow renders MessageList and MessageInput only (no header/ExportMenu in current impl)
 */

import { render, screen } from '@testing-library/react'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ChatWindow } from '../ChatWindow'

import { useChatStore } from '../../../../stores/dynamic'

vi.mock('../../../../stores/dynamic')
vi.mock('../MessageList', () => ({
  MessageList: () => <div>MessageList</div>,
}))
vi.mock('../MessageInput', () => ({
  MessageInput: () => <div>MessageInput</div>,
}))

describe('ChatWindow', () => {
  beforeEach(() => {
    vi.mocked(useChatStore).mockReturnValue({
      messages: [],
      isLoading: false,
      error: null,
    })
  })

  it('renders chat window', () => {
    render(<ChatWindow sessionId="session-1" />)
    expect(screen.getByText('MessageList')).toBeInTheDocument()
    expect(screen.getByText('MessageInput')).toBeInTheDocument()
  })

  it('renders with messages', () => {
    const mockMessages = [
      {
        id: 'msg-1',
        content: 'Hello',
        role: 'user' as const,
        timestamp: Date.now(),
        sessionId: 'session-1',
      },
    ]

    vi.mocked(useChatStore).mockReturnValue({
      messages: mockMessages,
      isLoading: false,
      error: null,
    })

    render(<ChatWindow sessionId="session-1" />)
    expect(screen.getByText('MessageList')).toBeInTheDocument()
  })
})
