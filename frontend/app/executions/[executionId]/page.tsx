'use client'

import { useParams } from 'next/navigation'

export default function ExecutionDetailPage() {
  const { executionId } = useParams<{ executionId: string }>()

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center border-b border-[var(--border)] px-6 py-4">
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">
          Execution {executionId?.slice(0, 8)}
        </h1>
      </div>
      <div className="flex-1 p-6">
        <p className="text-[var(--text-secondary)]">Execution detail coming soon...</p>
      </div>
    </div>
  )
}
