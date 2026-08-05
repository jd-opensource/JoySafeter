'use client'

import { AppErrorState } from '@/components/shared/app-error-state'

/**
 * Global error boundary — catches errors in the root layout itself.
 * Must include <html> and <body> since the root layout unmounts on error.
 */
export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="en">
      <body>
        <AppErrorState onRetry={reset} />
      </body>
    </html>
  )
}
