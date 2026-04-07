'use client'

import { BrainCircuit } from 'lucide-react'
import React from 'react'
import { Node, Edge } from 'reactflow'

import { useTranslation } from '@/lib/i18n'

import { FieldSchema } from '../services/nodeRegistry'
import type { StateField } from '../types/graph'

import { SchemaFieldRenderer } from './SchemaFieldRenderer'
import { SectionHeader } from './SectionHeader'

interface MemorySectionProps {
  memoryFields: FieldSchema[]
  config: Record<string, unknown>
  enableMemory: boolean
  updateConfig: (key: string, value: unknown) => void
  canEdit: boolean
  nodes: Node[]
  edges: Edge[]
  currentNodeId: string
  graphStateFields?: StateField[]
  onMemoryModelChange: (modelName: string, providerName: string) => void
}

export const MemorySection = React.memo(function MemorySection({
  memoryFields,
  config,
  enableMemory,
  updateConfig,
  canEdit,
  nodes,
  edges,
  currentNodeId,
  graphStateFields,
  onMemoryModelChange,
}: MemorySectionProps) {
  const { t } = useTranslation()

  if (memoryFields.length === 0) return null

  return (
    <div className="space-y-4">
      <SectionHeader icon={BrainCircuit} title={t('workspace.knowledgeMemory')} />

      {/* Always show Enable Memory toggle */}
      {memoryFields
        .filter((f) => f.key === 'enableMemory')
        .map((field) => (
          <SchemaFieldRenderer
            key={field.key}
            schema={field}
            value={config[field.key]}
            onChange={(val) => updateConfig(field.key, val)}
            canEdit={canEdit}
            t={t}
            nodes={nodes}
            edges={edges}
            currentNodeId={currentNodeId}
            onCreateEdge={undefined}
            graphStateFields={graphStateFields}
          />
        ))}

      {/* Nested conditional fields */}
      {enableMemory && (
        <div className="space-y-4 border-l-2 border-[var(--brand-100)] pl-4 duration-300 animate-in slide-in-from-top-2">
          {memoryFields
            .filter((f) => f.key !== 'enableMemory')
            .map((field) => (
              <SchemaFieldRenderer
                key={field.key}
                schema={field}
                value={config[field.key]}
                onChange={(val) => updateConfig(field.key, val)}
                canEdit={canEdit}
                t={t}
                nodes={nodes}
                edges={edges}
                currentNodeId={currentNodeId}
                onCreateEdge={undefined}
                graphStateFields={graphStateFields}
                onModelChange={
                  field.key === 'memoryModel'
                    ? onMemoryModelChange
                    : undefined
                }
              />
            ))}
        </div>
      )}

      {!enableMemory && (
        <p className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface-2)] p-2 text-2xs italic text-[var(--text-muted)]">
          {t('workspace.memoryDisabled')}
        </p>
      )}
    </div>
  )
})
