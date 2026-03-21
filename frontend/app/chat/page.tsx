'use client'

import { useSearchParams } from 'next/navigation'

import { ChatProvider } from './ChatProvider'
import ChatLayout from './ChatLayout'

/**
 * Chat Page — wraps ChatLayout in ChatProvider context
 */
export default function ChatPage() {
  const searchParams = useSearchParams()
  const threadId = searchParams?.get('thread') || null

  return (
    <ChatProvider>
      <ChatLayout chatId={threadId} />
    </ChatProvider>
  )
}
