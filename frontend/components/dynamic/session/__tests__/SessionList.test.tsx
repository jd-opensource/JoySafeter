/**
 * SessionList component tests
 */

import { render, screen } from '@testing-library/react'
import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SessionList } from '../SessionList'

import { useSessionStore } from '../../../../stores/dynamic/sessionStore'

vi.mock('../../../../stores/dynamic/sessionStore', () => ({
  useSessionStore: vi.fn(),
}))

describe('SessionList', () => {
  const mockSessions = [
    { id: 'session-1', title: 'Session 1', userId: 'user-1', createdAt: Date.now(), updatedAt: Date.now(), messageCount: 5 },
    { id: 'session-2', title: 'Session 2', userId: 'user-1', createdAt: Date.now(), updatedAt: Date.now(), messageCount: 3 },
  ]

  beforeEach(() => {
    vi.mocked(useSessionStore).mockReturnValue({
      sessions: mockSessions,
      currentSession: mockSessions[0],
      searchQuery: '',
      loadSessions: vi.fn(),
      switchSession: vi.fn(),
    })
  })

  it('renders session list', () => {
    render(<SessionList userId="user-1" />)
    // SessionItem shows title in .session-item-title and .session-item-tooltip
    expect(screen.getAllByText('Session 1').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Session 2').length).toBeGreaterThan(0)
  })

  it('loads sessions on mount', () => {
    const mockLoadSessions = vi.fn()
    vi.mocked(useSessionStore).mockReturnValue({
      sessions: mockSessions,
      currentSession: mockSessions[0],
      searchQuery: '',
      loadSessions: mockLoadSessions,
      switchSession: vi.fn(),
    });

    render(<SessionList userId="user-1" />);
    expect(mockLoadSessions).toHaveBeenCalledWith('user-1');
  });

  it('shows empty state when no sessions', () => {
    vi.mocked(useSessionStore).mockReturnValue({
      sessions: [],
      currentSession: null,
      searchQuery: '',
      loadSessions: vi.fn(),
      switchSession: vi.fn(),
    });

    render(<SessionList userId="user-1" />);
    expect(screen.getByText('No sessions yet')).toBeInTheDocument();
  });

  it('filters sessions by search query', () => {
    vi.mocked(useSessionStore).mockReturnValue({
      sessions: mockSessions,
      currentSession: mockSessions[0],
      searchQuery: 'Session 1',
      loadSessions: vi.fn(),
      switchSession: vi.fn(),
    });

    render(<SessionList userId="user-1" />)
    expect(screen.getAllByText('Session 1').length).toBeGreaterThan(0)
    expect(screen.queryByText('Session 2')).not.toBeInTheDocument()
  })
})
