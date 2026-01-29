/**
 * Zustand store for chat state management
 * Manages messages, loading states, and chat operations
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import type { Message, ChatStore } from '@/types/dynamic/chat';

/**
 * Create chat store with persistence
 */
export const useChatStore = create<ChatStore>()(
  persist(
    (set) => ({
      // State
      currentSessionId: null,
      messages: [],
      isLoading: false,
      error: null,
      isInputDisabled: false,

      // Actions
      addMessage: (message: Message) =>
        set((state) => {
          // Prevent adding duplicate messages by ID
          if (state.messages.some((m) => m.id === message.id)) {
            return {}; // Do not update state if message already exists
          }
          return { messages: [...state.messages, message] };
        }),

      updateMessage: (messageId: string, updates: Partial<Message>) =>
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === messageId ? { ...msg, ...updates } : msg
          ),
        })),

      removeMessage: (messageId: string) =>
        set((state) => ({
          messages: state.messages.filter((msg) => msg.id !== messageId),
        })),

      clearMessages: () =>
        set({
          messages: [],
        }),

      setLoading: (isLoading: boolean) =>
        set({
          isLoading,
        }),

      setError: (error: string | null) =>
        set({
          error,
        }),

      setInputDisabled: (disabled: boolean) =>
        set({
          isInputDisabled: disabled,
        }),

      setCurrentSessionId: (sessionId: string | null) =>
        set({
          currentSessionId: sessionId,
        }),

      reset: () =>
        set({
          currentSessionId: null,
          messages: [],
          isLoading: false,
          error: null,
          isInputDisabled: false,
        }),
    }),
    {
      name: 'chat-store',
      partialize: (state) => ({
        messages: state.messages,
        currentSessionId: state.currentSessionId,
      }),
    }
  )
);
