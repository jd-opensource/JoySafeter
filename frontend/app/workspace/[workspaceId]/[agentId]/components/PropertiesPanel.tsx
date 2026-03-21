'use client'

import { X, AlertCircle, Settings, BrainCircuit, Hammer, Sparkles, Database } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useMemo } from 'react'
import { Node, Edge } from 'reactflow'

// import { validateNodeConfig } from '../services/nodeConfigValidator'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/components/ui/use-toast'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import {
  getTemplatesForNodeType,
  applyTemplate,
} from '../services/nodeConfigTemplates'
import { nodeRegistry, FieldSchema } from '../services/nodeRegistry'
import { useBuilderStore } from '../stores/builderStore'
import { EdgeData } from '../types/graph'

import { ConditionExprField } from './fields/ConditionExprField'
import { DockerConfigField } from './fields/DockerConfigField'
import { KVListField } from './fields/KVListField'
import { ModelSelectField } from './fields/ModelSelectField'
import { RouteListField } from './fields/RouteListField'
import { SkillsField } from './fields/SkillsField'
import { StateMapperField } from './fields/StateMapperField'
import { StringArrayField } from './fields/StringArrayField'
import { ToolsField } from './fields/ToolsField'
import { VariableInputField } from './fields/VariableInputField'

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

/**
 * Normalize a value for comparison (handles boolean strings, types)
 * Converts 'true'/'false' strings to boolean, preserves other types
 */
function normalizeValue(value: unknown): string | boolean | number {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value
  if (typeof value === 'string') {
    const lower = value.toLowerCase()
    return lower === 'true' ? true : lower === 'false' ? false : value
  }
  return String(value)
}

/**
 * Check if a field should be shown based on showWhen condition
 */
function shouldShowField(field: FieldSchema, config: Record<string, unknown>): boolean {
  if (!field.showWhen) return true

  const dependentValue = config[field.showWhen.field]
  const normalizedDependent = normalizeValue(dependentValue)

  return field.showWhen.values.some((val) => {
    const normalizedVal = normalizeValue(val)
    return normalizedVal === normalizedDependent
  })
}

// ============================================================================
// Components
// ============================================================================

