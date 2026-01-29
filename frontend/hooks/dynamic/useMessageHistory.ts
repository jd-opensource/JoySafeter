/**
 * useMessageHistory hook
 * Custom hook for managing message history
 */

import { useCallback } from 'react';

import { chatService } from '@/lib/api/dynamic/chatService';
import { useChatStore } from '@/stores/dynamic/chatStore';
import type { Message } from '@/types/dynamic/chat';

/**
 * Hook for managing message history
 */
export const useMessageHistory = (sessionId: string) => {
  const { messages, addMessage } = useChatStore();

  const loadHistory = useCallback(async () => {
    try {
      const history = await chatService.getMessages(sessionId);
      history.forEach((msg) => addMessage(msg));
      return history;
    } catch (error) {
      console.error('Failed to load message history:', error);
      return [];
    }
  }, [sessionId, addMessage]);

  const searchMessages = useCallback(
    async (query: string) => {
      try {
        return await chatService.searchMessages(sessionId, query);
      } catch (error) {
        console.error('Failed to search messages:', error);
        return [];
      }
    },
    [sessionId]
  );

  const getMessageStats = useCallback(() => {
    const totalMessages = messages.length;
    const userMessages = messages.filter((m) => m.role === 'user').length;
    const assistantMessages = messages.filter((m) => m.role === 'assistant').length;
    const messagesWithTools = messages.filter((m) => m.toolInvocations?.length).length;

    return {
      totalMessages,
      userMessages,
      assistantMessages,
      messagesWithTools,
      averageLength:
        totalMessages > 0
          ? Math.round(
              messages.reduce((sum, m) => sum + m.content.length, 0) / totalMessages
            )
          : 0,
    };
  }, [messages]);

  const getMessagesByTimeRange = useCallback(
    (startTime: number, endTime: number) => {
      return messages.filter(
        (m) => m.timestamp >= startTime && m.timestamp <= endTime
      );
    },
    [messages]
  );

  const exportHistoryAsJSON = useCallback(() => {
    return JSON.stringify(messages, null, 2);
  }, [messages]);

  return {
    messages,
    loadHistory,
    searchMessages,
    getMessageStats,
    getMessagesByTimeRange,
    exportHistoryAsJSON,
  };
};
