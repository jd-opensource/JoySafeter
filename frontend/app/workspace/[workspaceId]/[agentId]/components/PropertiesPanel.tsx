'use client'

import { X, AlertCircle, Settings, Hammer, Sparkles } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useCallback, useMemo } from 'react'
import { Node, Edge } from 'reactflow'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { nodeRegistry, FieldSchema } from '../services/nodeRegistry'
import { useBuilderStore } from '../stores/builderStore'

import { MemorySection } from './MemorySection'
import { SchemaFieldRenderer } from './SchemaFieldRenderer'
import { SectionHeader } from './SectionHeader'

// Re-export SectionHeader for any existing consumers
export { SectionHeader } from './SectionHeader'

interface PropertiesPanelProps {
  node: Node
  nodes: Node[]
  edges: Edge[]
  onUpdate: (id: string, data: { label: string; config?: Record<string, unknown> }) => void
  onClose: () => void
}

// ============================================================================
// Utility Functions
// ============================================================================

function normalizeValue(value: unknown): string | boolean | number {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value
  if (typeof value === 'string') {
    const lower = value.toLowerCase()
    return lower === 'true' ? true : lower === 'false' ? false : value
  }
  return String(value)
}

function shouldShowField(field: FieldSchema, config: Record<string, unknown>): boolean {
  if (!field.showWhen) return true
  const dependentValue = config[field.showWhen.field]
  const normalizedDependent = normalizeValue(dependentValue)
  return field.showWhen.values.some((val) => normalizeValue(val) === normalizedDependent)
}

// ============================================================================
// Sub-components
// ============================================================================

