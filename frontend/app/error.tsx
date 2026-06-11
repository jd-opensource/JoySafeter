'use client'

import { useEffect } from 'react'

import { AppErrorState } from '@/components/shared/app-error-state'

/**
 * Page-level error boundary — catches errors in any page component under the root layout.
 * The root layout (providers, shell, toaster) stays intact while this replaces the page content.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('Page error:', error)
  }, [error])

  return <AppErrorState onRetry={reset} />
}
