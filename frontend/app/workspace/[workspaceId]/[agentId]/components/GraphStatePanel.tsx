'use client'

import { X, Plus, Trash2, Database, AlertCircle, Pencil, Check, Copy } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useState, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
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
import { useBuilderStore } from '../stores/builderStore'
import { useExecutionStore } from '../stores/executionStore'
import { StateField, StateFieldType, ReducerType } from '../types/graph'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip'

// ─── Default value helpers ─── ────────────────────────────────
function getDefaultValueForType(type: StateFieldType): any {
    switch (type) {
        case 'string': return ''
        case 'int': return 0
        case 'float': return 0.0
        case 'bool': return false
        case 'list': return []
        case 'dict': return {}
        case 'messages': return []
        default: return ''
    }
}

function formatDefaultValue(value: any, type: StateFieldType): string {
    if (value === undefined || value === null) return ''
    if (type === 'dict' || type === 'list' || type === 'messages') {
        return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
    }
    return String(value)
}

function parseDefaultValue(raw: string, type: StateFieldType): any {
    try {
        switch (type) {
            case 'int': return parseInt(raw, 10) || 0
            case 'float': return parseFloat(raw) || 0.0
            case 'bool': return raw === 'true'
            case 'list':
            case 'dict':
            case 'messages':
                return JSON.parse(raw || (type === 'dict' ? '{}' : '[]'))
            default: return raw
        }
    } catch {
        return raw
    }
}

