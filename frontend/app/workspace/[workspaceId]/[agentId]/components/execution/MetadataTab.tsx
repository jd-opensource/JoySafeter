'use client'

import React, { useMemo } from 'react'

import { useExecutionData } from './contexts/ExecutionDataContext'
import { useExecutionSelection } from './contexts/ExecutionSelectionContext'
import { EmptyState } from './ExecutionDetailPanel'
import { JsonView } from './JsonView'

export const MetadataTab = React.memo(function MetadataTab() {
  const { nodeMap } = useExecutionData()
  const { selectedNodeId } = useExecutionSelection()

  const node = selectedNodeId ? nodeMap.get(selectedNodeId) : null
  const step = node?.step

  const metadata = useMemo(() => {
    if (!step) return null
    const meta: Record<string, any> = {
      id: step.id,
      nodeId: step.nodeId,
      nodeLabel: step.nodeLabel,
      stepType: step.stepType,
      status: step.status,
      startTime: new Date(step.startTime).toISOString(),
      endTime: step.endTime ? new Date(step.endTime).toISOString() : null,
      duration: step.duration ? `${step.duration}ms` : null,
    }
    // trace / observation info
    if (step.traceId) meta.traceId = step.traceId
    if (step.observationId) meta.observationId = step.observationId
    if (step.parentObservationId) meta.parentObservationId = step.parentObservationId
    // token usage
    if (step.promptTokens) meta.promptTokens = step.promptTokens
    if (step.completionTokens) meta.completionTokens = step.completionTokens
    if (step.totalTokens) meta.totalTokens = step.totalTokens
    return meta
  }, [step])

  if (!step || !metadata) return <EmptyState message="Select a step to view metadata" />

  return (
    <div className="p-4">
      <div className="space-y-2">
        {Object.entries(metadata).map(([key, value]) => (
          <div
            key={key}
            className="flex items-start gap-3 border-b border-[var(--border-muted)] py-1.5 last:border-b-0"
          >
            <span className="w-24 shrink-0 pt-0.5 text-2xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
              {key}
            </span>
            <span className="break-all font-mono text-app-xs text-[var(--text-secondary)]">
              {value === null ? <span className="italic text-[var(--text-subtle)]">null</span> : String(value)}
            </span>
          </div>
        ))}
      </div>

      {/* Raw data section */}
      {step.data && (
        <div className="mt-4">
          <div className="mb-2 text-2xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
            Raw Data
          </div>
          <JsonView data={step.data} />
        </div>
      )}
    </div>
  )
})
