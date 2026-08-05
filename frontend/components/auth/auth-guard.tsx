'use client'

import { useRouter, usePathname } from 'next/navigation'
import { useEffect } from 'react'

import { useSession } from '@/lib/auth/auth-client'
import {
  isPublicRoute,
  DEFAULT_AUTHENTICATED_ROUTE,
  DEFAULT_SIGNIN_ROUTE,
} from '@/lib/core/constants/routes'

const SSO_AUTO_ATTEMPTED_KEY = 'sso_auto_attempted'

/**
 * Auth Guard component
 * Protects routes that require authentication
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const session = useSession()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    const isPublic = isPublicRoute(pathname)

    if (session?.isPending) {
      return
    }

    if (session?.error && !session?.data && !isPublic) {
      return
    }

    if (!session?.data && !isPublic) {
      const currentPath = pathname || '/'
      const redirectUrl =
        currentPath !== '/' ? `?callbackUrl=${encodeURIComponent(currentPath)}` : ''
      router.push(`${DEFAULT_SIGNIN_ROUTE}${redirectUrl}`)
      return
    }

    if (session?.data && isPublic) {
      sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
      router.push(DEFAULT_AUTHENTICATED_ROUTE)
      return
    }

    if (session?.data) {
      sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
    }
  }, [session, pathname, router])

  if (session?.isPending) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-[var(--border)] border-t-primary" />
          <p className="text-sm text-[var(--text-secondary)]">Loading...</p>
        </div>
      </div>
    )
  }

  const isPublic = isPublicRoute(pathname)

  if (session?.error && !session?.data && !isPublic) {
    return (
      <div className="flex h-screen items-center justify-center bg-[var(--bg)] px-6">
        <div className="flex max-w-sm flex-col items-center gap-4 text-center">
          <div className="text-base font-medium text-[var(--text-primary)]">
            Session check failed
          </div>
          <p className="text-sm text-[var(--text-secondary)]">
            Please check the network connection and try again.
          </p>
          <button
            type="button"
            className="h-9 rounded-md bg-[var(--brand-600)] px-4 text-sm font-medium text-white hover:bg-[var(--brand-700)]"
            onClick={() => {
              void session.refetch()
            }}
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!session?.data && !isPublic) {
    return null
  }

  if (session?.data && isPublic) {
    return null
  }

  return <>{children}</>
}
