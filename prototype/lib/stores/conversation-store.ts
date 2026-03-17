import { create } from 'zustand'

interface Conversation {
  id: number
  thread_id: string
  title: string
  updated_at: string
  message_count: number
}

interface ConversationState {
  conversations: Conversation[]
  currentThreadId: string | null
  setCurrentThreadId: (threadId: string | null) => void
  setConversations: (conversations: Conversation[]) => void
  addConversation: (conversation: Conversation) => void
  updateConversation: (threadId: string, updates: Partial<Conversation>) => void
  deleteConversation: (threadId: string) => void
}

export const useConversationStore = create<ConversationState>()((set) => ({
  conversations: [],
  currentThreadId: null,
  setCurrentThreadId: (threadId) => set({ currentThreadId: threadId }),
  setConversations: (conversations) => set({ conversations }),
  addConversation: (conversation) =>
    set((state) => ({
      conversations: [conversation, ...state.conversations],
    })),
  updateConversation: (threadId, updates) =>
    set((state) => ({
      conversations: state.conversations.map((conv) =>
        conv.thread_id === threadId ? { ...conv, ...updates } : conv
      ),
    })),
  deleteConversation: (threadId) =>
    set((state) => ({
      conversations: state.conversations.filter((conv) => conv.thread_id !== threadId),
    })),
}))
