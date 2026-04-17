'use client'

import { AlertCircle, RefreshCw } from 'lucide-react'
import { useEffect } from 'react'

import { Button } from '@/components/ui/button'

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

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <AlertCircle className="h-10 w-10 text-[var(--status-error)]" />
      <h2 className="text-lg font-semibold text-[var(--text-primary)]">Something went wrong</h2>
      <p className="max-w-md text-center text-sm text-[var(--text-secondary)]">
        {error.message || 'An unexpected error occurred'}
      </p>
      <Button variant="outline" onClick={reset} className="gap-1.5">
        <RefreshCw className="h-4 w-4" />
        Try again
      </Button>
    </div>
  )
}
