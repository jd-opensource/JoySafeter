'use client'

import { ArrowLeft, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'

import { ExecutionTimeline } from '@/components/executions/execution-timeline'
import { Button } from '@/components/ui/button'
import { useExecution } from '@/hooks/queries/executions'
import { useWorkspaces } from '@/hooks/queries/workspaces'

export default function ExecutionDetailPage() {
  const { executionId } = useParams<{ executionId: string }>()
  const { data: workspaces = [] } = useWorkspaces()
  const workspaceId = workspaces[0]?.id ?? ''

  const { data: execution, isLoading } = useExecution(executionId ?? '', workspaceId, {
    enabled: Boolean(executionId) && Boolean(workspaceId),
  })

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <Link href="/executions">
          <Button variant="ghost" size="icon" aria-label="Back to executions">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">
            {execution?.title ?? `Execution ${executionId?.slice(0, 8) ?? ''}`}
          </h1>
          {execution?.mission_id && (
            <p className="text-xs text-[var(--text-muted)]">
              Mission {execution.mission_id.slice(0, 8)}
            </p>
          )}
        </div>
        {isLoading && <Loader2 className="h-4 w-4 animate-spin text-[var(--text-muted)]" />}
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-hidden">
        {executionId && workspaceId ? (
          <ExecutionTimeline executionId={executionId} workspaceId={workspaceId} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-[var(--text-muted)]" />
          </div>
        )}
      </div>
    </div>
  )
}
