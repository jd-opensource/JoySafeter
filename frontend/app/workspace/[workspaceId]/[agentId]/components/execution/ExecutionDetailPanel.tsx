'use client'

/**
 * ExecutionDetailPanel - Right panel showing details of the selected execution node.
 *
 * Features:
 * - Tabbed interface: Preview | Output | Metadata
 * - Formatted / JSON toggle
 * - Routes to appropriate view based on step type
 *
 * Inspired by langfuse ObservationDetailView.tsx
 */

import { Braces, Code2, Eye, FileText, Info, AlignLeft } from 'lucide-react'
import { useMemo } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { ModelIOCard } from '../ModelIOCard'
import { ThoughtContent } from '../ThoughtContent'
import { ToolCallCard } from '../ToolCallCard'

import { useExecutionData } from './contexts/ExecutionDataContext'
import { useExecutionSelection } from './contexts/ExecutionSelectionContext'
import {
  useExecutionViewPreferences,
  type DetailTab,
} from './contexts/ExecutionViewPreferencesContext'

/**
 * Format JSON to better display string values containing newlines
 */
function formatJsonWithNewlines(data: any): string {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

function JsonView({ data, label }: { data: any; label?: string }) {
  if (!data) return null

  return (
    <div className="space-y-1">
      {label && (
        <div className="px-1 text-2xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
          {label}
        </div>
      )}
      <SyntaxHighlighter
        language="json"
        style={oneLight}
        PreTag="div"
        codeTagProps={{
          style: {
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            overflowWrap: 'break-word',
          },
        }}
        customStyle={{
          margin: 0,
          padding: '0.75rem',
          background: 'var(--surface-2)',
          fontSize: '11px',
          lineHeight: '1.6',
          fontFamily: 'JetBrains Mono, monospace',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          overflowWrap: 'break-word',
          maxWidth: '100%',
          borderRadius: '6px',
          border: '1px solid var(--border)',
        }}
        wrapLongLines={true}
      >
        {formatJsonWithNewlines(data)}
      </SyntaxHighlighter>
    </div>
  )
}

function FormattedView({ data, label }: { data: any; label?: string }) {
  if (!data) return null

  if (typeof data === 'string') {
    return (
      <div className="space-y-1">
        {label && (
          <div className="px-1 text-2xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
            {label}
          </div>
        )}
        <div className="whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3 font-mono text-xs leading-relaxed text-[var(--text-secondary)]">
          {data}
        </div>
      </div>
    )
  }

  return <JsonView data={data} label={label} />
}

// ============ Tab Content Components ============

function PreviewTab() {
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
}

function OutputTab() {
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
            <div className="flex items-center gap-2 text-cyan-600">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-500" />
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
}

function MetadataTab() {
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
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-12 text-[var(--text-muted)]">
      <Braces size={32} strokeWidth={0.5} className="text-[var(--text-subtle)]" />
      <p className="font-mono text-xs">{message}</p>
    </div>
  )
}

// ============ Main Component ============

export function ExecutionDetailPanel() {
  const { t } = useTranslation()
  const { nodeMap } = useExecutionData()
  const { selectedNodeId } = useExecutionSelection()
  const { jsonViewMode, setJsonViewMode, activeDetailTab, setActiveDetailTab } =
    useExecutionViewPreferences()

  const node = selectedNodeId ? nodeMap.get(selectedNodeId) : null
  const step = node?.step

  if (!step) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[var(--text-muted)]">
        <Braces size={40} strokeWidth={0.5} className="text-[var(--text-subtle)]" />
        <p className="font-mono text-xs">
          {t('workspace.selectStepToInspectPayload', {
            defaultValue: 'Select a step to inspect payload',
          })}
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-[var(--surface-elevated)]">
      {/* Header */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface-2)] px-3">
        <div className="flex min-w-0 items-center gap-2">
          <AlignLeft size={13} className="shrink-0 text-[var(--text-tertiary)]" />
          <span className="truncate text-app-xs font-semibold text-[var(--text-primary)]">
            {step.title || step.nodeLabel}
          </span>
          <span className="shrink-0 rounded border border-[var(--border)] bg-[var(--surface-3)] px-1.5 py-0.5 font-mono text-micro text-[var(--text-muted)]">
            {step.stepType}
          </span>
        </div>

        {/* Formatted / JSON toggle */}
        <div className="flex items-center gap-0.5 rounded-md border border-[var(--border)] bg-[var(--surface-3)] p-0.5">
          <button
            onClick={() => setJsonViewMode('formatted')}
            className={cn(
              'rounded px-2 py-0.5 text-micro font-medium transition-colors',
              jsonViewMode === 'formatted'
                ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm'
                : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]',
            )}
          >
            <FileText size={10} className="mr-1 inline" />
            Formatted
          </button>
          <button
            onClick={() => setJsonViewMode('json')}
            className={cn(
              'rounded px-2 py-0.5 text-micro font-medium transition-colors',
              jsonViewMode === 'json'
                ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm'
                : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]',
            )}
          >
            <Code2 size={10} className="mr-1 inline" />
            JSON
          </button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        value={activeDetailTab}
        onValueChange={(v) => setActiveDetailTab(v as DetailTab)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="h-8 shrink-0 justify-start gap-0 rounded-none border-b border-[var(--border)] bg-transparent px-3">
          <TabsTrigger
            value="preview"
            className="h-8 rounded-none border-b-2 border-transparent px-3 text-app-xs data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
          >
            <Eye size={12} className="mr-1" />
            Preview
          </TabsTrigger>
          <TabsTrigger
            value="output"
            className="h-8 rounded-none border-b-2 border-transparent px-3 text-app-xs data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
          >
            <AlignLeft size={12} className="mr-1" />
            Output
          </TabsTrigger>
          <TabsTrigger
            value="metadata"
            className="h-8 rounded-none border-b-2 border-transparent px-3 text-app-xs data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
          >
            <Info size={12} className="mr-1" />
            Metadata
          </TabsTrigger>
        </TabsList>

        <div className="flex-1 overflow-auto">
          <TabsContent value="preview" className="mt-0 h-full">
            <PreviewTab />
          </TabsContent>
          <TabsContent value="output" className="mt-0 h-full">
            <OutputTab />
          </TabsContent>
          <TabsContent value="metadata" className="mt-0 h-full">
            <MetadataTab />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}