const SchemaFieldRenderer = ({
  schema,
  value,
  onChange,
  disabled = false,
  canEdit = true,
  t,
  onModelChange, // New: For updating both provider_name and model_name when selecting model
  nodes,
  edges,
  currentNodeId,
  onCreateEdge, // New: Callback for creating edges
  graphStateFields,
}: {
  schema: FieldSchema
  value: unknown
  onChange: (val: unknown) => void
  disabled?: boolean
  canEdit?: boolean
  t: (key: string, options?: Record<string, unknown>) => string
  onModelChange?: (modelName: string, providerName: string) => void // New
  nodes?: Node[]
  edges?: Edge[]
  currentNodeId?: string
  onCreateEdge?: (targetNodeId: string, routeKey: string) => void // New
  graphStateFields?: import('../types/graph').StateField[]
}) => {
  let input = null

  if (disabled || !canEdit) return null

  // Get translated field label
  const getFieldLabel = (key: string) => {
    const fieldKey = `workspace.nodeFields.${key}`
    try {
      const translated = t(fieldKey)
      // If translation exists and is different from key, use it
      if (translated && translated !== fieldKey) {
        return translated
      }
    } catch {
      // Translation key doesn't exist, use default
    }
    return schema.label
  }

  const translatedLabel = getFieldLabel(schema.key)

  switch (schema.type) {
    case 'boolean':
      input = (
        <div
          className={cn(
            'flex cursor-pointer select-none items-center justify-between rounded-lg border p-2 transition-all',
            value ? 'border-blue-200 bg-blue-50' : 'border-gray-200 bg-gray-50',
          )}
          onClick={() => onChange(!value)}
        >
          <span className="text-[11px] font-medium text-gray-700">
            {value ? t('workspace.enabled') : t('workspace.disabled')}
          </span>
          <div
            className={cn(
              'relative h-4 w-7 rounded-full border transition-all',
              value ? 'border-blue-600 bg-blue-500' : 'border-gray-400 bg-gray-300',
            )}
          >
            <div
              className={cn(
                'absolute top-[2px] h-2.5 w-2.5 rounded-full bg-white transition-all',
                value ? 'right-[2px]' : 'left-[2px]',
              )}
            />
          </div>
        </div>
      )
      break
    case 'text':
      input = (
        <Input
          value={(value as string) || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={schema.placeholder}
          className="h-8 text-xs focus-visible:ring-1"
        />
      )
      break
    case 'textarea':
      // Check if variable input support is needed (for expression fields)
      const needsVariableSupport = [
        'expression',
        'condition_expression',
        'condition',
        'function_code',
        'input_mapping',
        'prompt',
        'template',
      ].includes(schema.key)

      if (needsVariableSupport && nodes && edges && currentNodeId) {
        input = (
          <VariableInputField
            label={translatedLabel}
            value={(value as string) || ''}
            onChange={(val) => onChange(val)}
            placeholder={schema.placeholder}
            description={schema.description}
            nodes={nodes}
            edges={edges}
            currentNodeId={currentNodeId}
          />
        )
      } else {
        input = (
          <Textarea
            value={(value as string) || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={schema.placeholder}
            className="min-h-[60px] resize-none py-2 text-xs focus-visible:ring-1"
          />
        )
      }
      break
    case 'code':
      input = (
        <Textarea
          value={(value as string) || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={schema.placeholder}
          spellCheck={false}
          className="min-h-[120px] resize-y border-slate-200 bg-slate-50 px-3 py-3 font-mono text-[11px] text-slate-800 shadow-inner focus-visible:ring-1 focus-visible:ring-blue-500"
        />
      )
      break
    case 'select':
      input = (
        <Select value={(value as string) || ''} onValueChange={onChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue
              placeholder={t('workspace.selectOption', { defaultValue: 'Select option' })}
            />
          </SelectTrigger>
          <SelectContent>
            {schema.options?.map((opt) => (
              <SelectItem key={opt} value={opt} className="text-xs">
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
      break
    case 'stateSelect':
      input = (
        <Select value={(value as string) || ''} onValueChange={onChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder={schema.placeholder || 'Select state variable'} />
          </SelectTrigger>
          <SelectContent>
            {graphStateFields?.map((field) => (
              <SelectItem key={field.name} value={field.name} className="text-xs">
                {field.name} ({field.type})
              </SelectItem>
            ))}
            {(!graphStateFields || graphStateFields.length === 0) && (
              <div className="p-2 text-center text-[10px] text-gray-400">
                No state variables defined
              </div>
            )}
          </SelectContent>
        </Select>
      )
      break
    case 'stateMapper':
      input = (
        <StateMapperField
          value={(value as any) || []}
          onChange={onChange}
          graphStateFields={graphStateFields}
          currentNodeId={currentNodeId}
        />
      )
      break
    case 'dockerConfig':
      input = (
        <DockerConfigField
          label={translatedLabel}
          value={(value as Record<string, unknown>) || {}}
          onChange={(val) => onChange(val)}
          description={schema.description}
          disabled={disabled}
        />
      )
      break
    case 'number':
      input = (
        <Input
          type="number"
          value={(value as number) ?? ''}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}
          min={schema.min}
          max={schema.max}
          step={schema.step || 1}
          placeholder={schema.placeholder}
          className="h-8 text-xs"
        />
      )
      break
    case 'conditionExpr':
      input = (
        <ConditionExprField
          value={(value as string) || ''}
          onChange={onChange}
          placeholder={schema.placeholder}
          description={schema.description}
          variables={schema.variables}
          nodes={nodes}
          edges={edges}
          currentNodeId={currentNodeId}
          graphStateFields={graphStateFields}
        />
      )
      break
    case 'routeList':
      const outgoingEdges = edges?.filter((e) => e.source === currentNodeId) || []
      const targetNodes = nodes?.filter((n) => outgoingEdges.some((e) => e.target === n.id)) || []
      input = (
        <RouteListField
          value={(value as any) || []}
          onChange={onChange}
          availableEdges={outgoingEdges}
          targetNodes={targetNodes}
          currentNodeId={currentNodeId || ''}
          nodes={nodes || []}
          edges={edges || []}
          onCreateEdge={onCreateEdge}
        />
      )
      break
    case 'modelSelect':
      // Save both provider_name and model_name simultaneously
      // Note: Need to determine if it's 'model' or 'memoryModel' based on field name
      input = (
        <ModelSelectField
          value={value as string}
          onChange={(modelName) => {
            // Only call onChange if onModelChange is not handling the update
            // to avoid two competing state updates that race
            if (!onModelChange) {
              onChange(modelName)
            }
          }}
          onModelChange={(modelName, providerName) => {
            // Update both model_name and provider_name simultaneously
            if (onModelChange) {
              onModelChange(modelName, providerName)
            } else {
              // Fallback: just update the field value with combined id
              onChange(`${providerName}:${modelName}`)
            }
          }}
        />
      )
      break
    case 'toolSelector':
      input = <ToolsField value={value} onChange={onChange} />
      break
    case 'skillSelector':
      input = <SkillsField value={value} onChange={onChange} />
      break
    case 'kvList':
      input = <KVListField value={value as { key: string; value: string }[]} onChange={onChange} />
      break
    case 'stringArray':
      input = (
        <StringArrayField
          value={(value as string[]) || []}
          onChange={onChange}
          placeholder={schema.placeholder}
          description={schema.description}
        />
      )
      break
    default:
      input = (
        <div className="text-xs text-red-500">
          {t('workspace.unknownFieldType', {
            type: schema.type,
            defaultValue: `Unknown field type: ${schema.type}`,
          })}
        </div>
      )
  }

  return (
    <div className="space-y-1.5 duration-200 animate-in fade-in">
      <Label className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-gray-400">
        {translatedLabel} {schema.required && <span className="text-red-500">*</span>}
      </Label>
      {input}
      {schema.description && (
        <p className="text-[9px] italic leading-tight text-gray-400">{schema.description}</p>
      )}
    </div>
  )
}

const SectionHeader = ({
  icon: Icon,
  title,
  tooltip,
}: {
  icon: React.ElementType
  title: string
  tooltip?: string
}) => (
  <div className="mb-3 mt-2 flex items-center gap-2">
    <Icon size={14} className="text-gray-400" />
    <div className="flex items-center gap-1.5">
      <h4 className="text-[11px] font-bold uppercase tracking-[0.1em] text-gray-500">{title}</h4>
      {tooltip && (
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <AlertCircle size={11} className="cursor-help text-gray-400" />
            </TooltipTrigger>
            <TooltipContent
              side="top"
              className="max-w-[200px] text-[11px] font-normal normal-case leading-relaxed tracking-normal text-slate-700"
            >
              {tooltip}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
    </div>
    <div className="ml-1 h-[1px] flex-1 bg-gray-100" />
  </div>
)

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
    | {
        type: string
        label?: string
        config?: Record<string, unknown>
      }
    | undefined
  const def = nodeData ? nodeRegistry.get(nodeData.type) : undefined

  const config = useMemo(() => nodeData?.config || {}, [nodeData?.config])
  const nodeType = nodeData?.type || ''

  // Get available templates for this node type
  const templates = nodeType ? getTemplatesForNodeType(nodeType) : []

  // Validate configuration using schema
  const validationErrors = useMemo(() => {
    const errors: { field: string; message: string; severity?: string }[] = []
    if (!def) return errors

    def.schema.forEach((field) => {
      if (
        field.required &&
        !config[field.key] &&
        config[field.key] !== 0 &&
        config[field.key] !== false
      ) {
        // Check showWhen condition
        if (field.showWhen) {
          const dependentValue = config[field.showWhen.field]
          if (!field.showWhen.values.includes(String(dependentValue))) {
            return // Skip if field is hidden
          }
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

  const { showAdvancedSettings } = useBuilderStore()

  if (!node || !nodeData) return null

  const updateConfig = (key: string, value: unknown) => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }
    // Allow free editing without immediate validation
    // Validation will be performed on save/deploy
    const newConfig = { ...config, [key]: value }
    onUpdate(node.id, { label: nodeData.label || '', config: newConfig })
  }

  const applyTemplateConfig = (templateName: string) => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }
    const templateConfig = applyTemplate(nodeType, templateName)
    if (templateConfig) {
      onUpdate(node.id, { label: nodeData.label || '', config: templateConfig })
      toast({
        title: 'Template Applied',
        description: `Applied template: ${templateName}`,
      })
    }
  }

  // Handle edge creation from RouteListField
  const handleCreateEdge = (targetNodeId: string, routeKey: string) => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }

    // Check if edge already exists
    const existingEdge = edges.find((e) => e.source === node.id && e.target === targetNodeId)
    if (existingEdge) {
      // Update existing edge
      const edgeData: EdgeData = {
        edge_type: 'conditional',
        route_key: routeKey,
      }
      updateEdge(existingEdge.id, edgeData)
      toast({
        title: 'Edge Updated',
        description: `Edge updated with route_key: ${routeKey}`,
      })
      return
    }

    // Create connection using onConnect
    // onConnect is synchronous, so we can find the edge immediately after
    onConnect({
      source: node.id,
      target: targetNodeId,
      sourceHandle: null,
      targetHandle: null,
    })

    // Find the newly created edge and update it with route_key
    // Use requestAnimationFrame to ensure state has been updated
    requestAnimationFrame(() => {
      const { edges: currentEdges } = useBuilderStore.getState()
      const newEdge = currentEdges.find((e) => e.source === node.id && e.target === targetNodeId)
      if (newEdge) {
        const edgeData: EdgeData = {
          edge_type: 'conditional',
          route_key: routeKey,
        }
        updateEdge(newEdge.id, edgeData)
        toast({
          title: 'Edge Created',
          description: `Edge created with route_key: ${routeKey}`,
        })
      }
    })
  }

  // Update both model_name and provider_name simultaneously
  const updateModelConfig = (modelName: string, providerName: string) => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }
    const combinedModelId = `${providerName}:${modelName}`

    // Update both model_name and provider_name simultaneously
    onUpdate(node.id, {
      label: nodeData.label || '',
      config: {
        ...config,
        model_name: modelName,
        provider_name: providerName,
        // Unified storage: keep combined id in `model`
        model: combinedModelId,
        // Backward compatibility: keep provider in `provider`
        provider: providerName,
      },
    })
  }

  const Icon = def?.icon || AlertCircle
  const enableMemory = config.enableMemory === true

  // Check if any parent node has useDeepAgents enabled
  const parentNodes = edges
    .filter((edge) => edge.target === node.id)
    .map((edge) => nodes.find((n) => n.id === edge.source))
    .filter(Boolean) as Node[]

  const hasParentWithDeepAgents = parentNodes.some((parentNode) => {
    const parentData = parentNode?.data as { config?: Record<string, unknown> }
    return parentData?.config?.useDeepAgents === true
  })

  // Filter schema by logical group
  const basicFields =
    def?.schema.filter(
      (s) =>
        !['enableMemory', 'memoryModel', 'memoryPrompt', 'description'].includes(s.key) &&
        s.type !== 'toolSelector' &&
        // Include skillSelector fields that have showWhen condition (they'll be shown in General section)
        !(s.type === 'skillSelector' && !s.showWhen),
    ) || []
  const toolsFields = def?.schema.filter((s) => s.type === 'toolSelector') || []
  // Only show skills fields without showWhen condition in the Skills section
  // Skills with showWhen condition are shown in General section
  const skillsFields = def?.schema.filter((s) => s.type === 'skillSelector' && !s.showWhen) || []
  const memoryFields =
    def?.schema.filter((s) => ['enableMemory', 'memoryModel', 'memoryPrompt'].includes(s.key)) || []
  const descriptionField = def?.schema.find((s) => s.key === 'description')

  return (
    <div className="absolute bottom-[60px] right-[336px] top-[56px] z-50 flex w-[400px] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-2xl duration-300 animate-in fade-in slide-in-from-right-10">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-gray-100 bg-white px-4 py-3.5">
        <div className="flex items-center gap-3 overflow-hidden text-gray-900">
          <div
            className={cn(
              'shrink-0 rounded-lg border border-gray-50 p-1.5 shadow-sm',
              def?.style.bg,
              def?.style.color,
            )}
          >
            <Icon size={14} />
          </div>
          <div className="flex min-w-0 flex-col">
            <h3 className="truncate text-sm font-bold leading-tight">
              {nodeData.label || def?.label}
            </h3>
            <span className="text-[9px] font-bold uppercase tracking-widest text-gray-400">
              {def?.label}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-7 w-7 text-gray-300 hover:bg-gray-100 hover:text-gray-600"
          >
            <X size={16} />
          </Button>
        </div>
      </div>

      {/* Waterfall Body */}
      <div className="custom-scrollbar flex-1 space-y-6 overflow-y-auto p-4 pb-12">
        {/* Configuration Templates */}
        {templates.length > 0 && (
          <div className="space-y-2">
            <Label className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
              Quick Templates
            </Label>
            <div className="space-y-1">
              {templates.map((template) => (
                <button
                  key={template.name}
                  onClick={() => applyTemplateConfig(template.name)}
                  disabled={!userPermissions.canEdit}
                  className="w-full rounded border border-gray-200 px-3 py-2 text-left text-xs transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <div className="font-medium text-gray-900">{template.name}</div>
                  <div className="mt-0.5 text-gray-500">{template.description}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Validation Errors */}
        {validationErrors.length > 0 && (
          <div className="space-y-2">
            <Label className="text-[10px] font-bold uppercase tracking-wider text-red-400">
              Configuration Errors
            </Label>
            <div className="space-y-1">
              {validationErrors.map((error, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2 rounded border border-red-200 bg-red-50 p-2 text-xs"
                >
                  <AlertCircle size={14} className="mt-0.5 flex-shrink-0 text-red-600" />
                  <div className="text-red-800">
                    <div className="font-medium">{error.field}</div>
                    <div className="text-red-600">{error.message}</div>
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
              <Label className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
                {t('workspace.displayName')}
              </Label>
              <Input
                value={nodeData.label || ''}
                onChange={(e) => {
                  if (!userPermissions.canEdit) {
                    toast({
                      title: t('workspace.noPermission'),
                      description: t('workspace.cannotEditNode'),
                      variant: 'destructive',
                    })
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
                  onModelChange={
                    field.key === 'model'
                      ? (modelName, providerName) => updateModelConfig(modelName, providerName)
                      : undefined
                  }
                  nodes={nodes}
                  edges={edges}
                  currentNodeId={node.id}
                  onCreateEdge={handleCreateEdge}
                  graphStateFields={graphStateFields}
                />
              ))}

            {/* DeepAgents Description Field (Conditional - shown when parent has useDeepAgents=true) */}
            {hasParentWithDeepAgents && descriptionField && (
              <div className="space-y-1.5 border-l-2 border-purple-100 pl-4 duration-300 animate-in slide-in-from-top-2">
                <SchemaFieldRenderer
                  schema={{ ...descriptionField, required: true }}
                  value={config[descriptionField.key]}
                  onChange={(val) => updateConfig(descriptionField.key, val)}
                  canEdit={userPermissions.canEdit}
                  t={t}
                  nodes={nodes}
                  edges={edges}
                  currentNodeId={node.id}
                  onCreateEdge={handleCreateEdge}
                  graphStateFields={graphStateFields}
                />
              </div>
            )}
          </div>
        </div>

        {/* Section: Tools */}
        {toolsFields.length > 0 && (
          <div className="space-y-4">
            <SectionHeader icon={Hammer} title={t('workspace.capabilities')} />
            {toolsFields.map((field) => (
              <SchemaFieldRenderer
                key={field.key}
                schema={field}
                value={config[field.key]}
                onChange={(val) => updateConfig(field.key, val)}
                canEdit={userPermissions.canEdit}
                t={t}
                nodes={nodes}
                edges={edges}
                currentNodeId={node.id}
                onCreateEdge={handleCreateEdge}
                graphStateFields={graphStateFields}
              />
            ))}
          </div>
        )}

        {/* Section: Skills */}
        {skillsFields.length > 0 && (
          <div className="space-y-4">
            <SectionHeader
              icon={Sparkles}
              title={t('workspace.skills', { defaultValue: 'Skills' })}
            />
            {skillsFields.map((field) => (
              <SchemaFieldRenderer
                key={field.key}
                schema={field}
                value={config[field.key]}
                onChange={(val) => updateConfig(field.key, val)}
                canEdit={userPermissions.canEdit}
                t={t}
                nodes={nodes}
                edges={edges}
                currentNodeId={node.id}
                onCreateEdge={handleCreateEdge}
                graphStateFields={graphStateFields}
              />
            ))}
          </div>
        )}

        {/* Section: Memory (Conditional Rendering) */}
        {memoryFields.length > 0 && (
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
                  canEdit={userPermissions.canEdit}
                  t={t}
                  nodes={nodes}
                  edges={edges}
                  currentNodeId={node.id}
                  onCreateEdge={handleCreateEdge}
                  graphStateFields={graphStateFields}
                />
              ))}

            {/* Nested conditional fields */}
            {enableMemory && (
              <div className="space-y-4 border-l-2 border-blue-100 pl-4 duration-300 animate-in slide-in-from-top-2">
                {memoryFields
                  .filter((f) => f.key !== 'enableMemory')
                  .map((field) => (
                    <SchemaFieldRenderer
                      key={field.key}
                      schema={field}
                      value={config[field.key]}
                      onChange={(val) => updateConfig(field.key, val)}
                      canEdit={userPermissions.canEdit}
                      t={t}
                      nodes={nodes}
                      edges={edges}
                      currentNodeId={node.id}
                      onCreateEdge={handleCreateEdge}
                      graphStateFields={graphStateFields}
                      onModelChange={
                        field.key === 'memoryModel'
                          ? (modelName, providerName) => {
                              // Update memoryModel and memoryProvider in a single onUpdate call
                              // to avoid race condition where separate updateConfig calls
                              // spread from the same stale config and overwrite each other
                              const combinedModelId = `${providerName}:${modelName}`
                              onUpdate(node.id, {
                                label: nodeData.label || '',
                                config: {
                                  ...config,
                                  memoryModel: combinedModelId,
                                  memoryProvider: providerName,
                                },
                              })
                            }
                          : undefined
                      }
                    />
                  ))}
              </div>
            )}

            {!enableMemory && (
              <p className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-2 text-[10px] italic text-gray-400">
                {t('workspace.memoryDisabled')}
              </p>
            )}
          </div>
        )}
        {/* Section: Output Mapping fields rendered conditionally as normal fields */}

        {/* Section: Input Mapping (Universal) */}
        {showAdvancedSettings && (
          <div className="space-y-4">
            <SectionHeader
              icon={Database}
              title={t('workspace.inputMapping', { defaultValue: 'Input Mapping' })}
              tooltip="Advanced: Map global state variables into this node's context. These will be available as 'context.mapped_inputs' in expressions."
            />
            <StateMapperField
              value={(config.input_mapping as any) || []}
              onChange={(val) => updateConfig('input_mapping', val)}
              graphStateFields={graphStateFields}
              currentNodeId={node.id}
            />
          </div>
        )}

        {/* Section: State Output Mapping */}
        {showAdvancedSettings && graphStateFields.length > 0 && (
          <div className="space-y-4">
            <SectionHeader
              icon={Database}
              title={t('workspace.stateUpdates', { defaultValue: 'State Updates' })}
              tooltip="Advanced: Map node outputs directly to global state variables. Useful for long-term memory across loops."
            />
            <div className="space-y-3">
              <p className="text-[10px] text-gray-400">
                Map node outputs to global state variables. Use <code>result</code> to reference the
                node&apos;s output.
              </p>
              {graphStateFields.map((field) => {
                // Access nested key for generic config update
                const currentMapping =
                  (config.output_mapping as Record<string, string>)?.[field.name] || ''

                return (
                  <div
                    key={field.name}
                    className="space-y-1.5 rounded-lg border border-gray-100 bg-gray-50/50 p-2.5"
                  >
                    <div className="flex items-center justify-between">
                      <Label className="font-mono text-[11px] font-medium text-gray-700">
                        {field.name}
                      </Label>
                      <span className="rounded border border-gray-200 bg-gray-100 px-1.5 py-0.5 text-[9px] uppercase text-gray-400">
                        {field.type}
                      </span>
                    </div>
                    {field.description && (
                      <p className="truncate text-[9px] text-gray-400">{field.description}</p>
                    )}
                    <VariableInputField
                      label=""
                      value={currentMapping}
                      onChange={(val) => {
                        const newMapping = {
                          ...((config.output_mapping as Record<string, string>) || {}),
                          [field.name]: val,
                        }
                        // If value is empty, remove the key to keep config clean
                        if (!val) {
                          delete newMapping[field.name]
                        }
                        updateConfig('output_mapping', newMapping)
                      }}
                      placeholder="e.g. result.answer"
                      nodes={nodes}
                      edges={edges}
                      currentNodeId={node.id}
                    />
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Section: State Dependencies */}
        {showAdvancedSettings && (def?.stateReads?.length || def?.stateWrites?.length) && (
          <div className="space-y-3">
            <SectionHeader
              icon={Database}
              title="State Dependencies"
              tooltip="Advanced: Shows what global state variables this node reads from or writes to. Usually managed automatically."
            />
            {def?.stateReads && def.stateReads.length > 0 && (
              <div className="space-y-1.5">
                <Label className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
                  Reads
                </Label>
                <div className="flex flex-wrap gap-1">
                  {def.stateReads.map((field) => (
                    <span
                      key={field}
                      className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 font-mono text-[9px] font-medium text-emerald-700"
                    >
                      {field === '*' ? 'all state' : field}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {def?.stateWrites && def.stateWrites.length > 0 && (
              <div className="space-y-1.5">
                <Label className="text-[10px] font-bold uppercase tracking-wider text-gray-400">
                  Writes
                </Label>
                <div className="flex flex-wrap gap-1">
                  {def.stateWrites.map((field) => (
                    <span
                      key={field}
                      className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 font-mono text-[9px] font-medium text-blue-700"
                    >
                      {field}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer Info */}
      <div className="flex items-center justify-between border-t border-gray-100 bg-gray-50 px-4 py-2 font-mono text-[9px] text-gray-400">
        <span className="truncate">TYPE: {nodeData.type}</span>
        <span className="flex items-center gap-1">
          <div className="h-1.5 w-1.5 rounded-full bg-green-500" /> {t('workspace.synced')}
        </span>
      </div>
    </div>
  )
}
