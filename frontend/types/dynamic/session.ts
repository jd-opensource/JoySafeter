/**
 * Session-related TypeScript type definitions
 * Defines interfaces for conversation sessions and session management
 */

import { Mode } from './mode';

/**
 * Represents a conversation session
 */
export interface Session {
  /** Unique session identifier */
  id: string;
  /** User ID who owns this session */
  userId: string;
  /** Session title/name */
  title: string;
  /** Session creation timestamp */
  createdAt: number;
  /** Last updated timestamp */
  updatedAt: number;
  /** Number of messages in this session */
  messageCount: number;
  /** Preview of last message */
  lastMessage?: string;
  /** Whether this session is currently active */
  isActive?: boolean;
  /** Mode for this session (ctf) */
  mode?: Mode;
}

/**
 * Session state managed by Zustand store
 */
export interface SessionState {
  /** List of all sessions */
  sessions: Session[];
  /** Currently active session */
  currentSession: Session | null;
  /** Search query for filtering sessions */
  searchQuery: string;
  /** Whether currently loading sessions */
  isLoading: boolean;
  /** Current error message if any */
  error: string | null;
}

/**
 * Session store actions
 */
export interface SessionActions {
  /** Create a new session */
  createSession: (title: string, userId: string, mode?: Mode) => Promise<Session>;
  /** Delete a session */
  deleteSession: (sessionId: string) => Promise<void>;
  /** Switch to a different session */
  switchSession: (sessionId: string) => void;
  /** Update session title */
  updateSessionTitle: (sessionId: string, title: string) => Promise<void>;
  /** Load all sessions for a user */
  loadSessions: (userId: string) => Promise<void>;
  /** Search sessions by title or content */
  searchSessions: (query: string) => void;
  /** Set loading state */
  setLoading: (isLoading: boolean) => void;
  /** Set error message */
  setError: (error: string | null) => void;
  /** Clear all sessions */
  clearSessions: () => void;
  /** Reset session state */
  reset: () => void;
}

/**
 * Complete session store type
 */
export type SessionStore = SessionState & SessionActions;

/**
 * Session creation request
 */
export interface CreateSessionRequest {
  /** User ID */
  userId: string;
  /** Session title */
  title: string;
  /** Optional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Session update request
 */
export interface UpdateSessionRequest {
  /** Session ID */
  sessionId: string;
  /** New title */
  title?: string;
  /** Updated metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Session list response
 */
export interface SessionListResponse {
  /** List of sessions */
  sessions: Session[];
  /** Total count */
  total: number;
  /** Pagination info */
  pagination?: {
    page: number;
    pageSize: number;
    totalPages: number;
  };
}
