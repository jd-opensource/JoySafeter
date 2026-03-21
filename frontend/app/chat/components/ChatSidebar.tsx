'use client'

import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { MessageSquare, Plus, ChevronLeft, ChevronRight } from 'lucide-react'
import React, { useState, useMemo, useCallback } from 'react'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { toastSuccess, toastError } from '@/lib/utils/toast'
import { conversationService, type Conversation } from '@/services/conversationService'
import ConversationGroup from './ConversationGroup'

// Conversation type imported from conversationService

interface ChatSidebarProps {
  isCollapsed: boolean
  onToggle: () => void
  onSelectConversation: (threadId: string) => void
  currentThreadId: string | null
  onNewChat?: () => void
}

export default function ChatSidebar({
  isCollapsed,
  onToggle,
  onSelectConversation,
  currentThreadId,
  onNewChat,
}: ChatSidebarProps) {
  const { t } = useTranslation()
  const { data: conversationsData, isLoading } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => conversationService.listConversations({ page: 1, pageSize: 100 }),
  })

  const conversations = conversationsData || []

  const { todayConvs, monthConvs, olderConvs } = useMemo(() => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const thisMonth = new Date(now.getFullYear(), now.getMonth(), 1)

    const todayConvs: Conversation[] = []
    const monthConvs: Conversation[] = []
    const olderConvs: Conversation[] = []

    conversations.forEach((conv) => {
      const updatedAt = new Date(conv.updated_at)
      if (updatedAt >= today) {
        todayConvs.push(conv)
      } else if (updatedAt >= thisMonth) {
        monthConvs.push(conv)
      } else {
        olderConvs.push(conv)
      }
    })

    return { todayConvs, monthConvs, olderConvs }
  }, [conversations])

  const queryClient = useQueryClient()
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [conversationToDelete, setConversationToDelete] = useState<{
    threadId: string
    title: string
  } | null>(null)

  // Expand states: today expanded by default, others collapsed
  const [isTodayExpanded, setIsTodayExpanded] = useState(true)
  const [isThisMonthExpanded, setIsThisMonthExpanded] = useState(false)
  const [isOlderExpanded, setIsOlderExpanded] = useState(false)

  const deleteConversationMutation = useMutation({
    mutationFn: (threadId: string) => conversationService.deleteConversation(threadId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
      toastSuccess(t('chat.deleteSuccess'))
      setDeleteConfirmOpen(false)
      setConversationToDelete(null)
    },
    onError: (error) => {
      console.error('Failed to delete conversation:', error)
      toastError(t('chat.deleteFailed'))
      setDeleteConfirmOpen(false)
      setConversationToDelete(null)
    },
  })

  const handleDeleteConversation = (e: React.MouseEvent, threadId: string, title: string) => {
    e.stopPropagation()
    setConversationToDelete({ threadId, title })
    setDeleteConfirmOpen(true)
  }

  const handleConfirmDelete = () => {
    if (conversationToDelete) {
      deleteConversationMutation.mutate(conversationToDelete.threadId)
    }
  }

  const handleCancelDelete = () => {
    setDeleteConfirmOpen(false)
    setConversationToDelete(null)
  }

  const monthNames = useMemo(() => [
    t('chat.jan'), t('chat.feb'), t('chat.mar'), t('chat.apr'),
    t('chat.may'), t('chat.jun'), t('chat.jul'), t('chat.aug'),
    t('chat.sep'), t('chat.oct'), t('chat.nov'), t('chat.dec'),
  ], [t])

  const formatTime = useCallback((dateString: string) => {
    try {
      const date = new Date(dateString)
      const now = new Date()
      const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / 60000)

      if (diffInMinutes < 1) return t('chat.now')
      if (diffInMinutes < 60) return t('chat.minutesAgo', { m: diffInMinutes })
      if (diffInMinutes < 1440) return t('chat.hoursAgo', { h: Math.floor(diffInMinutes / 60) })
      return `${monthNames[date.getMonth()]} ${date.getDate()}`
    } catch {
      return ''
    }
  }, [t, monthNames])

  return (
    <div className="flex h-full flex-col bg-gray-50/50">
      {/* Header */}
      <div
        className={cn(
          'border-b border-gray-100 bg-white p-3 transition-all',
          isCollapsed ? 'px-2' : 'px-4',
        )}
      >
        <div className={cn('flex items-center', isCollapsed ? 'justify-center' : 'justify-start')}>
          {!isCollapsed && (
            <h2 className="text-sm font-semibold text-gray-800">{t('chat.history')}</h2>
          )}
        </div>
      </div>

      {/* Conversations List */}
      <div
        className={cn(
          'flex-1 overflow-y-auto transition-all',
          isCollapsed ? 'px-1.5 py-2' : 'px-2 py-2',
        )}
      >
        {isLoading ? (
          <div className="space-y-2 px-2 py-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-2 rounded-md px-2 py-1.5">
                <div className="h-4 w-4 flex-shrink-0 rounded bg-gray-200 animate-pulse" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-3 w-3/4 rounded bg-gray-200 animate-pulse" />
                  <div className="h-2.5 w-1/2 rounded bg-gray-100 animate-pulse" />
                </div>
              </div>
            ))}
          </div>
        ) : conversations.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-6">
            <div className="rounded-full bg-gray-100 p-2">
              <MessageSquare size={16} className="text-gray-400" />
            </div>
            <span className="text-xs text-gray-400">{t('chat.noConversations')}</span>
          </div>
        ) : (
          <>
            <ConversationGroup
              label={t('chat.today')}
              conversations={todayConvs}
              isExpanded={isTodayExpanded}
              onToggleExpand={() => setIsTodayExpanded(!isTodayExpanded)}
              isCollapsed={isCollapsed}
              currentThreadId={currentThreadId}
              onSelectConversation={onSelectConversation}
              onDeleteClick={handleDeleteConversation}
              formatTime={formatTime}
              deleteConfirmOpen={deleteConfirmOpen}
              conversationToDelete={conversationToDelete}
              onDeleteConfirmChange={setDeleteConfirmOpen}
              onConfirmDelete={handleConfirmDelete}
              onCancelDelete={handleCancelDelete}
            />
            <ConversationGroup
              label={t('chat.thisMonth')}
              conversations={monthConvs}
              isExpanded={isThisMonthExpanded}
              onToggleExpand={() => setIsThisMonthExpanded(!isThisMonthExpanded)}
              isCollapsed={isCollapsed}
              currentThreadId={currentThreadId}
              onSelectConversation={onSelectConversation}
              onDeleteClick={handleDeleteConversation}
              formatTime={formatTime}
              deleteConfirmOpen={deleteConfirmOpen}
              conversationToDelete={conversationToDelete}
              onDeleteConfirmChange={setDeleteConfirmOpen}
              onConfirmDelete={handleConfirmDelete}
              onCancelDelete={handleCancelDelete}
            />
            <ConversationGroup
              label={t('chat.older')}
              conversations={olderConvs}
              isExpanded={isOlderExpanded}
              onToggleExpand={() => setIsOlderExpanded(!isOlderExpanded)}
              isCollapsed={isCollapsed}
              currentThreadId={currentThreadId}
              onSelectConversation={onSelectConversation}
              onDeleteClick={handleDeleteConversation}
              formatTime={formatTime}
              maxItems={10}
              deleteConfirmOpen={deleteConfirmOpen}
              conversationToDelete={conversationToDelete}
              onDeleteConfirmChange={setDeleteConfirmOpen}
              onConfirmDelete={handleConfirmDelete}
              onCancelDelete={handleCancelDelete}
            />
          </>
        )}
      </div>

      {/* Collapse Button */}
      <div className="flex-shrink-0 border-t border-gray-100 p-2">
        <button
          onClick={onToggle}
          className={cn(
            'flex w-full items-center justify-center rounded-lg py-1.5 text-gray-600 transition-colors hover:bg-gray-100',
            isCollapsed ? 'px-0' : 'gap-2 px-2',
          )}
          title={isCollapsed ? t('chat.expand') : t('chat.collapse')}
        >
          {isCollapsed ? (
            <ChevronRight size={14} />
          ) : (
            <>
              <ChevronLeft size={14} />
              <span className="text-xs text-gray-500">{t('chat.collapse')}</span>
            </>
          )}
        </button>
      </div>
    </div>
  )
}
