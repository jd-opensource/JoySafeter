/**
 * Chat API service
 * Handles all chat-related API calls and streaming
 */

import axios from 'axios';

import type { Message } from '@/types/dynamic/chat';
import type { Mode } from '@/types/dynamic/mode';
import { modeToMetadata } from '@/types/dynamic/mode';
import type { StreamingEvent } from '@/types/dynamic/tool';

import { getApiBaseUrl } from './apiConfig';

// Next.js uses process.env.NEXT_PUBLIC_* for client-side environment variables
const API_BASE_URL = getApiBaseUrl();


/**
 * Detect mode from user message using keyword + LLM detection
 */
export interface DetectModeResponse {
  mode: 'ctf';
  confidence: 'high' | 'low';
}

/**
 * Chat service for API communication
 */
export const chatService = {
  /**
   * Detect mode from user message
   */
  async detectMode(message: string): Promise<DetectModeResponse> {
    try {
      const response = await axios.post<DetectModeResponse>(
        `${API_BASE_URL}/api/chat/detect-mode`,
        { message },
        {
          headers: {
            'Content-Type': 'application/json',
          },
        }
      );
      return response.data;
    } catch (error) {
      console.error('Failed to detect mode:', error);
      // Fallback to ctf on error
      return { mode: 'ctf', confidence: 'low' };
    }
  },

  /**
   * Send a message and get streaming response
   */
  sendMessage: async function* (
    sessionId: string,
    message: string,
    userId: string,
    mode?: Mode | null
  ): AsyncGenerator<StreamingEvent> {
    try {


      // Build metadata from mode
      const metadata = mode ? modeToMetadata(mode) : undefined;

      // Use real backend API with streaming via fetch
      const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message,
          session_id: sessionId,
          user_id: userId,
          metadata, // Include mode metadata
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      // Parse Server-Sent Events (SSE)
      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Response body is not readable');
      }

      const decoder = new TextDecoder();
      let buffer = '';
      let lastDataTime = Date.now();
      const STREAM_TIMEOUT = 120000; // 2分钟超时
      let timeoutId: NodeJS.Timeout | null = null;

      // 设置超时检查
      const resetTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          reader.cancel('Stream timeout').catch(() => {});
        }, STREAM_TIMEOUT);
      };

      resetTimeout();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // 收到数据，重置超时
        lastDataTime = Date.now();
        resetTimeout();

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const jsonStr = line.slice(6);
              const data = JSON.parse(jsonStr);

              // Map server event types to client event types
              if (data.type === 'chunk') {
                yield {
                  type: 'message_chunk',
                  data: data.data,
                  timestamp: Date.now(),
                };
              } else if (data.type === 'intermediate') {
                yield {
                  type: 'intermediate',
                  data: data.data,
                  timestamp: Date.now(),
                };
              } else if (data.type === 'task_created') {
                yield {
                  type: 'task_created',
                  data: data.task_id,
                  timestamp: Date.now(),
                };
              } else if (data.type === 'complete') {
                yield {
                  type: 'complete',
                  data: data,
                  timestamp: Date.now(),
                };
                // 收到 complete 事件，主动结束循环
                break;
              } else if (data.type === 'error') {
                yield {
                  type: 'error',
                  data: data.message,
                  timestamp: Date.now(),
                };
                break;
              }
            } catch (e) {
              console.error('Failed to parse SSE data:', line, e);
            }
          }
        }
      }

      // 清理超时定时器
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    } catch (error) {
      yield {
        type: 'error',
        data: {
          error: error instanceof Error ? error.message : 'Unknown error',
        },
        timestamp: Date.now(),
      };
    }
  },

  /**
   * Get conversation history for a specific session
   */
  async getMessages(
    sessionId: string,
    userId?: string,
    limit: number = 50,
    offset: number = 0
  ): Promise<Message[]> {
    if (!sessionId || sessionId === 'undefined') {
      console.warn('getMessages called with an invalid sessionId, returning empty array.');
      return [];
    }
    try {


      // Get userId from store if not provided
      const { useUserStore } = await import('@/stores/dynamic/userStore');
      const currentUserId = userId || useUserStore.getState().userId;

      if (!currentUserId) {
        console.warn('No userId available for fetching messages');
        return [];
      }

      // Use real backend API with userId and sessionId
      const response = await axios.get(
        `${API_BASE_URL}/api/web/users/${currentUserId}/sessions/${sessionId}/history`,
        {
          params: {
            limit,
            offset,
          },
        }
      );

      const { messages } = response.data;

      // Map backend response to frontend Message format
      return (messages || []).map((msg: any) => ({
        id: msg.id,
        sessionId: msg.session_id,
        role: msg.role,
        content: msg.content,
        timestamp: msg.timestamp,
        taskId: msg.task_id, // Map snake_case to camelCase
      }));
    } catch (error) {
      console.error('Failed to fetch messages:', error);
      // Re-throw error so caller can handle it (e.g., clear invalid session)
      throw error;
    }
  },



  /**
   * Clear conversation history
   */
  async clearMessages(sessionId: string): Promise<boolean> {
    try {
      // Mock implementation
      return true;
    } catch (error) {
      console.error('Failed to clear messages:', error);
      return false;
    }
  },

  /**
   * Search messages in a session
   */
  async searchMessages(
    sessionId: string,
    query: string
  ): Promise<Message[]> {
    try {
      const messages = await this.getMessages(sessionId);
      return messages.filter((msg) =>
        msg.content.toLowerCase().includes(query.toLowerCase())
      );
    } catch (error) {
      console.error('Failed to search messages:', error);
      return [];
    }
  },
};
