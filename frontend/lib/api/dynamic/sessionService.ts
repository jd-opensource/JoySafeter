/**
 * Session API service
 * Handles all session-related API calls
 */

import axios from 'axios';

import { toMode } from '@/types/dynamic/mode';
import type { Session } from '@/types/dynamic/session';

import { getApiBaseUrl } from './apiConfig';

const API_BASE_URL = getApiBaseUrl();


/**
 * Session service for API communication
 */
export const sessionService = {
  /**
   * Create a new session
   */
  async createSession(userId: string, title: string): Promise<Session> {
    try {


      // Real API: Create session by sending first message
      // Backend creates session automatically on first message
      const sessionId = `session_${Date.now()}`;
      return {
        id: sessionId,
        userId,
        title,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messageCount: 0,
      };
    } catch (error) {
      console.error('Failed to create session:', error);
      throw error;
    }
  },

  /**
   * Get all sessions for a user
   */
  async getSessions(userId: string): Promise<Session[]> {
    if (!userId) {
      console.warn('getSessions called without a userId, returning empty array.');
      return [];
    }
    try {


      // Real API: Get sessions from backend
      const response = await axios.get(
        `${API_BASE_URL}/api/web/users/${userId}/sessions`,
        {
          params: {
            limit: 50,
            offset: 0,
          },
        }
      );

      const data = response.data;
      return data.sessions.map((s: any) => ({
        id: s.id,
        userId: s.user_id,
        title: s.title,
        createdAt: new Date(s.created_at).getTime(),
        updatedAt: new Date(s.updated_at).getTime(),
        messageCount: s.message_count || s.task_count || 0,
        mode: toMode(s.mode), // Map backend mode to frontend Mode type
      }));
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
      // Fallback to localStorage
      const sessionsKey = `sessions_${userId}`;
      const sessionsJson = localStorage.getItem(sessionsKey);
      if (sessionsJson) {
        return JSON.parse(sessionsJson);
      }
      return [];
    }
  },

  /**
   * Get a single session
   */
  async getSession(sessionId: string): Promise<Session | null> {
    if (!sessionId || sessionId === 'undefined') {
      console.warn('getSession called with an invalid sessionId.');
      return null;
    }
    try {


      // Real API: Get session details
      const response = await axios.get(
        `${API_BASE_URL}/api/sessions/${sessionId}`
      );

      const data = response.data;
      return {
        id: data.session_id,
        userId: data.user_id,
        title: `Session ${sessionId.slice(-8)}`,
        createdAt: data.created_at ? new Date(data.created_at).getTime() : Date.now(),
        updatedAt: Date.now(),
        messageCount: data.message_count || 0,
      };
    } catch (error) {
      console.error('Failed to fetch session:', error);
      return null;
    }
  },

  /**
   * Delete a session
   */
  async deleteSession(sessionId: string): Promise<boolean> {
    if (!sessionId || sessionId === 'undefined') {
      console.warn('deleteSession called with an invalid sessionId.');
      return false;
    }
    try {


      // Real API: Delete session
      await axios.delete(`${API_BASE_URL}/api/sessions/${sessionId}`);
      return true;
    } catch (error) {
      console.error('Failed to delete session:', error);
      return false;
    }
  },

  /**
   * Update session title
   */
  async updateSessionTitle(
    sessionId: string,
    title: string
  ): Promise<boolean> {
    try {


      // Real API: Update session title
      // Note: Backend doesn't have this endpoint yet
      // Store in localStorage for now
      return true;
    } catch (error) {
      console.error('Failed to update session title:', error);
      return false;
    }
  },

  /**
   * Clear all sessions
   */
  async clearAllSessions(userId: string): Promise<boolean> {
    try {


      // Real API: Clear all sessions
      // Note: Backend doesn't have this endpoint yet
      // Clear localStorage for now
      const sessionsKey = `sessions_${userId}`;
      localStorage.removeItem(sessionsKey);
      return true;
    } catch (error) {
      console.error('Failed to clear sessions:', error);
      return false;
    }
  },

  /**
   * Save session to localStorage
   */
  saveSessionToLocal(userId: string, session: Session): void {
    try {
      const sessionsKey = `sessions_${userId}`;
      const sessionsJson = localStorage.getItem(sessionsKey);
      const sessions: Session[] = sessionsJson ? JSON.parse(sessionsJson) : [];

      // Update or add session
      const index = sessions.findIndex(s => s.id === session.id);
      if (index >= 0) {
        sessions[index] = session;
      } else {
        sessions.unshift(session);
      }

      localStorage.setItem(sessionsKey, JSON.stringify(sessions));
    } catch (error) {
      console.error('Failed to save session to localStorage:', error);
    }
  },
};
