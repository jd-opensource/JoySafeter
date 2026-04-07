'use client'

import React from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/utils'

import { ModelIOCard } from '../ModelIOCard'
import { ThoughtContent } from '../ThoughtContent'
import { ToolCallCard } from '../ToolCallCard'

import { useExecutionData } from './contexts/ExecutionDataContext'
import { useExecutionSelection } from './contexts/ExecutionSelectionContext'
import { useExecutionViewPreferences } from './contexts/ExecutionViewPreferencesContext'
import { EmptyState } from './ExecutionDetailPanel'
import { JsonView, FormattedView } from './JsonView'

export const PreviewTab = React.memo(function PreviewTab() {
  const { nodeMap } = useExecutionData()
  const { selectedNodeId } = useExecutionSelection()
  const { jsonViewMode } = useExecutionViewPreferences()

  const node = selectedNodeId ? nodeMap.get(selectedNodeId) : null
  const step = node?.step

  if (!step) return <EmptyState message="Select a step to preview" />

  const ViewComponent = jsonViewMode === 'json' ? JsonView : FormattedView

  switch (step.stepType) {
    case 'agent_thought':
    case 'code_agent_thought':
      return (
        <div className="p-4">
          <ThoughtContent step={step} showHeader={false} />
        </div>
      )

    case 'tool_execution':
      return (
        <div className="p-4">
          <ToolCallCard step={step} defaultCollapsed={false} showHeader={false} />
        </div>
      )

    case 'model_io':
      return (
        <div className="p-4">
          <ModelIOCard step={step} defaultCollapsed={false} showHeader={false} />
        </div>
      )

    case 'node_lifecycle': {
      const nodeData = step.data as Record<string, unknown> | undefined
      return (
        <div className="space-y-3 p-4">
          {nodeData?.input ? <ViewComponent data={nodeData.input} label="Input" /> : null}
          {step.content && <ViewComponent data={step.content} label="Content" />}
          {!nodeData?.input && !step.content && (
            <ViewComponent
              data={step.data || { nodeId: step.nodeId, nodeLabel: step.nodeLabel }}
              label="Node Info"
            />
          )}
        </div>
      )
    }

    case 'code_agent_code':
      return (
        <div className="p-4">
          <SyntaxHighlighter
            language="python"
            style={oneLight}
            customStyle={{
              margin: 0,
              padding: '1rem',
              background: 'var(--surface-2)',
              fontSize: '11px',
              lineHeight: '1.6',
              borderRadius: '6px',
              border: '1px solid var(--border)',
            }}
          >
            {step.content || ''}
          </SyntaxHighlighter>
        </div>
      )

    case 'code_agent_observation':
      return (
        <div className="p-4">
          <div
            className={cn(
              'whitespace-pre-wrap rounded-md border p-3 font-mono text-xs leading-relaxed',
              (step.data as Record<string, unknown>)?.has_error
                ? 'border-red-200 bg-red-50 text-red-700'
                : 'border-teal-200 bg-teal-50 text-teal-700',
            )}
          >
            {step.content}
          </div>
        </div>
      )

    case 'code_agent_final_answer':
      return (
        <div className="p-4">
          <div className="whitespace-pre-wrap rounded-md border border-green-200 bg-green-50 p-3 font-mono text-xs leading-relaxed text-green-700">
            {step.content}
          </div>
        </div>
      )

    case 'code_agent_planning':
      return (
        <div className="p-4">
          <div className="whitespace-pre-wrap rounded-md border border-orange-200 bg-orange-50 p-3 font-mono text-xs leading-relaxed text-orange-700">
            {step.content}
          </div>
        </div>
      )

    case 'code_agent_error':
      return (
        <div className="p-4">
          <div className="whitespace-pre-wrap rounded-md border border-red-200 bg-red-50 p-3 font-mono text-xs leading-relaxed text-red-700">
            {step.content}
          </div>
        </div>
      )

    default:
      return (
        <div className="p-4">
          <ViewComponent data={step.data || step.content || step} />
        </div>
      )
  }
})
