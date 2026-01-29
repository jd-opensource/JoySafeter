'use client'

import { X, AlertCircle, Settings, BrainCircuit, Hammer, Sparkles } from 'lucide-react'

import { KVListField } from './fields/KVListField'
import { VariableInputField } from './fields/VariableInputField'
import { RouteListField } from './fields/RouteListField'
import { ConditionExprField } from './fields/ConditionExprField'
import { StringArrayField } from './fields/StringArrayField'
import { DockerConfigField } from './fields/DockerConfigField'
import { nodeConfigTemplates, getTemplatesForNodeType, applyTemplate } from '../services/nodeConfigTemplates'
import { validateNodeConfig } from '../services/nodeConfigValidator'
import { cn } from '@/lib/core/utils/cn'
import { Node, Edge } from 'reactflow'
import { useTranslation } from '@/lib/i18n'
import { useParams } from 'next/navigation'
import React from 'react'
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
import { useToast } from '@/components/ui/use-toast'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'

import { nodeRegistry, FieldSchema } from '../services/nodeRegistry'
import { useBuilderStore } from '../stores/builderStore'
import { EdgeData } from '../types/graph'
import { ModelSelectField } from './fields/ModelSelectField'
import { SkillsField } from './fields/SkillsField'
import { ToolsField } from './fields/ToolsField'

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
function shouldShowField(
  field: FieldSchema,
  config: Record<string, unknown>
): boolean {
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
            'flex items-center justify-between p-2 rounded-lg border transition-all cursor-pointer select-none',
            value ? 'bg-blue-50 border-blue-200' : 'bg-gray-50 border-gray-200'
          )}
          onClick={() => onChange(!value)}
        >
          <span className="text-[11px] font-medium text-gray-700">
            {value ? t('workspace.enabled') : t('workspace.disabled')}
          </span>
          <div
            className={cn(
              'w-7 h-4 rounded-full relative transition-all border',
              value ? 'bg-blue-500 border-blue-600' : 'bg-gray-300 border-gray-400'
            )}
          >
            <div
              className={cn(
                'absolute top-[2px] w-2.5 h-2.5 bg-white rounded-full transition-all',
                value ? 'right-[2px]' : 'left-[2px]'
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
            className="resize-none min-h-[60px] text-xs py-2 focus-visible:ring-1"
          />
        )
      }
      break
    case 'select':
      input = (
        <Select value={(value as string) || ''} onValueChange={onChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder={t('workspace.selectOption', { defaultValue: 'Select option' })} />
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
        />
      )
      break
    case 'routeList':
      const outgoingEdges = edges?.filter((e) => e.source === currentNodeId) || []
      const targetNodes = nodes?.filter((n) =>
        outgoingEdges.some((e) => e.target === n.id)
      ) || []
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
      const isMemoryModel = schema.key === 'memoryModel'
      input = (
        <ModelSelectField
          value={value as string}
          onChange={(modelName) => {
            // Maintain backward compatibility: update the field itself
            onChange(modelName)
          }}
          onModelChange={(modelName, providerName) => {
            // Update both model_name and provider_name simultaneously
            if (onModelChange) {
              onModelChange(modelName, providerName)
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
      input = (
        <KVListField
          value={value as { key: string; value: string }[]}
          onChange={onChange}
        />
      )
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
      input = <div className="text-red-500 text-xs">{t('workspace.unknownFieldType', { type: schema.type, defaultValue: `Unknown field type: ${schema.type}` })}</div>
  }

  return (
    <div className="space-y-1.5 animate-in fade-in duration-200">
      <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
        {translatedLabel} {schema.required && <span className="text-red-500">*</span>}
      </Label>
      {input}
      {schema.description && (
        <p className="text-[9px] text-gray-400 leading-tight italic">{schema.description}</p>
      )}
    </div>
  )
}

const SectionHeader = ({ icon: Icon, title }: { icon: React.ElementType; title: string }) => (
  <div className="flex items-center gap-2 mb-3 mt-2">
    <Icon size={14} className="text-gray-400" />
    <h4 className="text-[11px] font-bold text-gray-500 uppercase tracking-[0.1em]">{title}</h4>
    <div className="h-[1px] flex-1 bg-gray-100 ml-1" />
  </div>
)

const PropertiesPanel: React.FC<PropertiesPanelProps> = ({
  node,
  nodes,
  edges,
  onUpdate,
  onClose,
}) => {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const { toast } = useToast()
  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)
  const { onConnect, updateEdge } = useBuilderStore()
  const nodeData = node.data as {
    type: string
    label?: string
    config?: Record<string, unknown>
  }
  const def = nodeRegistry.get(nodeData.type)

  if (!node) return null

  const config = nodeData.config || {}
  const nodeType = nodeData.type

  // Get available templates for this node type
  const templates = getTemplatesForNodeType(nodeType)

  // Validate configuration
  const validationErrors = validateNodeConfig(nodeType, config)

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
    const existingEdge = edges.find(
      (e) => e.source === node.id && e.target === targetNodeId
    )
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
      const newEdge = currentEdges.find(
        (e) => e.source === node.id && e.target === targetNodeId
      )
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
    // Update both model_name and provider_name simultaneously
    onUpdate(node.id, {
      label: nodeData.label || '',
      config: {
        ...config,
        model_name: modelName,
        provider_name: providerName,
        // Maintain backward compatibility: if field name is 'model', also update it
        model: modelName,
        provider: providerName,
      },
    })
  }

  const Icon = def?.icon || AlertCircle
  const isAgent = nodeData.type === 'agent'
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
        !(s.type === 'skillSelector' && !s.showWhen)
    ) || []
  const toolsFields = def?.schema.filter((s) => s.type === 'toolSelector') || []
  // Only show skills fields without showWhen condition in the Skills section
  // Skills with showWhen condition are shown in General section
  const skillsFields = def?.schema.filter((s) => s.type === 'skillSelector' && !s.showWhen) || []
  const memoryFields =
    def?.schema.filter((s) => ['enableMemory', 'memoryModel', 'memoryPrompt'].includes(s.key)) ||
    []
  const descriptionField = def?.schema.find((s) => s.key === 'description')

  return (
    <div className="absolute top-[56px] right-[336px] bottom-[60px] w-[400px] bg-white border border-gray-200 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right-10 fade-in duration-300 z-50">
      {/* Header */}
      <div className="px-4 py-3.5 border-b border-gray-100 flex items-center justify-between bg-white shrink-0">
        <div className="flex items-center gap-3 text-gray-900 overflow-hidden">
          <div
            className={cn(
              'p-1.5 rounded-lg border border-gray-50 shadow-sm shrink-0',
              def?.style.bg,
              def?.style.color
            )}
          >
            <Icon size={14} />
          </div>
          <div className="flex flex-col min-w-0">
            <h3 className="font-bold text-sm leading-tight truncate">
              {nodeData.label || def?.label}
            </h3>
            <span className="text-[9px] text-gray-400 uppercase tracking-widest font-bold">
              {def?.label}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-7 w-7 text-gray-300 hover:text-gray-600 hover:bg-gray-100"
          >
            <X size={16} />
          </Button>
        </div>
      </div>

      {/* Waterfall Body */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-6 pb-12">
        {/* Configuration Templates */}
        {templates.length > 0 && (
          <div className="space-y-2">
            <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
              Quick Templates
            </Label>
            <div className="space-y-1">
              {templates.map((template) => (
                <button
                  key={template.name}
                  onClick={() => applyTemplateConfig(template.name)}
                  disabled={!userPermissions.canEdit}
                  className="w-full text-left px-3 py-2 text-xs rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <div className="font-medium text-gray-900">{template.name}</div>
                  <div className="text-gray-500 mt-0.5">{template.description}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Validation Errors */}
        {validationErrors.length > 0 && (
          <div className="space-y-2">
            <Label className="text-[10px] font-bold text-red-400 uppercase tracking-wider">
              Configuration Errors
            </Label>
            <div className="space-y-1">
              {validationErrors.map((error, idx) => (
                <div key={idx} className="flex items-start gap-2 p-2 bg-red-50 border border-red-200 rounded text-xs">
                  <AlertCircle size={14} className="text-red-600 mt-0.5 flex-shrink-0" />
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
              <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
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
                />
              ))}

            {/* DeepAgents Description Field (Conditional - shown when parent has useDeepAgents=true) */}
            {hasParentWithDeepAgents && descriptionField && (
              <div className="pl-4 border-l-2 border-purple-100 space-y-1.5 animate-in slide-in-from-top-2 duration-300">
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
              />
            ))}
          </div>
        )}

        {/* Section: Skills */}
        {skillsFields.length > 0 && (
          <div className="space-y-4">
            <SectionHeader icon={Sparkles} title={t('workspace.skills', { defaultValue: 'Skills' })} />
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
                />
              ))}

            {/* Nested conditional fields */}
            {enableMemory && (
              <div className="pl-4 border-l-2 border-blue-100 space-y-4 animate-in slide-in-from-top-2 duration-300">
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
                      onModelChange={
                        field.key === 'memoryModel'
                          ? (modelName, providerName) => {
                              // Update both memoryModel and memoryProvider simultaneously
                              updateConfig('memoryModel', modelName)
                              updateConfig('memoryProvider', providerName)
                            }
                          : undefined
                      }
                    />
                  ))}
              </div>
            )}

            {!enableMemory && (
              <p className="text-[10px] text-gray-400 italic bg-gray-50 p-2 rounded-lg border border-dashed border-gray-200">
                {t('workspace.memoryDisabled')}
              </p>
            )}
          </div>
        )}

      </div>

      {/* Footer Info */}
      <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 flex items-center justify-between text-[9px] text-gray-400 font-mono">
        <span className="truncate">TYPE: {nodeData.type}</span>
        <span className="flex items-center gap-1">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> {t('workspace.synced')}
        </span>
      </div>
    </div>
  )
}

export default PropertiesPanel
