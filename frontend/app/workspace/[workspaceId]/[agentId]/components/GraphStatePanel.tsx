'use client'

import { X, Plus, Trash2, Database, AlertCircle, Pencil, Check, Copy } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/components/ui/use-toast'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'

import { useBuilderStore } from '../stores/builderStore'
import { useExecutionStore } from '../stores/executionStore'
import { StateField, StateFieldType, ReducerType } from '../types/graph'

// ─── Default value helpers ─── ────────────────────────────────
function getDefaultValueForType(type: StateFieldType): any {
  switch (type) {
    case 'string':
      return ''
    case 'int':
      return 0
    case 'float':
      return 0.0
    case 'bool':
      return false
    case 'list':
      return []
    case 'dict':
      return {}
    case 'messages':
      return []
    default:
      return ''
  }
}

function formatDefaultValue(value: any, type: StateFieldType): string {
  if (value === undefined || value === null) return ''
  if (type === 'dict' || type === 'list' || type === 'messages') {
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  }
  return String(value)
}

// ─── Component ─── ────────────────────────────────────────────
export function GraphStatePanel() {
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const { toast } = useToast()
  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)

  const showGraphStatePanel = useBuilderStore((state) => state.showGraphStatePanel)
  const toggleGraphStatePanel = useBuilderStore((state) => state.toggleGraphStatePanel)
  const nodes = useBuilderStore((state) => state.nodes)
  const graphStateFields = useBuilderStore((state) => state.graphStateFields)
  const fallbackNodeId = useBuilderStore((state) => state.fallbackNodeId)
  const setFallbackNodeId = useBuilderStore((state) => state.setFallbackNodeId)
  const addStateField = useBuilderStore((state) => state.addStateField)
  const updateStateField = useBuilderStore((state) => state.updateStateField)
  const deleteStateField = useBuilderStore((state) => state.deleteStateField)
  const setHighlightedStateVariable = useBuilderStore((state) => state.setHighlightedStateVariable)

  // Execution state
  const executionState = useExecutionStore((state) => state.currentState)

  // Pull node outputs from active execution
  const executionSteps = useExecutionStore((state) => state.steps)
  const nodeOutputs = executionSteps
    .filter((s) => s.stepType === 'node_lifecycle' && s.data?.payload)
    .map((s) => ({
      nodeId: s.nodeId,
      nodeLabel: s.nodeLabel,
      payload: s.data?.payload,
    }))

  // Local state for new field
  const [newField, setNewField] = useState<Partial<StateField>>({
    name: '',
    type: 'string',
    description: '',
    reducer: undefined,
    defaultValue: undefined,
  })

  // Inline editing state
  const [editingFieldName, setEditingFieldName] = useState<string | null>(null)
  const [editValues, setEditValues] = useState<Partial<StateField>>({})

  // Add new field
  const handleAddField = useCallback(() => {
    if (!userPermissions.canEdit) {
      toast({
        title: 'Permission Denied',
        description: 'You do not have permission to edit.',
        variant: 'destructive',
      })
      return
    }
    if (!newField.name?.trim()) {
      toast({
        title: 'Validation Error',
        description: 'Field name is required.',
        variant: 'destructive',
      })
      return
    }
    if (graphStateFields.some((f) => f.name === newField.name)) {
      toast({
        title: 'Validation Error',
        description: `Field "${newField.name}" already exists.`,
        variant: 'destructive',
      })
      return
    }
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(newField.name)) {
      toast({
        title: 'Validation Error',
        description: 'Name must start with a letter or underscore.',
        variant: 'destructive',
      })
      return
    }

    const fieldType = (newField.type || 'string') as StateFieldType
    addStateField({
      name: newField.name,
      type: fieldType,
      description: newField.description,
      reducer: newField.reducer as ReducerType | undefined,
      defaultValue: newField.defaultValue ?? getDefaultValueForType(fieldType),
    })
    setNewField({
      name: '',
      type: 'string',
      description: '',
      reducer: undefined,
      defaultValue: undefined,
    })
  }, [newField, graphStateFields, userPermissions.canEdit, addStateField, toast])

  // Start inline editing
  const startEditing = (field: StateField) => {
    setEditingFieldName(field.name)
    setEditValues({
      description: field.description || '',
      defaultValue: field.defaultValue,
      reducer: field.reducer,
    })
  }

  // Save inline editing
  const saveEditing = () => {
    if (editingFieldName) {
      updateStateField(editingFieldName, editValues)
      setEditingFieldName(null)
      setEditValues({})
    }
  }

  // Copy usage snippet
  const copyUsage = (fieldName: string) => {
    navigator.clipboard.writeText(`state.get('${fieldName}')`)
    toast({ title: 'Copied!', description: `state.get('${fieldName}') copied to clipboard.` })
  }

  const handleClose = () => toggleGraphStatePanel(false)

  // Default value input
  const renderDefaultValueInput = (
    value: any,
    type: StateFieldType,
    onChange: (val: any) => void,
    disabled: boolean = false,
    compact: boolean = false,
  ) => {
    const cls = compact ? 'h-7 text-[11px]' : 'h-8 text-xs'
    switch (type) {
      case 'bool':
        return (
          <Select
            value={String(value ?? false)}
            onValueChange={(v) => onChange(v === 'true')}
            disabled={disabled}
          >
            <SelectTrigger className={cls}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="z-[10000001]">
              <SelectItem value="true">true</SelectItem>
              <SelectItem value="false">false</SelectItem>
            </SelectContent>
          </Select>
        )
      case 'int':
      case 'float':
        return (
          <Input
            type="number"
            step={type === 'float' ? '0.01' : '1'}
            value={value ?? 0}
            onChange={(e) =>
              onChange(type === 'float' ? parseFloat(e.target.value) : parseInt(e.target.value, 10))
            }
            disabled={disabled}
            className={cls + ' font-mono'}
          />
        )
      case 'list':
      case 'dict':
      case 'messages':
        return (
          <Textarea
            value={formatDefaultValue(value, type)}
            onChange={(e) => {
              try {
                onChange(JSON.parse(e.target.value))
              } catch {
                onChange(e.target.value)
              }
            }}
            disabled={disabled}
            className="min-h-[48px] font-mono text-[11px]"
            placeholder={type === 'dict' ? '{"key": "value"}' : '[]'}
          />
        )
      default:
        return (
          <Input
            value={String(value ?? '')}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            className={cls + ' font-mono'}
            placeholder="Default value..."
          />
        )
    }
  }

  return (
    <Dialog open={showGraphStatePanel} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent
        hideCloseButton
        className="flex max-h-[85vh] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] p-0 shadow-2xl sm:max-w-[520px]"
      >
        <DialogHeader className="flex shrink-0 flex-row items-center justify-between border-b border-[var(--border-muted)] px-4 py-3.5">
          <div className="flex items-center gap-3 overflow-hidden text-[var(--text-primary)]">
            <div className="shrink-0 rounded-lg border border-[var(--border)] bg-primary/5 p-1.5 text-primary shadow-sm">
              <Database size={14} />
            </div>
            <div className="flex min-w-0 flex-col">
              <DialogTitle className="truncate text-sm font-bold leading-tight">
                Graph State Schema
              </DialogTitle>
              <span className="text-[9px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                Global Variables & State
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleClose}
            className="h-7 w-7 shrink-0 text-[var(--text-disabled)] hover:bg-[var(--surface-2)] hover:text-[var(--text-secondary)]"
          >
            <X size={16} />
          </Button>
        </DialogHeader>

        {/* Body */}
        <div className="custom-scrollbar flex flex-1 flex-col overflow-y-auto p-0">
          <Tabs defaultValue="global" className="flex flex-1 flex-col">
            <div className="border-b border-[var(--border-muted)] px-4 pt-2">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="global">State Fields</TabsTrigger>
                <TabsTrigger value="execution">Execution State</TabsTrigger>
                <TabsTrigger value="local">Node Outputs</TabsTrigger>
              </TabsList>
            </div>

            {/* ═══ Tab 1: State Fields ═══ */}
            <TabsContent
              value="global"
              className="m-0 flex-1 space-y-4 overflow-y-auto border-0 p-4 focus-visible:outline-none focus-visible:ring-0"
            >
              {/* Fallback node (global error handler) */}
              <div className="space-y-1.5">
                <Label className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                  Global error handler (fallback node)
                </Label>
                <Select
                  value={fallbackNodeId || '__none__'}
                  onValueChange={(v) => setFallbackNodeId(v === '__none__' ? null : v)}
                  disabled={!userPermissions.canEdit}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__" className="text-xs">
                      None
                    </SelectItem>
                    {nodes.map((n) => (
                      <SelectItem key={n.id} value={n.id} className="text-xs">
                        {(n.data as { label?: string })?.label || n.id.slice(0, 8)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[9px] text-[var(--text-muted)]">
                  On node error, execution jumps to this node when set.
                </p>
              </div>

              {/* Info Banner */}
              <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs text-[var(--text-primary)]">
                <div className="flex items-start gap-2">
                  <AlertCircle size={14} className="mt-0.5 shrink-0" />
                  <div>
                    <div className="mb-1 font-medium">Global State Variables</div>
                    <p className="text-[var(--text-secondary)]">
                      Define variables that persist across node executions. Access via{' '}
                      <code className="rounded bg-primary/10 px-1">state.get(&apos;name&apos;)</code>{' '}
                      or <code className="rounded bg-primary/10 px-1">state.name</code> in expressions
                      and Data Pills.
                    </p>
                  </div>
                </div>
              </div>

              {/* Existing Fields */}
              {graphStateFields.length > 0 && (
                <div className="space-y-2">
                  <Label className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                    Defined Fields ({graphStateFields.length})
                  </Label>
                  <div className="space-y-2">
                    {graphStateFields.map((field) => {
                      const isEditing = editingFieldName === field.name
                      return (
                        <div
                          key={field.name}
                          className="space-y-2 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-3 transition-colors hover:border-primary/30 hover:bg-primary/5"
                          onMouseEnter={() => setHighlightedStateVariable(field.name)}
                          onMouseLeave={() => setHighlightedStateVariable(null)}
                        >
                          {/* Header row */}
                          <div className="flex items-center justify-between">
                            <div className="flex flex-wrap items-center gap-2">
                              <code className="rounded bg-primary/5 px-1.5 py-0.5 font-mono text-xs font-medium text-primary">
                                {field.name}
                              </code>
                              <span className="rounded border border-[var(--border)] bg-[var(--surface-3)] px-1.5 py-0.5 text-[9px] uppercase text-[var(--text-muted)]">
                                {field.type}
                              </span>
                              {field.reducer && (
                                <span className="rounded border border-amber-100 bg-amber-50 px-1.5 py-0.5 text-[9px] uppercase text-amber-600">
                                  {field.reducer}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-0.5">
                              {isEditing ? (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={saveEditing}
                                  className="h-6 w-6 text-green-500 hover:text-green-700"
                                >
                                  <Check size={12} />
                                </Button>
                              ) : (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => startEditing(field)}
                                  disabled={!userPermissions.canEdit || field.isSystem}
                                  className="h-6 w-6 text-[var(--text-muted)] hover:text-primary"
                                >
                                  <Pencil size={12} />
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => deleteStateField(field.name)}
                                disabled={!userPermissions.canEdit || field.isSystem}
                                className="h-6 w-6 text-[var(--text-muted)] hover:text-[var(--status-error)]"
                              >
                                <Trash2 size={12} />
                              </Button>
                            </div>
                          </div>

                          {/* Description */}
                          {isEditing ? (
                            <Input
                              value={editValues.description || ''}
                              onChange={(e) =>
                                setEditValues({ ...editValues, description: e.target.value })
                              }
                              className="h-7 text-[11px]"
                              placeholder="Description..."
                            />
                          ) : field.description ? (
                            <p className="text-[10px] text-[var(--text-tertiary)]">{field.description}</p>
                          ) : null}

                          {/* Default Value */}
                          {isEditing ? (
                            <div className="space-y-1">
                              <Label className="text-[9px] font-bold text-[var(--text-muted)]">
                                Default Value
                              </Label>
                              {renderDefaultValueInput(
                                editValues.defaultValue ?? field.defaultValue,
                                field.type,
                                (val) => setEditValues({ ...editValues, defaultValue: val }),
                                false,
                                true,
                              )}
                            </div>
                          ) : field.defaultValue !== undefined &&
                            field.defaultValue !== null &&
                            field.defaultValue !== '' ? (
                            <div className="rounded border border-[var(--border-muted)] bg-[var(--surface-elevated)] px-2 py-1 font-mono text-[10px] text-[var(--text-tertiary)]">
                              <span className="text-[var(--text-muted)]">default: </span>
                              {formatDefaultValue(field.defaultValue, field.type)}
                            </div>
                          ) : null}

                          {/* Reducer (inline edit) */}
                          {isEditing && (
                            <div className="space-y-1">
                              <Label className="text-[9px] font-bold text-[var(--text-muted)]">Reducer</Label>
                              <Select
                                value={editValues.reducer || 'none'}
                                onValueChange={(v) =>
                                  setEditValues({
                                    ...editValues,
                                    reducer: v === 'none' ? undefined : (v as ReducerType),
                                  })
                                }
                              >
                                <SelectTrigger className="h-7 text-[11px]">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent className="z-[10000001]">
                                  <SelectItem value="none">No Reducer (Overwrite)</SelectItem>
                                  <SelectItem value="add">Add (+)</SelectItem>
                                  <SelectItem value="append">Append (List)</SelectItem>
                                  <SelectItem value="merge">Merge (Dict)</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                          )}

                          {/* Usage Hint */}
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <button
                                  onClick={() => copyUsage(field.name)}
                                  className="group flex w-full items-center justify-between rounded border border-[var(--border-muted)] bg-[var(--surface-elevated)] px-2 py-1 text-left font-mono text-[9px] text-[var(--text-muted)] transition-colors hover:border-primary/20 hover:bg-primary/5 hover:text-primary"
                                >
                                  <span>state.get(&apos;{field.name}&apos;)</span>
                                  <Copy
                                    size={10}
                                    className="opacity-0 transition-opacity group-hover:opacity-100"
                                  />
                                </button>
                              </TooltipTrigger>
                              <TooltipContent side="bottom" className="text-[10px]">
                                Click to copy usage snippet
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Add New Field */}
              <div className="space-y-3 rounded-lg border border-dashed border-[var(--border-strong)] bg-[var(--surface-elevated)] p-3">
                <Label className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                  <Plus size={12} />
                  Add New State Field
                </Label>

                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-[9px] font-bold text-[var(--text-muted)]">Field Name</Label>
                    <Input
                      value={newField.name}
                      onChange={(e) => setNewField({ ...newField, name: e.target.value })}
                      placeholder="e.g., user_score"
                      disabled={!userPermissions.canEdit}
                      className="h-8 font-mono text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-[9px] font-bold text-[var(--text-muted)]">Type</Label>
                    <Select
                      value={newField.type}
                      onValueChange={(v) =>
                        setNewField({
                          ...newField,
                          type: v as StateFieldType,
                          defaultValue: getDefaultValueForType(v as StateFieldType),
                        })
                      }
                      disabled={!userPermissions.canEdit}
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="z-[10000001]">
                        <SelectItem value="string">string</SelectItem>
                        <SelectItem value="int">int</SelectItem>
                        <SelectItem value="float">float</SelectItem>
                        <SelectItem value="bool">bool</SelectItem>
                        <SelectItem value="list">list</SelectItem>
                        <SelectItem value="dict">dict</SelectItem>
                        <SelectItem value="messages">messages</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="space-y-1">
                  <Label className="text-[9px] font-bold text-[var(--text-muted)]">Default Value</Label>
                  {renderDefaultValueInput(
                    newField.defaultValue ??
                      getDefaultValueForType((newField.type || 'string') as StateFieldType),
                    (newField.type || 'string') as StateFieldType,
                    (val) => setNewField({ ...newField, defaultValue: val }),
                    !userPermissions.canEdit,
                  )}
                </div>

                <div className="space-y-1">
                  <Label className="text-[9px] font-bold text-[var(--text-muted)]">Reducer (Optional)</Label>
                  <Select
                    value={newField.reducer || 'none'}
                    onValueChange={(v) =>
                      setNewField({
                        ...newField,
                        reducer: v === 'none' ? undefined : (v as ReducerType),
                      })
                    }
                    disabled={!userPermissions.canEdit}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="No Reducer" />
                    </SelectTrigger>
                    <SelectContent className="z-[10000001]">
                      <SelectItem value="none">No Reducer (Overwrite)</SelectItem>
                      <SelectItem value="add">Add (+)</SelectItem>
                      <SelectItem value="append">Append (List)</SelectItem>
                      <SelectItem value="merge">Merge (Dict)</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-[9px] text-[var(--text-muted)]">
                    Determines how new values are merged with existing state.
                  </p>
                </div>

                <div className="space-y-1">
                  <Label className="text-[9px] font-bold text-[var(--text-muted)]">Description</Label>
                  <Input
                    value={newField.description || ''}
                    onChange={(e) => setNewField({ ...newField, description: e.target.value })}
                    placeholder="Description of this state variable..."
                    disabled={!userPermissions.canEdit}
                    className="h-8 text-xs"
                  />
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleAddField}
                  disabled={!userPermissions.canEdit || !newField.name?.trim()}
                  className="h-8 w-full text-xs"
                >
                  <Plus size={12} className="mr-1" />
                  Add Field
                </Button>
              </div>

              {/* Empty state */}
              {graphStateFields.length === 0 && (
                <div className="py-6 text-center text-[var(--text-muted)]">
                  <Database size={32} className="mx-auto mb-2 opacity-30" />
                  <p className="text-xs">No state fields defined yet.</p>
                  <p className="mt-1 text-[9px]">Add variables to share data across nodes.</p>
                </div>
              )}
            </TabsContent>

            {/* ═══ Tab 2: Execution State ═══ */}
            <TabsContent
              value="execution"
              className="m-0 flex-1 space-y-4 overflow-y-auto border-0 p-4 focus-visible:outline-none focus-visible:ring-0"
            >
              <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-xs text-green-800">
                <div className="flex items-start gap-2">
                  <Database size={14} className="mt-0.5 shrink-0" />
                  <div>
                    <div className="mb-1 font-medium">Active Global State</div>
                    <p className="text-green-600">
                      Current runtime values of all global state variables.
                    </p>
                  </div>
                </div>
              </div>

              {!executionState || Object.keys(executionState).length === 0 ? (
                <div className="rounded-lg border border-dashed py-8 text-center text-sm italic text-[var(--text-tertiary)]">
                  Graph is not running or state is empty.
                </div>
              ) : (
                <div className="flex flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]">
                  <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-2)] px-3 py-2">
                    <div className="flex items-center gap-1.5 font-mono text-xs font-bold text-green-700">
                      Current State Variables
                    </div>
                  </div>
                  <pre className="overflow-x-auto whitespace-pre-wrap p-3 text-sm text-[var(--text-secondary)]">
                    <code>{JSON.stringify(executionState, null, 2)}</code>
                  </pre>
                </div>
              )}
            </TabsContent>

            {/* ═══ Tab 3: Local Node Outputs ═══ */}
            <TabsContent
              value="local"
              className="m-0 flex-1 space-y-4 overflow-y-auto border-0 p-4 focus-visible:outline-none focus-visible:ring-0"
            >
              <div className="rounded-lg border border-purple-200 bg-purple-50 p-3 text-xs text-purple-800">
                <div className="flex items-start gap-2">
                  <Database size={14} className="mt-0.5 shrink-0" />
                  <div>
                    <div className="mb-1 font-medium">Local Node Outputs (Testing)</div>
                    <p className="text-purple-600">
                      Values produced by executed nodes. Reference via{' '}
                      <code>{`{NodeId.output}`}</code>.
                    </p>
                  </div>
                </div>
              </div>

              {nodeOutputs.length === 0 ? (
                <div className="rounded-lg border border-dashed py-8 text-center text-sm italic text-[var(--text-tertiary)]">
                  No node outputs recorded yet. Run the graph to see data!
                </div>
              ) : (
                <div className="space-y-4">
                  {nodeOutputs.map((output, i) => (
                    <div
                      key={`${output.nodeId}-${i}`}
                      className="flex flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]"
                    >
                      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-2)] px-3 py-2">
                        <div className="flex items-center gap-1.5 font-mono text-xs font-bold text-purple-700">
                          <span className="text-[var(--text-muted)]">node:</span>{' '}
                          {output.nodeLabel || output.nodeId}
                        </div>
                      </div>
                      <pre className="whitespace-pre-wrap text-[var(--text-secondary)]">
                        <code>{JSON.stringify(output.payload, null, 2)}</code>
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-[var(--border-muted)] bg-[var(--surface-2)] px-4 py-2 font-mono text-[9px] text-[var(--text-muted)]">
          <span>
            {graphStateFields.length} field{graphStateFields.length !== 1 ? 's' : ''} defined
          </span>
          <span className="flex items-center gap-1">
            <div className="h-1.5 w-1.5 rounded-full bg-green-500" /> Auto-saved
          </span>
        </div>
      </DialogContent>
    </Dialog>
  )
}
