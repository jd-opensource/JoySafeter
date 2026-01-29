/**
 * SessionItem component tests
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { describe, expect, it, vi } from 'vitest'

import { SessionItem } from '../SessionItem'

describe('SessionItem', () => {
  const mockSession = {
    id: 'session-1',
    title: 'Test Session',
    userId: 'user-1',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messageCount: 5,
  }

  it('renders session title', () => {
    render(
      <SessionItem
        session={mockSession}
        isActive={false}
        onSelect={vi.fn()}
      />
    )
    // Title appears in both .session-item-title and .session-item-tooltip
    expect(screen.getAllByText('Test Session').length).toBeGreaterThan(0)
  })

  it('shows active state', () => {
    const { container } = render(
      <SessionItem
        session={mockSession}
        isActive={true}
        onSelect={vi.fn()}
      />
    );
    const item = container.querySelector('[class*="active"]');
    expect(item).toBeInTheDocument();
  });

  it('calls onSelect when clicked', async () => {
    const user = userEvent.setup()
    const mockOnSelect = vi.fn()
    render(
      <SessionItem
        session={mockSession}
        isActive={false}
        onSelect={mockOnSelect}
      />
    )
    // SessionItem uses a div with onClick, not a button
    const item = screen.getByTitle('Test Session')
    await user.click(item)
    expect(mockOnSelect).toHaveBeenCalled()
  })

  it('displays message count', () => {
    render(
      <SessionItem
        session={mockSession}
        isActive={false}
        onSelect={vi.fn()}
      />
    );
    expect(screen.getByText(/5/)).toBeInTheDocument();
  });
});
