/**
 * useSessions hook
 * Custom hook for session management
 */

import { useCallback } from 'react';

import { sessionService } from '@/lib/api/dynamic/sessionService';
import { useSessionStore } from '@/stores/dynamic/sessionStore';

/**
 * Hook for managing conversation sessions
 */
export const useSessions = (userId: string) => {
  const {
    sessions,
    currentSession,
    searchQuery,
    isLoading,
    error,
    createSession,
    deleteSession,
    switchSession,
    updateSessionTitle,
    loadSessions,
    searchSessions,
    setError,
  } = useSessionStore();

  const handleCreateSession = useCallback(
    async (title?: string) => {
      try {
        const sessionTitle = title || `Conversation ${new Date().toLocaleDateString()}`;
        await createSession(sessionTitle, userId);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to create session');
      }
    },
    [userId, createSession, setError]
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      try {
        const success = await sessionService.deleteSession(sessionId);
        if (success) {
          await deleteSession(sessionId);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete session');
      }
    },
    [deleteSession, setError]
  );

  const handleUpdateTitle = useCallback(
    async (sessionId: string, title: string) => {
      try {
        const success = await sessionService.updateSessionTitle(sessionId, title);
        if (success) {
          await updateSessionTitle(sessionId, title);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update session');
      }
    },
    [updateSessionTitle, setError]
  );

  const handleSwitchSession = useCallback(
    (sessionId: string) => {
      switchSession(sessionId);
    },
    [switchSession]
  );

  const handleSearch = useCallback(
    (query: string) => {
      searchSessions(query);
    },
    [searchSessions]
  );

  return {
    sessions,
    currentSession,
    searchQuery,
    isLoading,
    error,
    createSession: handleCreateSession,
    deleteSession: handleDeleteSession,
    switchSession: handleSwitchSession,
    updateSessionTitle: handleUpdateTitle,
    searchSessions: handleSearch,
    loadSessions,
  };
};
