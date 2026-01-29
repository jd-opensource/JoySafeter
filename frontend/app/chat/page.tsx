'use client'

import { useSearchParams } from 'next/navigation'

import ChatInterface from './ChatInterface'

/**
 * Chat Canvas Page
 */
export default function ChatPage() {
  const searchParams = useSearchParams()
  const threadId = searchParams?.get('thread') || null

  return (
    <div className="flex h-full w-full">
      <ChatInterface chatId={threadId} />
    </div>
  )
}
