'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

import ChatInterface from '@/app/chat/ChatInterface'

function CopilotContent() {
  const searchParams = useSearchParams()
  const threadId = searchParams?.get('thread') || null

  return (
    <div className="flex h-full w-full">
      <ChatInterface chatId={threadId} />
    </div>
  )
}

export default function CopilotPage() {
  return (
    <Suspense fallback={
      <div className="flex h-full items-center justify-center bg-[var(--bg)]">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--border)] border-t-[var(--brand-500)]" />
      </div>
    }>
      <CopilotContent />
    </Suspense>
  )
}
