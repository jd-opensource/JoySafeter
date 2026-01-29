/**
 * useChat hook
 * Custom hook for chat message management
 */

import { useCallback } from 'react';

import { chatService } from '@/lib/api/dynamic/chatService';
import { sessionService } from '@/lib/api/dynamic/sessionService';
import { useChatStore } from '@/stores/dynamic/chatStore';
import type { Message } from '@/types/dynamic/chat';

/**
 * Hook for managing chat messages
 */
export const useChat = (sessionId: string) => {
  const {
    messages,
    isLoading,
    error,
    isInputDisabled,
    addMessage,
    updateMessage,
    clearMessages,
    setLoading,
    setError,
    setInputDisabled,
  } = useChatStore();

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim()) return;

      // Add user message
      const userMessage: Message = {
        id: `msg_${Date.now()}`,
        sessionId,
        role: 'user',
        content,
        timestamp: Date.now(),
      };

      addMessage(userMessage);
      setInputDisabled(true);
      setLoading(true);

      try {
        // Create placeholder for assistant message
        const assistantMessage: Message = {
          id: `msg_${Date.now()}_response`,
          sessionId,
          role: 'assistant',
          content: '',
          timestamp: Date.now(),
          isStreaming: true,
        };

        addMessage(assistantMessage);

        // Stream response
        let fullContent = '';
        let intermediateContent = '';
        let taskId: string | undefined;

        for await (const event of chatService.sendMessage(
          sessionId,
          content,
          'user'
        )) {
          if (event.type === 'task_created') {
            // Task created - update user message with taskId
            taskId = event.data as string;
            updateMessage(userMessage.id, {
              taskId: taskId,
            });
          } else if (event.type === 'message_chunk') {
            // Final reply chunk
            fullContent += event.data;
            updateMessage(assistantMessage.id, {
              content: intermediateContent + fullContent,
            });
          } else if (event.type === 'intermediate') {
            // Intermediate message (tool execution, thinking, etc.)
            intermediateContent += event.data + '\n\n';
            updateMessage(assistantMessage.id, {
              content: intermediateContent + fullContent,
            });
          } else if (event.type === 'complete') {
            break;
          } else if (event.type === 'error') {
            throw new Error(JSON.stringify(event.data));
          }
        }

        // Mark as complete
        updateMessage(assistantMessage.id, {
          isStreaming: false,
        });

        // Save session to localStorage
        sessionService.saveSessionToLocal('user', {
          id: sessionId,
          userId: 'user',
          title: content.slice(0, 50),
          createdAt: Date.now(),
          updatedAt: Date.now(),
          messageCount: messages.length + 2,
        });
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to send message';
        setError(errorMessage);
      } finally {
        setLoading(false);
        setInputDisabled(false);
      }
    },
    [sessionId, messages, addMessage, updateMessage, setLoading, setError, setInputDisabled]
  );

  const handleClearMessages = useCallback(() => {
    clearMessages();
  }, [clearMessages]);

  const handleRetry = useCallback(
    async (messageId: string) => {
      const message = messages.find((m) => m.id === messageId);
      if (message && message.role === 'user') {
        await sendMessage(message.content);
      }
    },
    [messages, sendMessage]
  );

  return {
    messages,
    isLoading,
    error,
    isInputDisabled,
    sendMessage,
    clearMessages: handleClearMessages,
    retry: handleRetry,
  };
};
