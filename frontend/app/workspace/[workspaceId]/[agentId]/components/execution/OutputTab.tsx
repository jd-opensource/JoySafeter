'use client'

import React from 'react'

import { useExecutionData } from './contexts/ExecutionDataContext'
import { useExecutionSelection } from './contexts/ExecutionSelectionContext'
import { useExecutionViewPreferences } from './contexts/ExecutionViewPreferencesContext'
import { EmptyState } from './ExecutionDetailPanel'
import { JsonView, FormattedView } from './JsonView'

export const OutputTab = React.memo(function OutputTab() {
  const { nodeMap } = useExecutionData()
  const { selectedNodeId } = useExecutionSelection()
  const { jsonViewMode } = useExecutionViewPreferences()

  const node = selectedNodeId ? nodeMap.get(selectedNodeId) : null
  const step = node?.step

  if (!step) return <EmptyState message="Select a step to view output" />

  const ViewComponent = jsonViewMode === 'json' ? JsonView : FormattedView

  switch (step.stepType) {
    case 'tool_execution':
      return (
        <div className="space-y-3 p-4">
          {step.data?.response ? (
            <ViewComponent data={step.data.response} label="Tool Output" />
          ) : step.status === 'running' ? (
            <div className="flex items-center gap-2 text-[var(--brand-secondary)]">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--brand-secondary)]" />
              <span className="font-mono text-xs">Executing...</span>
            </div>
          ) : (
            <EmptyState message="No output available" />
          )}
        </div>
      )

    case 'model_io':
      return (
        <div className="space-y-3 p-4">
          {(step.data as Record<string, unknown>)?.output ? (
            <ViewComponent data={(step.data as Record<string, unknown>).output} label="Model Output" />
          ) : step.data?.response ? (
            <ViewComponent data={step.data.response} label="Model Output" />
          ) : (
            <EmptyState message="No output available" />
          )}
        </div>
      )

    case 'agent_thought':
    case 'code_agent_thought':
      return (
        <div className="p-4">
          <FormattedView data={step.content} label="Thought Output" />
        </div>
      )

    case 'node_lifecycle':
      return (
        <div className="space-y-3 p-4">
          {(step.data as Record<string, unknown>)?.output ? (
            <ViewComponent data={(step.data as Record<string, unknown>).output} label="Node Output" />
          ) : step.endTime ? (
            <div className="space-y-2">
              <FormattedView
                data={{
                  status: step.status,
                  duration: step.duration ? `${step.duration}ms` : undefined,
                  endTime: new Date(step.endTime).toISOString(),
                }}
                label="Completion Info"
              />
            </div>
          ) : (
            <EmptyState message="No output yet" />
          )}
        </div>
      )

    default:
      return (
        <div className="p-4">
          {step.content ? (
            <FormattedView data={step.content} label="Output" />
          ) : (
            <EmptyState message="No output available" />
          )}
        </div>
      )
  }
})
