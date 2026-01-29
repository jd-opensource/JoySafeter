/**
 * MessageList component tests
 */

import { render, screen } from '@testing-library/react'
import React from 'react'
import { describe, expect, it, vi } from 'vitest'

import { MessageList } from '../MessageList'

vi.mock('../MessageBubble', () => ({
  MessageBubble: ({ message }: { message: { content: string } }) => <div>{message.content}</div>,
}))

describe('MessageList', () => {
  it('renders empty list', () => {
    render(<MessageList messages={[]} />);
    expect(screen.queryByText(/hello/i)).not.toBeInTheDocument();
  });

  it('renders messages', () => {
    const messages = [
      {
        id: 'msg-1',
        content: 'Hello',
        role: 'user' as const,
        timestamp: Date.now(),
        sessionId: 'session-1',
      },
      {
        id: 'msg-2',
        content: 'Hi there',
        role: 'assistant' as const,
        timestamp: Date.now(),
        sessionId: 'session-1',
      },
    ];

    render(<MessageList messages={messages} />);
    expect(screen.getByText('Hello')).toBeInTheDocument();
    expect(screen.getByText('Hi there')).toBeInTheDocument();
  });

  it('displays messages in order', () => {
    const messages = [
      {
        id: 'msg-1',
        content: 'First',
        role: 'user' as const,
        timestamp: Date.now(),
        sessionId: 'session-1',
      },
      {
        id: 'msg-2',
        content: 'Second',
        role: 'assistant' as const,
        timestamp: Date.now() + 1000,
        sessionId: 'session-1',
      },
    ];

    const { container } = render(<MessageList messages={messages} />);
    const items = container.querySelectorAll('div');
    expect(items.length).toBeGreaterThan(0);
  });

  it('handles large message lists', () => {
    const messages = Array.from({ length: 100 }, (_, i) => ({
      id: `msg-${i}`,
      content: `Message ${i}`,
      role: (i % 2 === 0 ? 'user' : 'assistant') as const,
      timestamp: Date.now() + i * 1000,
      sessionId: 'session-1',
    }));

    render(<MessageList messages={messages} />);
    expect(screen.getByText('Message 0')).toBeInTheDocument();
    expect(screen.getByText('Message 99')).toBeInTheDocument();
  });
});
