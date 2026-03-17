'use client'

import { Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect } from 'react'

function ChatRedirect() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const threadId = searchParams?.get('thread')

  useEffect(() => {
    const dest = threadId ? `/copilot?thread=${threadId}` : '/copilot'
    router.replace(dest)
  }, [threadId, router])

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--bg)]">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--border)] border-t-[var(--brand-500)]" />
    </div>
  )
}

/**
 * /chat → /copilot (with thread param preserved)
 */
export default function ChatPage() {
  return (
    <Suspense fallback={
      <div className="flex h-screen items-center justify-center bg-[var(--bg)]">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--border)] border-t-[var(--brand-500)]" />
      </div>
    }>
      <ChatRedirect />
    </Suspense>
  )
}
