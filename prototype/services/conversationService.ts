'use client'

/**
 * Conversation Service
 *
 * Encapsulates conversation-related API calls, including:
 * - Get conversation list
 * - Get conversation history messages
 * - Delete conversation
 */

import { API_ENDPOINTS, apiGet, apiDelete } from '@/lib/api-client'

// ==================== Types ====================

export interface Conversation {
  id: string
  thread_id: string
  title: string
  updated_at: string
  message_count: number
}

export interface ConversationMessage {
  id: string
  role: string
  content: string
  metadata: Record<string, any>
  created_at: string
}

export interface PaginatedConversationsResponse {
  items: Array<{
    id: string
    thread_id: string
    user_id: string
    title: string
    metadata: Record<string, any>
    created_at: string
    updated_at: string
    message_count: number
  }>
  total: number
  page: number
  page_size: number
  pages: number
}

export interface PaginatedMessagesResponse {
  items: ConversationMessage[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ==================== Service ====================

export const conversationService = {
  /**
   * Get conversation list
   */
  async listConversations(params?: {
    graphId?: string
    page?: number
    pageSize?: number
  }): Promise<Conversation[]> {
    const { graphId, page = 1, pageSize = 100 } = params || {}

    let url = `${API_ENDPOINTS.conversations}?page=${page}&page_size=${pageSize}`
    if (graphId) {
      url += `&graph_id=${graphId}`
    }

    try {
      const response = await apiGet<PaginatedConversationsResponse>(url)

      return (response?.items || []).map((item) => ({
        id: item.id,
        thread_id: item.thread_id,
        title: item.title,
        updated_at: item.updated_at,
        message_count: item.message_count,
      }))
    } catch (error) {
      console.error('Failed to load conversations:', error)
      return []
    }
  },

  /**
   * Get conversation history messages
   */
  async getConversationHistory(
    threadId: string,
    params?: {
      page?: number
      pageSize?: number
    }
  ): Promise<ConversationMessage[]> {
    const { page = 1, pageSize = 100 } = params || {}

    const response = await apiGet<PaginatedMessagesResponse>(
      `${API_ENDPOINTS.conversations}/${threadId}/messages?page=${page}&page_size=${pageSize}`
    )

    return response?.items || []
  },

  /**
   * Delete conversation
   */
  async deleteConversation(threadId: string): Promise<void> {
    await apiDelete(`${API_ENDPOINTS.conversations}/${threadId}`)
  },
}
