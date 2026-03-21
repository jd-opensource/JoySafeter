'use client'

import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { MessageSquare, Plus, ChevronLeft, ChevronRight, ChevronDown, Trash2 } from 'lucide-react'
import React, { useState } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { toastSuccess, toastError } from '@/lib/utils/toast'
import { conversationService, type Conversation } from '@/services/conversationService'

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

  const groupConversations = (convs: Conversation[]) => {
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const thisMonth = new Date(now.getFullYear(), now.getMonth(), 1)

    const todayConvs: Conversation[] = []
    const monthConvs: Conversation[] = []
    const olderConvs: Conversation[] = []

    convs.forEach((conv) => {
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
  }

  const { todayConvs, monthConvs, olderConvs } = groupConversations(conversations)

  const queryClient = useQueryClient()
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [conversationToDelete, setConversationToDelete] = useState<{
    threadId: string
    title: string
  } | null>(null)

  // Collapse states: today expanded by default, others collapsed
  const [isTodayCollapsed, setIsTodayCollapsed] = useState(false)
  const [isThisMonthCollapsed, setIsThisMonthCollapsed] = useState(true)
  const [isOlderCollapsed, setIsOlderCollapsed] = useState(true)

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

  const formatTime = (dateString: string) => {
    try {
      const date = new Date(dateString)
      const now = new Date()
      const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / 60000)

      if (diffInMinutes < 1) return t('chat.now')
      if (diffInMinutes < 60) return t('chat.minutesAgo', { m: diffInMinutes })
      if (diffInMinutes < 1440) return t('chat.hoursAgo', { h: Math.floor(diffInMinutes / 60) })
      const monthNames = [
        t('chat.jan'),
        t('chat.feb'),
        t('chat.mar'),
        t('chat.apr'),
        t('chat.may'),
        t('chat.jun'),
        t('chat.jul'),
        t('chat.aug'),
        t('chat.sep'),
        t('chat.oct'),
        t('chat.nov'),
        t('chat.dec'),
      ]
      return `${monthNames[date.getMonth()]} ${date.getDate()}`
    } catch {
      return ''
    }
  }

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
            {/* Today */}
            {todayConvs.length > 0 && (
              <div className="mb-2">
                {!isCollapsed && (
                  <button
                    onClick={() => setIsTodayCollapsed(!isTodayCollapsed)}
                    className="mb-1.5 flex w-full items-center justify-between px-1.5 text-[10px] font-medium uppercase tracking-wider text-gray-400 transition-colors hover:text-gray-700"
                  >
                    <span>{t('chat.today')}</span>
                    {isTodayCollapsed ? (
                      <ChevronRight size={14} className="text-gray-400" />
                    ) : (
                      <ChevronDown size={14} className="text-gray-400" />
                    )}
                  </button>
                )}
                {!isTodayCollapsed && (
                  <div className="space-y-0.5">
                    {todayConvs.map((conv) => (
                      <div
                        key={conv.thread_id}
                        className={cn(
                          'group relative flex w-full items-center rounded-md transition-colors duration-150',
                          isCollapsed ? 'justify-center px-1.5 py-1.5' : 'gap-2 px-2 py-1.5',
                          currentThreadId === conv.thread_id
                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-blue-50'
                            : 'text-gray-600 hover:bg-white/60',
                        )}
                      >
                        <button
                          onClick={() => {
                            onSelectConversation(conv.thread_id)
                          }}
                          className={cn(
                            'flex min-w-0 flex-1 items-center text-left',
                            isCollapsed ? 'justify-center' : 'gap-2',
                          )}
                          title={conv.title || t('chat.newChat')}
                        >
                          <MessageSquare
                            size={14}
                            className={cn(
                              'flex-shrink-0',
                              currentThreadId === conv.thread_id
                                ? 'text-blue-500'
                                : 'text-gray-400',
                            )}
                          />
                          {!isCollapsed && (
                            <>
                              <div className="min-w-0 flex-1 truncate text-xs">
                                {conv.title || t('chat.newChat')}
                              </div>
                              <div className="flex-shrink-0 text-[10px] text-gray-400">
                                {formatTime(conv.updated_at)}
                              </div>
                            </>
                          )}
                        </button>
                        {!isCollapsed && (
                          <AlertDialog
                            open={
                              deleteConfirmOpen && conversationToDelete?.threadId === conv.thread_id
                            }
                            onOpenChange={setDeleteConfirmOpen}
                          >
                            <AlertDialogTrigger asChild>
                              <button
                                onClick={(e) =>
                                  handleDeleteConversation(
                                    e,
                                    conv.thread_id,
                                    conv.title || t('chat.newChat'),
                                  )
                                }
                                className="flex-shrink-0 rounded p-1 opacity-0 transition-all hover:bg-red-100 group-hover:opacity-100"
                                title={t('chat.delete')}
                              >
                                <Trash2 size={12} className="text-gray-400 hover:text-red-600" />
                              </button>
                            </AlertDialogTrigger>
                            <AlertDialogContent variant="destructive">
                              <AlertDialogHeader>
                                <AlertDialogTitle>{t('chat.deleteConfirmTitle')}</AlertDialogTitle>
                                <AlertDialogDescription>
                                  {t('chat.deleteConfirmMessage')}{' '}
                                  <span className="font-semibold text-[#ef4444]">
                                    {conv.title || t('chat.newChat')}
                                  </span>
                                  {'?'}
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel
                                  onClick={() => {
                                    setDeleteConfirmOpen(false)
                                    setConversationToDelete(null)
                                  }}
                                >
                                  {t('chat.cancel')}
                                </AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={handleConfirmDelete}
                                  className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
                                >
                                  {t('chat.delete')}
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* This Month */}
            {monthConvs.length > 0 && (
              <div className="mb-2">
                {!isCollapsed && (
                  <button
                    onClick={() => setIsThisMonthCollapsed(!isThisMonthCollapsed)}
                    className="mb-1.5 flex w-full items-center justify-between px-1.5 text-[10px] font-medium uppercase tracking-wider text-gray-400 transition-colors hover:text-gray-700"
                  >
                    <span>{t('chat.thisMonth')}</span>
                    {isThisMonthCollapsed ? (
                      <ChevronRight size={14} className="text-gray-400" />
                    ) : (
                      <ChevronDown size={14} className="text-gray-400" />
                    )}
                  </button>
                )}
                {!isThisMonthCollapsed && (
                  <div className="space-y-0.5">
                    {monthConvs.map((conv) => (
                      <div
                        key={conv.thread_id}
                        className={cn(
                          'group relative flex w-full items-center rounded-md transition-colors duration-150',
                          isCollapsed ? 'justify-center px-1.5 py-1.5' : 'gap-2 px-2 py-1.5',
                          currentThreadId === conv.thread_id
                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-blue-50'
                            : 'text-gray-600 hover:bg-white/60',
                        )}
                      >
                        <button
                          onClick={() => onSelectConversation(conv.thread_id)}
                          className={cn(
                            'flex min-w-0 flex-1 items-center text-left',
                            isCollapsed ? 'justify-center' : 'gap-2',
                          )}
                          title={conv.title || t('chat.newChat')}
                        >
                          <MessageSquare
                            size={14}
                            className={cn(
                              'flex-shrink-0',
                              currentThreadId === conv.thread_id
                                ? 'text-blue-500'
                                : 'text-gray-400',
                            )}
                          />
                          {!isCollapsed && (
                            <>
                              <div className="min-w-0 flex-1 truncate text-xs">
                                {conv.title || t('chat.newChat')}
                              </div>
                              <div className="flex-shrink-0 text-[10px] text-gray-400">
                                {formatTime(conv.updated_at)}
                              </div>
                            </>
                          )}
                        </button>
                        {!isCollapsed && (
                          <AlertDialog
                            open={
                              deleteConfirmOpen && conversationToDelete?.threadId === conv.thread_id
                            }
                            onOpenChange={setDeleteConfirmOpen}
                          >
                            <AlertDialogTrigger asChild>
                              <button
                                onClick={(e) =>
                                  handleDeleteConversation(
                                    e,
                                    conv.thread_id,
                                    conv.title || t('chat.newChat'),
                                  )
                                }
                                className="flex-shrink-0 rounded p-1 opacity-0 transition-all hover:bg-red-100 group-hover:opacity-100"
                                title={t('chat.delete')}
                              >
                                <Trash2 size={12} className="text-gray-400 hover:text-red-600" />
                              </button>
                            </AlertDialogTrigger>
                            <AlertDialogContent variant="destructive">
                              <AlertDialogHeader>
                                <AlertDialogTitle>{t('chat.deleteConfirmTitle')}</AlertDialogTitle>
                                <AlertDialogDescription>
                                  {t('chat.deleteConfirmMessage')}{' '}
                                  <span className="font-semibold text-[#ef4444]">
                                    {conv.title || t('chat.newChat')}
                                  </span>
                                  {'?'}
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel
                                  onClick={() => {
                                    setDeleteConfirmOpen(false)
                                    setConversationToDelete(null)
                                  }}
                                >
                                  {t('chat.cancel')}
                                </AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={handleConfirmDelete}
                                  className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
                                >
                                  {t('chat.delete')}
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Older */}
            {olderConvs.length > 0 && (
              <div>
                {!isCollapsed && (
                  <button
                    onClick={() => setIsOlderCollapsed(!isOlderCollapsed)}
                    className="mb-1.5 flex w-full items-center justify-between px-1.5 text-[10px] font-medium uppercase tracking-wider text-gray-400 transition-colors hover:text-gray-700"
                  >
                    <span>{t('chat.older')}</span>
                    {isOlderCollapsed ? (
                      <ChevronRight size={14} className="text-gray-400" />
                    ) : (
                      <ChevronDown size={14} className="text-gray-400" />
                    )}
                  </button>
                )}
                {!isOlderCollapsed && (
                  <div className="space-y-0.5">
                    {olderConvs.slice(0, 10).map((conv) => (
                      <div
                        key={conv.thread_id}
                        className={cn(
                          'group relative flex w-full items-center rounded-md transition-colors duration-150',
                          isCollapsed ? 'justify-center px-1.5 py-1.5' : 'gap-2 px-2 py-1.5',
                          currentThreadId === conv.thread_id
                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-blue-50'
                            : 'text-gray-600 hover:bg-white/60',
                        )}
                      >
                        <button
                          onClick={() => onSelectConversation(conv.thread_id)}
                          className={cn(
                            'flex min-w-0 flex-1 items-center text-left',
                            isCollapsed ? 'justify-center' : 'gap-2',
                          )}
                          title={conv.title || t('chat.newChat')}
                        >
                          <MessageSquare
                            size={14}
                            className={cn(
                              'flex-shrink-0',
                              currentThreadId === conv.thread_id
                                ? 'text-blue-500'
                                : 'text-gray-400',
                            )}
                          />
                          {!isCollapsed && (
                            <>
                              <div className="min-w-0 flex-1 truncate text-xs">
                                {conv.title || t('chat.newChat')}
                              </div>
                              <div className="flex-shrink-0 text-[10px] text-gray-400">
                                {formatTime(conv.updated_at)}
                              </div>
                            </>
                          )}
                        </button>
                        {!isCollapsed && (
                          <AlertDialog
                            open={
                              deleteConfirmOpen && conversationToDelete?.threadId === conv.thread_id
                            }
                            onOpenChange={setDeleteConfirmOpen}
                          >
                            <AlertDialogTrigger asChild>
                              <button
                                onClick={(e) =>
                                  handleDeleteConversation(
                                    e,
                                    conv.thread_id,
                                    conv.title || t('chat.newChat'),
                                  )
                                }
                                className="flex-shrink-0 rounded p-1 opacity-0 transition-all hover:bg-red-100 group-hover:opacity-100"
                                title={t('chat.delete')}
                              >
                                <Trash2 size={12} className="text-gray-400 hover:text-red-600" />
                              </button>
                            </AlertDialogTrigger>
                            <AlertDialogContent variant="destructive">
                              <AlertDialogHeader>
                                <AlertDialogTitle>{t('chat.deleteConfirmTitle')}</AlertDialogTitle>
                                <AlertDialogDescription>
                                  {t('chat.deleteConfirmMessage')}{' '}
                                  <span className="font-semibold text-[#ef4444]">
                                    {conv.title || t('chat.newChat')}
                                  </span>
                                  {'?'}
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel
                                  onClick={() => {
                                    setDeleteConfirmOpen(false)
                                    setConversationToDelete(null)
                                  }}
                                >
                                  {t('chat.cancel')}
                                </AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={handleConfirmDelete}
                                  className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
                                >
                                  {t('chat.delete')}
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
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