// ─── Component ─── ────────────────────────────────────────────
export const GraphStatePanel: React.FC = () => {
    const params = useParams()
    const workspaceId = params.workspaceId as string
    const { toast } = useToast()
    const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
    const userPermissions = useUserPermissions(permissions, permissionsLoading, null)

    const showGraphStatePanel = useBuilderStore((state) => state.showGraphStatePanel)
    const toggleGraphStatePanel = useBuilderStore((state) => state.toggleGraphStatePanel)
    const graphStateFields = useBuilderStore((state) => state.graphStateFields)
    const addStateField = useBuilderStore((state) => state.addStateField)
    const updateStateField = useBuilderStore((state) => state.updateStateField)
    const deleteStateField = useBuilderStore((state) => state.deleteStateField)
    const setHighlightedStateVariable = useBuilderStore((state) => state.setHighlightedStateVariable)

    // Execution state
    const executionState = useExecutionStore((state) => state.currentState)

    // Pull node outputs from active execution
    const executionSteps = useExecutionStore((state) => state.steps)
    const nodeOutputs = executionSteps
        .filter(s => s.stepType === 'node_lifecycle' && s.data?.payload)
        .map(s => ({
            nodeId: s.nodeId,
            nodeLabel: s.nodeLabel,
            payload: s.data?.payload
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
            toast({ title: 'Permission Denied', description: 'You do not have permission to edit.', variant: 'destructive' })
            return
        }
        if (!newField.name?.trim()) {
            toast({ title: 'Validation Error', description: 'Field name is required.', variant: 'destructive' })
            return
        }
        if (graphStateFields.some(f => f.name === newField.name)) {
            toast({ title: 'Validation Error', description: `Field "${newField.name}" already exists.`, variant: 'destructive' })
            return
        }
        if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(newField.name)) {
            toast({ title: 'Validation Error', description: 'Name must start with a letter or underscore.', variant: 'destructive' })
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
        setNewField({ name: '', type: 'string', description: '', reducer: undefined, defaultValue: undefined })
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
        const cls = compact ? "h-7 text-[11px]" : "h-8 text-xs"
        switch (type) {
            case 'bool':
                return (
                    <Select value={String(value ?? false)} onValueChange={(v) => onChange(v === 'true')} disabled={disabled}>
                        <SelectTrigger className={cls}><SelectValue /></SelectTrigger>
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
                        onChange={(e) => onChange(type === 'float' ? parseFloat(e.target.value) : parseInt(e.target.value, 10))}
                        disabled={disabled}
                        className={cls + " font-mono"}
                    />
                )
            case 'list':
            case 'dict':
            case 'messages':
                return (
                    <Textarea
                        value={formatDefaultValue(value, type)}
                        onChange={(e) => {
                            try { onChange(JSON.parse(e.target.value)) } catch { onChange(e.target.value) }
                        }}
                        disabled={disabled}
                        className="text-[11px] font-mono min-h-[48px]"
                        placeholder={type === 'dict' ? '{"key": "value"}' : '[]'}
                    />
                )
            default:
                return (
                    <Input
                        value={String(value ?? '')}
                        onChange={(e) => onChange(e.target.value)}
                        disabled={disabled}
                        className={cls + " font-mono"}
                        placeholder="Default value..."
                    />
                )
        }
    }

    return (
        <Dialog open={showGraphStatePanel} onOpenChange={(open) => !open && handleClose()}>
            <DialogContent hideCloseButton className="sm:max-w-[520px] max-h-[85vh] p-0 bg-white border border-gray-200 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
                <DialogHeader className="px-4 py-3.5 border-b border-gray-100 shrink-0 flex flex-row items-center justify-between">
                    <div className="flex items-center gap-3 text-gray-900 overflow-hidden">
                        <div className="p-1.5 rounded-lg border border-gray-50 shadow-sm shrink-0 bg-blue-50 text-blue-600">
                            <Database size={14} />
                        </div>
                        <div className="flex flex-col min-w-0">
                            <DialogTitle className="font-bold text-sm leading-tight truncate">Graph State Schema</DialogTitle>
                            <span className="text-[9px] text-gray-400 uppercase tracking-widest font-bold">
                                Global Variables & State
                            </span>
                        </div>
                    </div>
                    <Button variant="ghost" size="icon" onClick={handleClose} className="h-7 w-7 text-gray-300 hover:text-gray-600 hover:bg-gray-100 shrink-0">
                        <X size={16} />
                    </Button>
                </DialogHeader>

                {/* Body */}
                <div className="flex-1 overflow-y-auto custom-scrollbar p-0 flex flex-col">
                    <Tabs defaultValue="global" className="flex-1 flex flex-col">
                        <div className="px-4 pt-2 border-b border-gray-100">
                            <TabsList className="grid w-full grid-cols-3">
                                <TabsTrigger value="global">State Fields</TabsTrigger>
                                <TabsTrigger value="execution">Execution State</TabsTrigger>
                                <TabsTrigger value="local">Node Outputs</TabsTrigger>
                            </TabsList>
                        </div>

                        {/* ═══ Tab 1: State Fields ═══ */}
                        <TabsContent value="global" className="flex-1 overflow-y-auto p-4 space-y-4 m-0 border-0 focus-visible:outline-none focus-visible:ring-0">
                            {/* Info Banner */}
                            <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-800">
                                <div className="flex items-start gap-2">
                                    <AlertCircle size={14} className="mt-0.5 shrink-0" />
                                    <div>
                                        <div className="font-medium mb-1">Global State Variables</div>
                                        <p className="text-blue-600">
                                            Define variables that persist across node executions. Access via{' '}
                                            <code className="bg-blue-100 px-1 rounded">state.get(&apos;name&apos;)</code>{' '}
                                            or{' '}
                                            <code className="bg-blue-100 px-1 rounded">state.name</code>{' '}
                                            in expressions and Data Pills.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            {/* Existing Fields */}
                            {graphStateFields.length > 0 && (
                                <div className="space-y-2">
                                    <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
                                        Defined Fields ({graphStateFields.length})
                                    </Label>
                                    <div className="space-y-2">
                                        {graphStateFields.map((field) => {
                                            const isEditing = editingFieldName === field.name
                                            return (
                                                <div
                                                    key={field.name}
                                                    className="border border-gray-200 rounded-lg p-3 bg-gray-50/50 space-y-2 hover:border-blue-300 hover:bg-blue-50/30 transition-colors"
                                                    onMouseEnter={() => setHighlightedStateVariable(field.name)}
                                                    onMouseLeave={() => setHighlightedStateVariable(null)}
                                                >
                                                    {/* Header row */}
                                                    <div className="flex items-center justify-between">
                                                        <div className="flex items-center gap-2 flex-wrap">
                                                            <code className="text-xs font-mono font-medium text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">
                                                                {field.name}
                                                            </code>
                                                            <span className="text-[9px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded uppercase border border-gray-200">
                                                                {field.type}
                                                            </span>
                                                            {field.reducer && (
                                                                <span className="text-[9px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded uppercase border border-amber-100">
                                                                    {field.reducer}
                                                                </span>
                                                            )}
                                                        </div>
                                                        <div className="flex items-center gap-0.5">
                                                            {isEditing ? (
                                                                <Button variant="ghost" size="icon" onClick={saveEditing} className="h-6 w-6 text-green-500 hover:text-green-700">
                                                                    <Check size={12} />
                                                                </Button>
                                                            ) : (
                                                                <Button variant="ghost" size="icon" onClick={() => startEditing(field)} disabled={!userPermissions.canEdit || field.isSystem} className="h-6 w-6 text-gray-400 hover:text-blue-500">
                                                                    <Pencil size={12} />
                                                                </Button>
                                                            )}
                                                            <Button variant="ghost" size="icon" onClick={() => deleteStateField(field.name)} disabled={!userPermissions.canEdit || field.isSystem} className="h-6 w-6 text-gray-400 hover:text-red-500">
                                                                <Trash2 size={12} />
                                                            </Button>
                                                        </div>
                                                    </div>

                                                    {/* Description */}
                                                    {isEditing ? (
                                                        <Input
                                                            value={editValues.description || ''}
                                                            onChange={(e) => setEditValues({ ...editValues, description: e.target.value })}
                                                            className="h-7 text-[11px]"
                                                            placeholder="Description..."
                                                        />
                                                    ) : field.description ? (
                                                        <p className="text-[10px] text-gray-500">{field.description}</p>
                                                    ) : null}

                                                    {/* Default Value */}
                                                    {isEditing ? (
                                                        <div className="space-y-1">
                                                            <Label className="text-[9px] font-bold text-gray-400">Default Value</Label>
                                                            {renderDefaultValueInput(
                                                                editValues.defaultValue ?? field.defaultValue,
                                                                field.type,
                                                                (val) => setEditValues({ ...editValues, defaultValue: val }),
                                                                false,
                                                                true,
                                                            )}
                                                        </div>
                                                    ) : field.defaultValue !== undefined && field.defaultValue !== null && field.defaultValue !== '' ? (
                                                        <div className="text-[10px] text-gray-500 font-mono bg-white px-2 py-1 rounded border border-gray-100">
                                                            <span className="text-gray-400">default: </span>
                                                            {formatDefaultValue(field.defaultValue, field.type)}
                                                        </div>
                                                    ) : null}

                                                    {/* Reducer (inline edit) */}
                                                    {isEditing && (
                                                        <div className="space-y-1">
                                                            <Label className="text-[9px] font-bold text-gray-400">Reducer</Label>
                                                            <Select
                                                                value={editValues.reducer || 'none'}
                                                                onValueChange={(v) => setEditValues({ ...editValues, reducer: v === 'none' ? undefined : v as ReducerType })}
                                                            >
                                                                <SelectTrigger className="h-7 text-[11px]"><SelectValue /></SelectTrigger>
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
                                                                    className="w-full text-left text-[9px] text-gray-400 font-mono bg-white px-2 py-1 rounded border border-gray-100 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-600 transition-colors flex items-center justify-between group"
                                                                >
                                                                    <span>state.get(&apos;{field.name}&apos;)</span>
                                                                    <Copy size={10} className="opacity-0 group-hover:opacity-100 transition-opacity" />
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
                            <div className="space-y-3 border border-dashed border-gray-300 rounded-lg p-3 bg-white">
                                <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
                                    <Plus size={12} />
                                    Add New State Field
                                </Label>

                                <div className="grid grid-cols-2 gap-2">
                                    <div className="space-y-1">
                                        <Label className="text-[9px] font-bold text-gray-400">Field Name</Label>
                                        <Input
                                            value={newField.name}
                                            onChange={(e) => setNewField({ ...newField, name: e.target.value })}
                                            placeholder="e.g., user_score"
                                            disabled={!userPermissions.canEdit}
                                            className="h-8 text-xs font-mono"
                                        />
                                    </div>
                                    <div className="space-y-1">
                                        <Label className="text-[9px] font-bold text-gray-400">Type</Label>
                                        <Select
                                            value={newField.type}
                                            onValueChange={(v) => setNewField({ ...newField, type: v as StateFieldType, defaultValue: getDefaultValueForType(v as StateFieldType) })}
                                            disabled={!userPermissions.canEdit}
                                        >
                                            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
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
                                    <Label className="text-[9px] font-bold text-gray-400">Default Value</Label>
                                    {renderDefaultValueInput(
                                        newField.defaultValue ?? getDefaultValueForType((newField.type || 'string') as StateFieldType),
                                        (newField.type || 'string') as StateFieldType,
                                        (val) => setNewField({ ...newField, defaultValue: val }),
                                        !userPermissions.canEdit,
                                    )}
                                </div>

                                <div className="space-y-1">
                                    <Label className="text-[9px] font-bold text-gray-400">Reducer (Optional)</Label>
                                    <Select
                                        value={newField.reducer || 'none'}
                                        onValueChange={(v) => setNewField({ ...newField, reducer: v === 'none' ? undefined : v as ReducerType })}
                                        disabled={!userPermissions.canEdit}
                                    >
                                        <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="No Reducer" /></SelectTrigger>
                                        <SelectContent className="z-[10000001]">
                                            <SelectItem value="none">No Reducer (Overwrite)</SelectItem>
                                            <SelectItem value="add">Add (+)</SelectItem>
                                            <SelectItem value="append">Append (List)</SelectItem>
                                            <SelectItem value="merge">Merge (Dict)</SelectItem>
                                        </SelectContent>
                                    </Select>
                                    <p className="text-[9px] text-gray-400">
                                        Determines how new values are merged with existing state.
                                    </p>
                                </div>

                                <div className="space-y-1">
                                    <Label className="text-[9px] font-bold text-gray-400">Description</Label>
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
                                    className="w-full h-8 text-xs"
                                >
                                    <Plus size={12} className="mr-1" />
                                    Add Field
                                </Button>
                            </div>

                            {/* Empty state */}
                            {graphStateFields.length === 0 && (
                                <div className="text-center py-6 text-gray-400">
                                    <Database size={32} className="mx-auto mb-2 opacity-30" />
                                    <p className="text-xs">No state fields defined yet.</p>
                                    <p className="text-[9px] mt-1">Add variables to share data across nodes.</p>
                                </div>
                            )}
                        </TabsContent>

                        {/* ═══ Tab 2: Execution State ═══ */}
                        <TabsContent value="execution" className="flex-1 overflow-y-auto p-4 space-y-4 m-0 border-0 focus-visible:outline-none focus-visible:ring-0">
                            <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-xs text-green-800">
                                <div className="flex items-start gap-2">
                                    <Database size={14} className="mt-0.5 shrink-0" />
                                    <div>
                                        <div className="font-medium mb-1">Active Global State</div>
                                        <p className="text-green-600">
                                            Current runtime values of all global state variables.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            {!executionState || Object.keys(executionState).length === 0 ? (
                                <div className="text-center text-gray-500 text-sm py-8 italic border border-dashed rounded-lg">
                                    Graph is not running or state is empty.
                                </div>
                            ) : (
                                <div className="border border-gray-200 rounded-lg overflow-hidden flex flex-col bg-white">
                                    <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                                        <div className="font-mono text-xs text-green-700 font-bold flex items-center gap-1.5">
                                            Current State Variables
                                        </div>
                                    </div>
                                    <pre className="text-gray-700 text-sm p-3 overflow-x-auto whitespace-pre-wrap">
                                        <code>{JSON.stringify(executionState, null, 2)}</code>
                                    </pre>
                                </div>
                            )}
                        </TabsContent>

                        {/* ═══ Tab 3: Local Node Outputs ═══ */}
                        <TabsContent value="local" className="flex-1 overflow-y-auto p-4 space-y-4 m-0 border-0 focus-visible:outline-none focus-visible:ring-0">
                            <div className="p-3 bg-purple-50 border border-purple-200 rounded-lg text-xs text-purple-800">
                                <div className="flex items-start gap-2">
                                    <Database size={14} className="mt-0.5 shrink-0" />
                                    <div>
                                        <div className="font-medium mb-1">Local Node Outputs (Testing)</div>
                                        <p className="text-purple-600">
                                            Values produced by executed nodes. Reference via <code>{`{NodeId.output}`}</code>.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            {nodeOutputs.length === 0 ? (
                                <div className="text-center text-gray-500 text-sm py-8 italic border border-dashed rounded-lg">
                                    No node outputs recorded yet. Run the graph to see data!
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    {nodeOutputs.map((output, i) => (
                                        <div key={`${output.nodeId}-${i}`} className="border border-gray-200 rounded-lg overflow-hidden flex flex-col bg-white">
                                            <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                                                <div className="font-mono text-xs text-purple-700 font-bold flex items-center gap-1.5">
                                                    <span className="text-gray-400">node:</span> {output.nodeLabel || output.nodeId}
                                                </div>
                                            </div>
                                            <pre className="text-gray-700 whitespace-pre-wrap">
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
                <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 flex items-center justify-between text-[9px] text-gray-400 font-mono">
                    <span>{graphStateFields.length} field{graphStateFields.length !== 1 ? 's' : ''} defined</span>
                    <span className="flex items-center gap-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> Auto-saved
                    </span>
                </div>
            </DialogContent>
        </Dialog>
    )
}
