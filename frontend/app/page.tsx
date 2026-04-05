'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useSession } from '@/lib/auth/auth-client'

/**
 * Root page - redirects based on auth status
 * Logged in -> /chat
 * Not logged in -> /signin
 */
export default function Page() {
  const router = useRouter()
  const session = useSession()

  useEffect(() => {
    if (!session.isPending) {
      if (session.data?.user) {
        router.replace('/chat')
      } else {
        router.replace('/signin')
      }
    }
  }, [session.isPending, session.data?.user, router])

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--bg)]">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--border)] border-t-[var(--brand-500)]" />
    </div>
  )
}
