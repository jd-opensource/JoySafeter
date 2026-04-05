'use client'

import { useRouter, usePathname } from 'next/navigation'
import { useEffect } from 'react'

import { useSession } from '@/lib/auth/auth-client'
import {
  isPublicRoute,
  DEFAULT_AUTHENTICATED_ROUTE,
  DEFAULT_SIGNIN_ROUTE,
} from '@/lib/core/constants/routes'

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

    if (!session?.data && !isPublic) {
      const currentPath = pathname || '/'
      const redirectUrl =
        currentPath !== '/' ? `?callbackUrl=${encodeURIComponent(currentPath)}` : ''
      router.push(`${DEFAULT_SIGNIN_ROUTE}${redirectUrl}`)
      return
    }

    if (session?.data && isPublic) {
      router.push(DEFAULT_AUTHENTICATED_ROUTE)
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

  if (!session?.data && !isPublic) {
    return null
  }

  if (session?.data && isPublic) {
    return null
  }

  return <>{children}</>
}