/** Renders a list of SchemaFieldRenderer items under a SectionHeader */
const FieldListSection = React.memo(function FieldListSection({
  icon,
  title,
  fields,
  config,
  updateConfig,
  canEdit,
  t,
  nodes,
  edges,
  currentNodeId,
  graphStateFields,
}: {
  icon: React.ElementType
  title: string
  fields: FieldSchema[]
  config: Record<string, unknown>
  updateConfig: (key: string, value: unknown) => void
  canEdit: boolean
  t: (key: string, options?: Record<string, unknown>) => string
  nodes: Node[]
  edges: Edge[]
  currentNodeId: string
  graphStateFields?: import('../types/graph').StateField[]
}) {
  if (fields.length === 0) return null
  return (
    <div className="space-y-4">
      <SectionHeader icon={icon} title={title} />
      {fields.map((field) => (
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
    </div>
  )
})

export default function PropertiesPanel({
  node,
  nodes,
  edges,
  onUpdate,
  onClose,
}: PropertiesPanelProps) {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const { toast } = useToast()
  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)
  const { onConnect, updateEdge, graphStateFields } = useBuilderStore()
  const nodeData = node?.data as
    | { type: string; label?: string; config?: Record<string, unknown> }
    | undefined
  const def = nodeData ? nodeRegistry.get(nodeData.type) : undefined

  const config = useMemo(() => nodeData?.config || {}, [nodeData?.config])

  const validationErrors = useMemo(() => {
    const errors: { field: string; message: string; severity?: string }[] = []
    if (!def) return errors
    def.schema.forEach((field) => {
      if (field.required && !config[field.key] && config[field.key] !== 0 && config[field.key] !== false) {
        if (field.showWhen) {
          const dependentValue = config[field.showWhen.field]
          if (!field.showWhen.values.includes(String(dependentValue))) return
        }
        errors.push({
          field: field.label || field.key,
          message: t('workspace.fieldRequired', { defaultValue: 'Field is required' }),
          severity: 'error',
        })
      }
    })
    return errors
  }, [def, config, t])

  const updateConfig = useCallback((key: string, value: unknown) => {
    if (!userPermissions.canEdit) {
      toast({ title: t('workspace.noPermission'), description: t('workspace.cannotEditNode'), variant: 'destructive' })
      return
    }
    onUpdate(node.id, { label: nodeData?.label || '', config: { ...config, [key]: value } })
  }, [userPermissions.canEdit, toast, t, onUpdate, node.id, nodeData?.label, config])

  const updateModelConfig = useCallback((modelName: string, providerName: string) => {
    const combinedModelId = `${providerName}:${modelName}`
    onUpdate(node.id, {
      label: nodeData?.label || '',
      config: { ...config, model_name: modelName, provider_name: providerName, model: combinedModelId, provider: providerName },
    })
  }, [onUpdate, node.id, nodeData?.label, config])

  const handleMemoryModelChange = useCallback((modelName: string, providerName: string) => {
    const combinedModelId = `${providerName}:${modelName}`
    onUpdate(node.id, {
      label: nodeData?.label || '',
      config: { ...config, memoryModel: combinedModelId, memoryProvider: providerName },
    })
  }, [onUpdate, node.id, nodeData?.label, config])

  if (!node || !nodeData) return null

  const Icon = def?.icon || AlertCircle
  const enableMemory = config.enableMemory === true

  const parentNodes = edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => nodes.find((n) => n.id === edge.source))
    .filter(Boolean) as Node[]
  const hasParentWithDeepAgents = parentNodes.some((p) => {
    const pd = p?.data as { config?: Record<string, unknown> }
    return pd?.config?.useDeepAgents === true
  })

  const basicFields = def?.schema.filter(
    (s) => !['enableMemory', 'memoryModel', 'memoryPrompt', 'description'].includes(s.key) && s.type !== 'toolSelector' && !(s.type === 'skillSelector' && !s.showWhen),
  ) || []
  const toolsFields = def?.schema.filter((s) => s.type === 'toolSelector') || []
  const skillsFields = def?.schema.filter((s) => s.type === 'skillSelector' && !s.showWhen) || []
  const memoryFields = def?.schema.filter((s) => ['enableMemory', 'memoryModel', 'memoryPrompt'].includes(s.key)) || []
  const descriptionField = def?.schema.find((s) => s.key === 'description')

  return (
    <div className="absolute bottom-[60px] right-[336px] top-[56px] z-50 flex w-[400px] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-1)] shadow-2xl duration-300 animate-in fade-in slide-in-from-right-10">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-3.5">
        <div className="flex items-center gap-3 overflow-hidden text-[var(--text-primary)]">
          <div className={cn('shrink-0 rounded-lg border border-[var(--border)] p-1.5 shadow-sm', def?.style.bg, def?.style.color)}>
            <Icon size={14} />
          </div>
          <div className="flex min-w-0 flex-col">
            <h3 className="truncate text-sm font-bold leading-tight">{nodeData.label || def?.label}</h3>
            <span className="text-micro font-bold uppercase tracking-widest text-[var(--text-muted)]">{def?.label}</span>
          </div>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} className="h-7 w-7 text-[var(--text-disabled)] hover:bg-[var(--surface-2)] hover:text-[var(--text-secondary)]" aria-label={t('workspace.closePanel', { defaultValue: 'Close panel' })}>
          <X size={16} />
        </Button>
      </div>

      {/* Body */}
      <div className="custom-scrollbar flex-1 space-y-6 overflow-y-auto p-4 pb-12">
        {/* Validation Errors */}
        {validationErrors.length > 0 && (
          <div className="space-y-2">
            <Label className="text-2xs font-bold uppercase tracking-wider text-[var(--status-error)]">Configuration Errors</Label>
            <div className="space-y-1">
              {validationErrors.map((error, idx) => (
                <div key={idx} className="flex items-start gap-2 rounded border border-[var(--status-error-border)] bg-[var(--status-error-bg)] p-2 text-xs">
                  <AlertCircle size={14} className="mt-0.5 flex-shrink-0 text-[var(--status-error)]" />
                  <div className="text-[var(--status-error-strong)]">
                    <div className="font-medium">{error.field}</div>
                    <div className="text-[var(--status-error)]">{error.message}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Section: General */}
        <div className="space-y-4">
          <SectionHeader icon={Settings} title={t('workspace.general')} />
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-2xs font-bold uppercase tracking-wider text-[var(--text-muted)]">{t('workspace.displayName')}</Label>
              <Input
                value={nodeData.label || ''}
                onChange={(e) => {
                  if (!userPermissions.canEdit) {
                    toast({ title: t('workspace.noPermission'), description: t('workspace.cannotEditNode'), variant: 'destructive' })
                    return
                  }
                  onUpdate(node.id, { label: e.target.value, config })
                }}
                disabled={!userPermissions.canEdit}
                className="h-8 text-xs font-medium"
              />
            </div>
            {basicFields
              .filter((field) => shouldShowField(field, config))
              .map((field) => (
                <SchemaFieldRenderer
                  key={field.key}
                  schema={field}
                  value={config[field.key]}
                  onChange={(val) => updateConfig(field.key, val)}
                  canEdit={userPermissions.canEdit}
                  t={t}
                  onModelChange={field.key === 'model' ? updateModelConfig : undefined}
                  nodes={nodes}
                  edges={edges}
                  currentNodeId={node.id}
                  onCreateEdge={undefined}
                  graphStateFields={graphStateFields}
                />
              ))}

            {hasParentWithDeepAgents && descriptionField && (
              <div className="space-y-1.5 border-l-2 border-[var(--brand-200)] pl-4 duration-300 animate-in slide-in-from-top-2">
                <SchemaFieldRenderer
                  schema={{ ...descriptionField, required: true }}
                  value={config[descriptionField.key]}
                  onChange={(val) => updateConfig(descriptionField.key, val)}
                  canEdit={userPermissions.canEdit}
                  t={t}
                  nodes={nodes}
                  edges={edges}
                  currentNodeId={node.id}
                  onCreateEdge={undefined}
                  graphStateFields={graphStateFields}
                />
              </div>
            )}
          </div>
        </div>

        {/* Section: Tools */}
        <FieldListSection
          icon={Hammer}
          title={t('workspace.capabilities')}
          fields={toolsFields}
          config={config}
          updateConfig={updateConfig}
          canEdit={userPermissions.canEdit}
          t={t}
          nodes={nodes}
          edges={edges}
          currentNodeId={node.id}
          graphStateFields={graphStateFields}
        />

        {/* Section: Skills */}
        <FieldListSection
          icon={Sparkles}
          title={t('workspace.skills', { defaultValue: 'Skills' })}
          fields={skillsFields}
          config={config}
          updateConfig={updateConfig}
          canEdit={userPermissions.canEdit}
          t={t}
          nodes={nodes}
          edges={edges}
          currentNodeId={node.id}
          graphStateFields={graphStateFields}
        />

        {/* Section: Memory */}
        <MemorySection
          memoryFields={memoryFields}
          config={config}
          enableMemory={enableMemory}
          updateConfig={updateConfig}
          canEdit={userPermissions.canEdit}
          nodes={nodes}
          edges={edges}
          currentNodeId={node.id}
          graphStateFields={graphStateFields}
          onMemoryModelChange={handleMemoryModelChange}
        />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-[var(--border)] bg-[var(--surface-2)] px-4 py-2 font-mono text-micro text-[var(--text-muted)]">
        <span className="truncate">TYPE: {nodeData.type}</span>
        <span className="flex items-center gap-1">
          <div className="h-1.5 w-1.5 rounded-full bg-[var(--status-success)]" /> {t('workspace.synced')}
        </span>
      </div>
    </div>
  )
}
