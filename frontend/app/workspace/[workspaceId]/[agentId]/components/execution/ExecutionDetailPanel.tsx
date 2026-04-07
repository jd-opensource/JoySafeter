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

import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useExecutionData } from './contexts/ExecutionDataContext'
import { useExecutionSelection } from './contexts/ExecutionSelectionContext'
import {
  useExecutionViewPreferences,
  type DetailTab,
} from './contexts/ExecutionViewPreferencesContext'
import { MetadataTab } from './MetadataTab'
import { OutputTab } from './OutputTab'
import { PreviewTab } from './PreviewTab'

export function EmptyState({ message }: { message: string }) {
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
