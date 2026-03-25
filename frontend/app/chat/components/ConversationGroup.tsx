'use client'

import { MessageSquare, Trash2, ChevronDown, ChevronRight } from 'lucide-react'
import React from 'react'

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
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import type { Conversation } from '@/services/conversationService'

interface ConversationItemProps {
  conv: Conversation
  isActive: boolean
  isCollapsed: boolean
  onSelect: (threadId: string) => void
  onDeleteClick: (e: React.MouseEvent, threadId: string, title: string) => void
  formatTime: (dateString: string) => string
  deleteConfirmOpen: boolean
  conversationToDelete: { threadId: string; title: string } | null
  onDeleteConfirmChange: (open: boolean) => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
}

function ConversationItem({
  conv,
  isActive,
  isCollapsed,
  onSelect,
  onDeleteClick,
  formatTime,
  deleteConfirmOpen,
  conversationToDelete,
  onDeleteConfirmChange,
  onConfirmDelete,
  onCancelDelete,
}: ConversationItemProps) {
  const { t } = useTranslation()

  return (
    <div
      className={cn(
        'group relative flex w-full items-center rounded-md transition-colors duration-150',
        isCollapsed ? 'justify-center px-1.5 py-1.5' : 'gap-2 px-2 py-1.5',
        isActive
          ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm ring-1 ring-primary/10'
          : 'text-[var(--text-secondary)] hover:bg-[var(--surface-2)]',
      )}
    >
      <button
        onClick={() => onSelect(conv.thread_id)}
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
            isActive ? 'text-primary' : 'text-[var(--text-muted)]',
          )}
        />
        {!isCollapsed && (
          <>
            <div className="min-w-0 flex-1 truncate text-xs">
              {conv.title || t('chat.newChat')}
            </div>
            <div className="flex-shrink-0 text-[10px] text-[var(--text-muted)]">
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
          onOpenChange={onDeleteConfirmChange}
        >
          <AlertDialogTrigger asChild>
            <button
              onClick={(e) =>
                onDeleteClick(
                  e,
                  conv.thread_id,
                  conv.title || t('chat.newChat'),
                )
              }
              className="flex-shrink-0 rounded p-1 opacity-0 transition-all hover:bg-red-100 group-hover:opacity-100"
              title={t('chat.delete')}
            >
              <Trash2 size={12} className="text-[var(--text-muted)] hover:text-red-600" />
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
              <AlertDialogCancel onClick={onCancelDelete}>
                {t('chat.cancel')}
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={onConfirmDelete}
                className="bg-[#ef4444] text-white hover:bg-[#dc2626]"
              >
                {t('chat.delete')}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  )
}

interface ConversationGroupProps {
  label: string
  conversations: Conversation[]
  isExpanded: boolean
  onToggleExpand: () => void
  isCollapsed: boolean
  currentThreadId: string | null
  onSelectConversation: (threadId: string) => void
  onDeleteClick: (e: React.MouseEvent, threadId: string, title: string) => void
  formatTime: (dateString: string) => string
  maxItems?: number
  deleteConfirmOpen: boolean
  conversationToDelete: { threadId: string; title: string } | null
  onDeleteConfirmChange: (open: boolean) => void
  onConfirmDelete: () => void
  onCancelDelete: () => void
}

export default function ConversationGroup({
  label,
  conversations,
  isExpanded,
  onToggleExpand,
  isCollapsed,
  currentThreadId,
  onSelectConversation,
  onDeleteClick,
  formatTime,
  maxItems,
  deleteConfirmOpen,
  conversationToDelete,
  onDeleteConfirmChange,
  onConfirmDelete,
  onCancelDelete,
}: ConversationGroupProps) {
  if (conversations.length === 0) return null

  const displayConversations = maxItems ? conversations.slice(0, maxItems) : conversations

  return (
    <div className="mb-2">
      {!isCollapsed && (
        <button
          onClick={onToggleExpand}
          className="mb-1.5 flex w-full items-center justify-between px-1.5 text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)] transition-colors hover:text-[var(--text-secondary)]"
        >
          <span>{label}</span>
          {isExpanded ? (
            <ChevronDown size={14} className="text-[var(--text-muted)]" />
          ) : (
            <ChevronRight size={14} className="text-[var(--text-muted)]" />
          )}
        </button>
      )}
      {(isExpanded || isCollapsed) && (
        <div className="space-y-0.5">
          {displayConversations.map((conv) => (
            <ConversationItem
              key={conv.thread_id}
              conv={conv}
              isActive={currentThreadId === conv.thread_id}
              isCollapsed={isCollapsed}
              onSelect={onSelectConversation}
              onDeleteClick={onDeleteClick}
              formatTime={formatTime}
              deleteConfirmOpen={deleteConfirmOpen}
              conversationToDelete={conversationToDelete}
              onDeleteConfirmChange={onDeleteConfirmChange}
              onConfirmDelete={onConfirmDelete}
              onCancelDelete={onCancelDelete}
            />
          ))}
        </div>
      )}
    </div>
  )
}
