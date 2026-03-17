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

import {
  Braces,
  Code2,
  Eye,
  FileText,
  Info,
  AlignLeft,
} from 'lucide-react'
import React, { useMemo } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'

import { ThoughtContent } from '../ThoughtContent'
import { ToolCallCard } from '../ToolCallCard'
import { ModelIOCard } from '../ModelIOCard'

import { useExecutionData } from './contexts/ExecutionDataContext'
import { useExecutionSelection } from './contexts/ExecutionSelectionContext'
import { useExecutionViewPreferences, type DetailTab, type JsonViewMode } from './contexts/ExecutionViewPreferencesContext'

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
        <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-1">
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
          background: 'rgb(249 250 251)',
          fontSize: '11px',
          lineHeight: '1.6',
          fontFamily: 'JetBrains Mono, monospace',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          overflowWrap: 'break-word',
          maxWidth: '100%',
          borderRadius: '6px',
          border: '1px solid rgb(229 231 235)',
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
          <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-1">
            {label}
          </div>
        )}
        <div className="text-xs text-gray-700 font-mono whitespace-pre-wrap bg-gray-50 rounded-md p-3 border border-gray-200 leading-relaxed">
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

    case 'node_lifecycle':
      return (
        <div className="p-4 space-y-3">
          {step.data?.input && <ViewComponent data={step.data.input} label="Input" />}
          {step.content && <ViewComponent data={step.content} label="Content" />}
          {!step.data?.input && !step.content && (
            <ViewComponent data={step.data || { nodeId: step.nodeId, nodeLabel: step.nodeLabel }} label="Node Info" />
          )}
        </div>
      )

    case 'code_agent_code':
      return (
        <div className="p-4">
          <SyntaxHighlighter
            language="python"
            style={oneLight}
            customStyle={{
              margin: 0,
              padding: '1rem',
              background: 'rgb(249 250 251)',
              fontSize: '11px',
              lineHeight: '1.6',
              borderRadius: '6px',
              border: '1px solid rgb(229 231 235)',
            }}
          >
            {step.content || ''}
          </SyntaxHighlighter>
        </div>
      )

    case 'code_agent_observation':
      return (
        <div className="p-4">
          <div className={cn(
            'text-xs font-mono leading-relaxed border rounded-md p-3 whitespace-pre-wrap',
            step.data?.has_error
              ? 'text-red-700 bg-red-50 border-red-200'
              : 'text-teal-700 bg-teal-50 border-teal-200'
          )}>
            {step.content}
          </div>
        </div>
      )

    case 'code_agent_final_answer':
      return (
        <div className="p-4">
          <div className="text-xs text-green-700 font-mono leading-relaxed bg-green-50 border border-green-200 rounded-md p-3 whitespace-pre-wrap">
            {step.content}
          </div>
        </div>
      )

    case 'code_agent_planning':
      return (
        <div className="p-4">
          <div className="text-xs text-orange-700 font-mono leading-relaxed bg-orange-50 border border-orange-200 rounded-md p-3 whitespace-pre-wrap">
            {step.content}
          </div>
        </div>
      )

    case 'code_agent_error':
      return (
        <div className="p-4">
          <div className="text-xs text-red-700 font-mono leading-relaxed bg-red-50 border border-red-200 rounded-md p-3 whitespace-pre-wrap">
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
        <div className="p-4 space-y-3">
          {step.data?.response ? (
            <ViewComponent data={step.data.response} label="Tool Output" />
          ) : step.status === 'running' ? (
            <div className="flex items-center gap-2 text-cyan-600">
              <div className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
              <span className="text-xs font-mono">Executing...</span>
            </div>
          ) : (
            <EmptyState message="No output available" />
          )}
        </div>
      )

    case 'model_io':
      return (
        <div className="p-4 space-y-3">
          {step.data?.output ? (
            <ViewComponent data={step.data.output} label="Model Output" />
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
        <div className="p-4 space-y-3">
          {step.data?.output ? (
            <ViewComponent data={step.data.output} label="Node Output" />
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
    // Trace / Observation 信息
    if (step.traceId) meta.traceId = step.traceId
    if (step.observationId) meta.observationId = step.observationId
    if (step.parentObservationId) meta.parentObservationId = step.parentObservationId
    // Token 使用
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
          <div key={key} className="flex items-start gap-3 py-1.5 border-b border-gray-100 last:border-b-0">
            <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider w-24 shrink-0 pt-0.5">
              {key}
            </span>
            <span className="text-[11px] text-gray-700 font-mono break-all">
              {value === null ? <span className="text-gray-300 italic">null</span> : String(value)}
            </span>
          </div>
        ))}
      </div>

      {/* Raw data section */}
      {step.data && (
        <div className="mt-4">
          <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
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
    <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-3 py-12">
      <Braces size={32} strokeWidth={0.5} className="text-gray-300" />
      <p className="text-xs font-mono">{message}</p>
    </div>
  )
}

// ============ Main Component ============

export const ExecutionDetailPanel: React.FC = () => {
  const { t } = useTranslation()
  const { nodeMap } = useExecutionData()
  const { selectedNodeId } = useExecutionSelection()
  const { jsonViewMode, setJsonViewMode, activeDetailTab, setActiveDetailTab } = useExecutionViewPreferences()

  const node = selectedNodeId ? nodeMap.get(selectedNodeId) : null
  const step = node?.step

  if (!step) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-3">
        <Braces size={40} strokeWidth={0.5} className="text-gray-300" />
        <p className="text-xs font-mono">
          {t('workspace.selectStepToInspectPayload', { defaultValue: 'Select a step to inspect payload' })}
        </p>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="h-9 border-b border-gray-200 flex items-center px-3 bg-gray-50/80 shrink-0 justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <AlignLeft size={13} className="text-gray-500 shrink-0" />
          <span className="text-[11px] font-semibold text-gray-800 truncate">
            {step.title || step.nodeLabel}
          </span>
          <span className="text-[9px] text-gray-400 font-mono bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200 shrink-0">
            {step.stepType}
          </span>
        </div>

        {/* Formatted / JSON toggle */}
        <div className="flex items-center gap-0.5 bg-gray-100 rounded-md p-0.5 border border-gray-200">
          <button
            onClick={() => setJsonViewMode('formatted')}
            className={cn(
              'px-2 py-0.5 rounded text-[9px] font-medium transition-colors',
              jsonViewMode === 'formatted'
                ? 'bg-white text-gray-800 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            )}
          >
            <FileText size={10} className="inline mr-1" />
            Formatted
          </button>
          <button
            onClick={() => setJsonViewMode('json')}
            className={cn(
              'px-2 py-0.5 rounded text-[9px] font-medium transition-colors',
              jsonViewMode === 'json'
                ? 'bg-white text-gray-800 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            )}
          >
            <Code2 size={10} className="inline mr-1" />
            JSON
          </button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeDetailTab} onValueChange={(v) => setActiveDetailTab(v as DetailTab)} className="flex-1 flex flex-col min-h-0">
        <TabsList className="h-8 bg-transparent border-b border-gray-200 rounded-none px-3 gap-0 justify-start shrink-0">
          <TabsTrigger
            value="preview"
            className="h-8 rounded-none border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none text-[11px] px-3"
          >
            <Eye size={12} className="mr-1" />
            Preview
          </TabsTrigger>
          <TabsTrigger
            value="output"
            className="h-8 rounded-none border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none text-[11px] px-3"
          >
            <AlignLeft size={12} className="mr-1" />
            Output
          </TabsTrigger>
          <TabsTrigger
            value="metadata"
            className="h-8 rounded-none border-b-2 border-transparent data-[state=active]:border-blue-500 data-[state=active]:bg-transparent data-[state=active]:shadow-none text-[11px] px-3"
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
