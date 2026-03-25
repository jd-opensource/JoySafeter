'use client'

import { highlight, languages } from 'prismjs'
import { useState, useEffect } from 'react'
import Editor from 'react-simple-code-editor'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-javascript'
import { Node, Edge } from 'reactflow'

import { cn } from '@/lib/utils'

import { StateField } from '../../types/graph'


interface ConditionExprFieldProps {
  value: string
  onChange: (expr: string) => void
  placeholder?: string
  description?: string
  variables?: string[]
  nodes?: Node[]
  edges?: Edge[]
  currentNodeId?: string
  className?: string
  disabled?: boolean
  graphStateFields?: StateField[]
}

export function ConditionExprField({
  value,
  onChange,
  placeholder = "state.get('value', 0) > 10",
  description,
  variables = ['state', 'messages', 'context'],
  nodes: _nodes,
  edges: _edges,
  currentNodeId: _currentNodeId,
  className,
  disabled = false,
  graphStateFields,
}: ConditionExprFieldProps) {
  // Use local state to prevent losing focus during input
  const [localValue, setLocalValue] = useState(value)

  // Builder state
  const [mode, setMode] = useState<'builder' | 'code'>('builder')
  const [builderState, setBuilderState] = useState({
    variable: '',
    operator: '==',
    value: '',
  })

  // Sync external value to local state when it changes from outside
  useEffect(() => {
    setLocalValue(value)
  }, [value])

  // Parse initial value to builder state if possible
  useEffect(() => {
    if (!value) return

    // Regex to match common patterns: state.get('VAR') OP VAL
    const match = value.match(/state\.get\(['"](\w+)['"](?:,\s*[^)]+)?\)\s*([=!<>]+|in)\s*(.+)/)
    const isEmptyMatch = value.match(/not\s+state\.get\(['"](\w+)['"]\)/)
    const isNotEmptyMatch = value.match(/^state\.get\(['"](\w+)['"]\)$/)

    if (match) {
      setBuilderState({
        variable: match[1],
        operator: match[2],
        value: match[3].replace(/^['"]|['"]$/g, ''),
      })
      setMode('builder')
    } else if (isEmptyMatch) {
      setBuilderState({
        variable: isEmptyMatch[1],
        operator: 'is_empty',
        value: '',
      })
      setMode('builder')
    } else if (isNotEmptyMatch) {
      setBuilderState({
        variable: isNotEmptyMatch[1],
        operator: 'is_not_empty',
        value: '',
      })
      setMode('builder')
    } else if (value && value.trim() !== '') {
      setMode('code')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleChange = (code: string) => {
    setLocalValue(code)
  }

  const handleBlur = () => {
    if (localValue !== value) {
      onChange(localValue)
    }
  }

  const updateBuilder = (key: string, val: string) => {
    const newState = { ...builderState, [key]: val }
    setBuilderState(newState)

    let code = ''
    if (!newState.variable) return

    const varRef = `state.get('${newState.variable}')`

    const isNumber = !isNaN(Number(newState.value)) && newState.value.trim() !== ''
    const isBool =
      newState.value.toLowerCase() === 'true' || newState.value.toLowerCase() === 'false'
    const cleanValue = isNumber || isBool ? newState.value.toLowerCase() : `'${newState.value}'`

    switch (newState.operator) {
      case 'is_empty':
        code = `not ${varRef}`
        break
      case 'is_not_empty':
        code = `${varRef}`
        break
      case 'contains':
        code = `'${newState.value}' in ${varRef}`
        break
      default:
        code = `${varRef} ${newState.operator} ${cleanValue}`
    }

    setLocalValue(code)
    onChange(code)
  }

  return (
    <div className={cn('space-y-2', className)}>
      {/* Mode Switcher */}
      <div className="flex items-center justify-end gap-2">
        <button
          onClick={() => setMode('builder')}
          className={cn(
            'rounded-full border px-2 py-0.5 text-[10px] transition-all',
            mode === 'builder'
              ? 'border-primary/20 bg-primary/5 font-medium text-primary'
              : 'border-transparent bg-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
          )}
        >
          Visual
        </button>
        <button
          onClick={() => setMode('code')}
          className={cn(
            'rounded-full border px-2 py-0.5 text-[10px] transition-all',
            mode === 'code'
              ? 'border-purple-200 bg-purple-50 font-medium text-purple-700'
              : 'border-transparent bg-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
          )}
        >
          Code
        </button>
      </div>

      {mode === 'builder' ? (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface-2)]/50 p-3">
          {/* Builder UI */}
          <div className="space-y-1">
            <label className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Variable</label>
            <select
              className="h-8 w-full rounded border border-[var(--border)] bg-[var(--surface-elevated)] px-2 text-xs outline-none focus:border-primary"
              value={builderState.variable}
              onChange={(e) => updateBuilder('variable', e.target.value)}
            >
              <option value="" disabled>
                Select state variable...
              </option>
              {graphStateFields?.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} ({f.type})
                </option>
              ))}
              <option disabled>--- System ---</option>
              <option value="loop_count">loop_count</option>
              <option value="current_node">current_node</option>
              {!graphStateFields?.find((f) => f.name === builderState.variable) &&
                builderState.variable && (
                  <option value={builderState.variable}>{builderState.variable}</option>
                )}
            </select>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-1 space-y-1">
              <label className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Condition</label>
              <select
                className="h-8 w-full rounded border border-[var(--border)] bg-[var(--surface-elevated)] px-2 text-xs outline-none focus:border-primary"
                value={builderState.operator}
                onChange={(e) => updateBuilder('operator', e.target.value)}
              >
                <option value="==">==</option>
                <option value="!=">!=</option>
                <option value=">">&gt;</option>
                <option value="<">&lt;</option>
                <option value=">=">&gt;=</option>
                <option value="<=">&lt;=</option>
                <option value="contains">Contains</option>
                <option value="is_empty">Is Empty</option>
                <option value="is_not_empty">Is Not Empty</option>
              </select>
            </div>

            <div className="col-span-2 space-y-1">
              <label className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Value</label>
              {!['is_empty', 'is_not_empty'].includes(builderState.operator) && (
                <input
                  className="h-8 w-full rounded border border-[var(--border)] bg-[var(--surface-elevated)] px-2 text-xs outline-none focus:border-primary"
                  placeholder="Value..."
                  value={builderState.value}
                  onChange={(e) => updateBuilder('value', e.target.value)}
                />
              )}
            </div>
          </div>

          <div className="border-t border-[var(--border-muted)] pt-2">
            <p className="truncate font-mono text-[9px] text-[var(--text-muted)]">
              Preview: <span className="text-primary">{localValue || '(empty)'}</span>
            </p>
          </div>
        </div>
      ) : (
        <div className="relative">
          <div
            className={cn(
              'relative min-h-[80px] rounded-lg border bg-[var(--surface-elevated)] font-mono text-xs',
              'focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20',
              disabled && 'cursor-not-allowed bg-[var(--surface-2)] opacity-60',
            )}
          >
            <Editor
              value={localValue}
              onValueChange={handleChange}
              onBlur={handleBlur}
              highlight={(code) => highlight(code, languages.python, 'python')}
              padding={8}
              style={{
                fontFamily: '"Fira Code", "Fira Mono", "Consolas", "Monaco", monospace',
                fontSize: 13,
                lineHeight: '21px',
                outline: 'none',
                minHeight: '80px',
              }}
              textareaClassName="outline-none resize-none"
              disabled={disabled}
              placeholder={placeholder}
              className="w-full"
            />
          </div>
        </div>
      )}

      {description && mode === 'code' && (
        <p className="text-[9px] italic leading-tight text-[var(--text-muted)]">{description}</p>
      )}

      {variables && variables.length > 0 && mode === 'code' && (
        <div className="text-[9px] text-[var(--text-tertiary)]">
          <span className="font-medium">Available variables:</span> {variables.join(', ')}
        </div>
      )}
    </div>
  )
}
