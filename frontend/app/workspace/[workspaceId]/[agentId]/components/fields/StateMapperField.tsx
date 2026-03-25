'use client'

import { Trash2, Plus, ArrowRight, Variable, Type } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { useBuilderStore } from '../../stores/builderStore'
import { StateField } from '../../types/graph'


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

export function StateMapperField({
  value,
  onChange,
  graphStateFields = [],
  currentNodeId,
}: StateMapperFieldProps) {
  const { t } = useTranslation()
  const nodes = useBuilderStore((state) => state.nodes)

  // Convert input value to internal state format
  const items: MappingItem[] = React.useMemo(() => {
    let rawItems: { key: string; value: string }[] = []

    if (Array.isArray(value)) {
      rawItems = value
    } else if (typeof value === 'object' && value !== null) {
      rawItems = Object.entries(value).map(([k, v]) => ({ key: k, value: String(v) }))
    }

    return rawItems.map((item) => {
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
      value: '', // Clear value on mode switch to avoid confusion
    }
    emitChange(newItems)
  }

  const emitChange = (newItems: MappingItem[]) => {
    // Transform back to code format
    const output = newItems.map((item) => {
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
    <div className="space-y-2 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3">
      {items.length === 0 && (
        <div className="py-2 text-center text-[10px] text-[var(--text-muted)]">
          {t('workspace.noParametersDefined', { defaultValue: 'No parameters defined' })}
        </div>
      )}

      <div className="space-y-2">
        {items.map((item, index) => (
          <div key={index} className="group flex items-start gap-2">
            {/* Param Name */}
            <div className="flex-1">
              <Input
                value={item.key}
                onChange={(e) => handleChange(index, 'key', e.target.value)}
                placeholder="Parameter Name"
                className="h-8 bg-[var(--surface-elevated)] font-mono text-xs"
              />
            </div>

            <ArrowRight size={12} className="mt-2.5 shrink-0 text-[var(--text-subtle)]" />

            {/* Value Input */}
            <div className="relative flex flex-[1.5] gap-1">
              {/* Mode Toggle */}
              <button
                onClick={() => toggleMode(index)}
                className={cn(
                  'flex h-8 w-6 shrink-0 items-center justify-center rounded border transition-colors',
                  item.mode === 'static' &&
                    'border-[var(--border)] bg-[var(--surface-3)] text-[var(--text-tertiary)] hover:bg-[var(--surface-5)]',
                  item.mode === 'variable' &&
                    'border-primary/20 bg-primary/5 text-primary hover:bg-primary/10',
                  item.mode === 'upstream_output' &&
                    'border-purple-200 bg-purple-50 text-purple-600 hover:bg-purple-100',
                )}
                title={
                  item.mode === 'static'
                    ? 'Switch to Variable'
                    : item.mode === 'variable'
                      ? 'Switch to Upstream Output'
                      : 'Switch to Static Value'
                }
              >
                {item.mode === 'static' ? (
                  <Type size={12} />
                ) : item.mode === 'variable' ? (
                  <Variable size={12} />
                ) : (
                  <div className="text-[10px] font-bold">OUT</div>
                )}
              </button>

              {item.mode === 'static' ? (
                <Input
                  value={item.value}
                  onChange={(e) => handleChange(index, 'value', e.target.value)}
                  placeholder="Value"
                  className="h-8 bg-[var(--surface-elevated)] text-xs"
                />
              ) : item.mode === 'variable' ? (
                <Select
                  value={item.value}
                  onValueChange={(val) => handleChange(index, 'value', val)}
                >
                  <SelectTrigger className="h-8 w-full bg-[var(--surface-elevated)] text-xs">
                    <SelectValue placeholder="Select state variable..." />
                  </SelectTrigger>
                  <SelectContent>
                    {graphStateFields.map((field) => (
                      <SelectItem key={field.name} value={field.name} className="text-xs">
                        {field.name} <span className="ml-1 text-[var(--text-muted)]">({field.type})</span>
                      </SelectItem>
                    ))}
                    {graphStateFields.length === 0 && (
                      <div className="p-2 text-center text-[10px] text-[var(--text-muted)]">
                        No state variables defined
                      </div>
                    )}
                  </SelectContent>
                </Select>
              ) : (
                <div className="flex w-full gap-1">
                  <Select
                    value={item.value ? item.value.split('.')[0] : ''}
                    onValueChange={(val) => handleChange(index, 'value', val)} // Note: this just sets the node ID for now. User needs to append path manually below.
                  >
                    <SelectTrigger className="h-8 w-1/2 shrink-0 bg-[var(--surface-elevated)] text-xs">
                      <SelectValue placeholder="Node..." />
                    </SelectTrigger>
                    <SelectContent>
                      {nodes
                        .filter((n) => n.id !== currentNodeId)
                        .map((n) => (
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
                        handleChange(
                          index,
                          'value',
                          e.target.value ? `${nodeId}.${e.target.value}` : nodeId,
                        )
                      }
                    }}
                    placeholder="Path (e.g. result.messages)"
                    className="h-8 w-1/2 min-w-0 bg-[var(--surface-elevated)] text-xs"
                  />
                </div>
              )}
            </div>

            {/* Remove Button */}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => handleRemove(index)}
              className="h-8 w-8 shrink-0 text-[var(--text-muted)] hover:text-[var(--status-error)]"
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
        className="mt-1 h-8 w-full border-dashed text-xs text-[var(--text-tertiary)]"
      >
        <Plus size={12} /> {t('workspace.addParameter', { defaultValue: 'Add Parameter' })}
      </Button>
    </div>
  )
}
