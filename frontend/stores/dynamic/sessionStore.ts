/**
 * Zustand store for session state management
 * Manages conversation sessions and session operations
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import type { Mode } from '@/types/dynamic/mode';
import type { Session, SessionStore } from '@/types/dynamic/session';

/**
 * Create session store with persistence
 */
export const useSessionStore = create<SessionStore>()(
  persist(
    (set) => ({
      // State
      sessions: [],
      currentSession: null,
      searchQuery: '',
      isLoading: false,
      error: null,

      // Actions
      createSession: async (title: string, userId: string, mode?: Mode): Promise<Session> => {
        // Prefer backend-created session id by triggering sessionService.createSession.
        // If backend call fails, fall back to a local session.
        let newSession: Session | null = null;

        try {
          const { sessionService } = await import('@/lib/api/dynamic/sessionService');
          const created = await sessionService.createSession(userId, title);
          newSession = {
            ...created,
            // Ensure mode is persisted if passed in
            mode: mode ?? created.mode,
          };
        } catch (e) {
          console.warn('[sessionStore] Failed to create session via backend, falling back to local session:', e);
        }

        if (!newSession) {
          newSession = {
            id: `session_${Date.now()}`,
            userId,
            title,
            createdAt: Date.now(),
            updatedAt: Date.now(),
            messageCount: 0,
            mode, // Include mode in session
          };
        }

        set((state) => ({
          sessions: [newSession!, ...state.sessions],
          currentSession: newSession!,
        }));

        return newSession!;
      },

      deleteSession: async (sessionId: string) => {
        set((state) => ({
          sessions: state.sessions.filter((s) => s.id !== sessionId),
          currentSession:
            state.currentSession?.id === sessionId ? null : state.currentSession,
        }));
      },

      switchSession: (sessionId: string) =>
        set((state) => ({
          currentSession:
            state.sessions.find((s) => s.id === sessionId) || null,
        })),

      updateSessionTitle: async (sessionId: string, title: string) => {
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId
              ? { ...s, title, updatedAt: Date.now() }
              : s
          ),
          currentSession:
            state.currentSession?.id === sessionId
              ? { ...state.currentSession, title, updatedAt: Date.now() }
              : state.currentSession,
        }));
      },

      loadSessions: async (userId: string) => {
        if (!userId) {
          return; // Do not load sessions if userId is not available yet
        }
        set({ isLoading: true });
        try {
          // Import sessionService dynamically to avoid circular dependency
          const { sessionService } = await import('@/lib/api/dynamic/sessionService');
          const sessions = await sessionService.getSessions(userId);

          // Clear currentSession if it doesn't belong to this user or doesn't exist
          set((state) => {
            const currentSessionValid = state.currentSession &&
              sessions.some(s => s.id === state.currentSession?.id);

            return {
              sessions,
              currentSession: currentSessionValid ? state.currentSession : null,
              isLoading: false,
            };
          });
        } catch (error) {
          console.error('Failed to load sessions:', error);
          set({
            error: 'Failed to load sessions',
            isLoading: false,
            currentSession: null, // Clear invalid session on error
          });
        }
      },

      searchSessions: (query: string) =>
        set({
          searchQuery: query,
        }),

      setLoading: (isLoading: boolean) =>
        set({
          isLoading,
        }),

      setError: (error: string | null) =>
        set({
          error,
        }),

      clearSessions: () =>
        set({
          sessions: [],
          currentSession: null,
        }),

      reset: () =>
        set({
          sessions: [],
          currentSession: null,
          searchQuery: '',
          isLoading: false,
          error: null,
        }),
    }),
    {
      name: 'session-store',
      partialize: (state) => ({
        sessions: state.sessions,
        currentSession: state.currentSession,
      }),
    }
  )
);
