'use client'

import { Trash2, Plus, ArrowRight, Variable, Type } from 'lucide-react'
import React from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/core/utils/cn'
import { useBuilderStore } from '../../stores/builderStore'
import { StateField } from '../../types/graph'
import type { Node } from 'reactflow'

interface StateMapperFieldProps {
    value: Record<string, string> | { key: string; value: string }[]
    onChange: (val: { key: string; value: string }[]) => void
    graphStateFields?: StateField[]
    // Can optionally provide current node ID to filter out downstream nodes, though for now we can just list all nodes
    currentNodeId?: string
}

type MappingMode = 'static' | 'variable' | 'upstream_output'

interface MappingItem {
    key: string
    value: string
    mode: MappingMode
}

export const StateMapperField: React.FC<StateMapperFieldProps> = ({
    value,
    onChange,
    graphStateFields = [],
    currentNodeId,
}) => {
    const { t } = useTranslation()
    const nodes = useBuilderStore(state => state.nodes)

    // Convert input value to internal state format
    const items: MappingItem[] = React.useMemo(() => {
        let rawItems: { key: string; value: string }[] = []

        if (Array.isArray(value)) {
            rawItems = value
        } else if (typeof value === 'object' && value !== null) {
            rawItems = Object.entries(value).map(([k, v]) => ({ key: k, value: String(v) }))
        }

        return rawItems.map(item => {
            // Heuristic to detect mode:
            // 1. state.get('node_outputs.node_id.path') -> upstream_output
            // 2. state.get('var') -> variable
            // 3. else -> static
            const match = item.value.match(/^state\.get\(['"](.+)['"]\)$/)
            if (match) {
                const innerValue = match[1]
                if (innerValue.startsWith('node_outputs.')) {
                    // Extract the part after node_outputs.
                    const nodeOutputPath = innerValue.substring('node_outputs.'.length)
                    return { key: item.key, value: nodeOutputPath, mode: 'upstream_output' }
                }
                return { key: item.key, value: innerValue, mode: 'variable' }
            }
            return { key: item.key, value: item.value, mode: 'static' }
        })
    }, [value])

    const handleChange = (index: number, field: keyof MappingItem, newValue: string) => {
        const newItems = [...items]
        newItems[index] = { ...newItems[index], [field]: newValue }
        emitChange(newItems)
    }

    const toggleMode = (index: number) => {
        const newItems = [...items]
        const currentMode = newItems[index].mode

        let nextMode: MappingMode = 'static'
        if (currentMode === 'static') nextMode = 'variable'
        else if (currentMode === 'variable') nextMode = 'upstream_output'
        else nextMode = 'static'

        newItems[index] = {
            ...newItems[index],
            mode: nextMode,
            value: '' // Clear value on mode switch to avoid confusion
        }
        emitChange(newItems)
    }

    const emitChange = (newItems: MappingItem[]) => {
        // Transform back to code format
        const output = newItems.map(item => {
            if (item.mode === 'variable' && item.value) {
                return { key: item.key, value: `state.get('${item.value}')` }
            }
            if (item.mode === 'upstream_output' && item.value) {
                return { key: item.key, value: `state.get('node_outputs.${item.value}')` }
            }
            return { key: item.key, value: item.value }
        })
        onChange(output)
    }

    const handleAdd = () => {
        emitChange([...items, { key: '', value: '', mode: 'static' }])
    }

    const handleRemove = (index: number) => {
        const newItems = [...items]
        newItems.splice(index, 1)
        emitChange(newItems)
    }

    return (
        <div className="space-y-2 border border-gray-200 rounded-xl p-3 bg-gray-50/30">
            {items.length === 0 && (
                <div className="text-[10px] text-gray-400 text-center py-2">
                    {t('workspace.noParametersDefined', { defaultValue: 'No parameters defined' })}
                </div>
            )}

            <div className="space-y-2">
                {items.map((item, index) => (
                    <div key={index} className="flex gap-2 items-start group">
                        {/* Param Name */}
                        <div className="flex-1">
                            <Input
                                value={item.key}
                                onChange={(e) => handleChange(index, 'key', e.target.value)}
                                placeholder="Parameter Name"
                                className="h-8 text-xs bg-white font-mono"
                            />
                        </div>

                        <ArrowRight size={12} className="text-gray-300 mt-2.5 shrink-0" />

                        {/* Value Input */}
                        <div className="flex-[1.5] relative flex gap-1">
                            {/* Mode Toggle */}
                            <button
                                onClick={() => toggleMode(index)}
                                className={cn(
                                    "h-8 w-6 flex items-center justify-center rounded border transition-colors shrink-0",
                                    item.mode === 'static' && "bg-gray-100 border-gray-200 text-gray-500 hover:bg-gray-200",
                                    item.mode === 'variable' && "bg-blue-50 border-blue-200 text-blue-600 hover:bg-blue-100",
                                    item.mode === 'upstream_output' && "bg-purple-50 border-purple-200 text-purple-600 hover:bg-purple-100"
                                )}
                                title={item.mode === 'static' ? "Switch to Variable" : item.mode === 'variable' ? "Switch to Upstream Output" : "Switch to Static Value"}
                            >
                                {item.mode === 'static' ? <Type size={12} /> : item.mode === 'variable' ? <Variable size={12} /> : <div className="text-[10px] font-bold">OUT</div>}
                            </button>

                            {item.mode === 'static' ? (
                                <Input
                                    value={item.value}
                                    onChange={(e) => handleChange(index, 'value', e.target.value)}
                                    placeholder="Value"
                                    className="h-8 text-xs bg-white"
                                />
                            ) : item.mode === 'variable' ? (
                                <Select
                                    value={item.value}
                                    onValueChange={(val) => handleChange(index, 'value', val)}
                                >
                                    <SelectTrigger className="h-8 text-xs bg-white w-full">
                                        <SelectValue placeholder="Select state variable..." />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {graphStateFields.map(field => (
                                            <SelectItem key={field.name} value={field.name} className="text-xs">
                                                {field.name} <span className="text-gray-400 ml-1">({field.type})</span>
                                            </SelectItem>
                                        ))}
                                        {(graphStateFields.length === 0) && (
                                            <div className="p-2 text-[10px] text-gray-400 text-center">No state variables defined</div>
                                        )}
                                    </SelectContent>
                                </Select>
                            ) : (
                                <div className="flex w-full gap-1">
                                    <Select
                                        value={item.value ? item.value.split('.')[0] : ''}
                                        onValueChange={(val) => handleChange(index, 'value', val)} // Note: this just sets the node ID for now. User needs to append path manually below.
                                    >
                                        <SelectTrigger className="h-8 text-xs bg-white w-1/2 shrink-0">
                                            <SelectValue placeholder="Node..." />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {nodes.filter(n => n.id !== currentNodeId).map(n => (
                                                <SelectItem key={n.id} value={n.id} className="text-xs">
                                                    {(n.data as any)?.label || n.id}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <Input
                                        value={item.value ? item.value.split('.').slice(1).join('.') : ''}
                                        onChange={(e) => {
                                            const nodeId = item.value ? item.value.split('.')[0] : ''
                                            if (nodeId) {
                                                // Only allow setting path if node is selected
                                                handleChange(index, 'value', e.target.value ? `${nodeId}.${e.target.value}` : nodeId)
                                            }
                                        }}
                                        placeholder="Path (e.g. result.messages)"
                                        className="h-8 text-xs bg-white w-1/2 min-w-0"
                                    />
                                </div>
                            )}
                        </div>

                        {/* Remove Button */}
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleRemove(index)}
                            className="h-8 w-8 text-gray-400 hover:text-red-500 shrink-0"
                        >
                            <Trash2 size={12} />
                        </Button>
                    </div>
                ))}
            </div>

            <Button
                variant="outline"
                size="sm"
                onClick={handleAdd}
                className="w-full border-dashed text-gray-500 mt-1 h-8 text-xs"
            >
                <Plus size={12} /> {t('workspace.addParameter', { defaultValue: 'Add Parameter' })}
            </Button>
        </div>
    )
}
