'use client'

import { highlight, languages } from 'prismjs'
import React, { useState, useEffect } from 'react'
import Editor from 'react-simple-code-editor'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-javascript'
import { Node, Edge } from 'reactflow'

import { cn } from '@/lib/core/utils/cn'

import { VariableInputField } from './VariableInputField'
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

export const ConditionExprField: React.FC<ConditionExprFieldProps> = ({
  value,
  onChange,
  placeholder = "state.get('value', 0) > 10",
  description,
  variables = ['state', 'messages', 'context'],
  nodes,
  edges,
  currentNodeId,
  className,
  disabled = false,
  graphStateFields,
}) => {
  // Use local state to prevent losing focus during input
  const [localValue, setLocalValue] = useState(value)

  // Builder state
  const [mode, setMode] = useState<'builder' | 'code'>('builder')
  const [builderState, setBuilderState] = useState({
    variable: '',
    operator: '==',
    value: ''
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
        value: match[3].replace(/^['"]|['"]$/g, '')
      })
      setMode('builder')
    } else if (isEmptyMatch) {
      setBuilderState({
        variable: isEmptyMatch[1],
        operator: 'is_empty',
        value: ''
      })
      setMode('builder')
    } else if (isNotEmptyMatch) {
      setBuilderState({
        variable: isNotEmptyMatch[1],
        operator: 'is_not_empty',
        value: ''
      })
      setMode('builder')
    } else if (value && value.trim() !== '') {
      setMode('code')
    }
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
    const isBool = newState.value.toLowerCase() === 'true' || newState.value.toLowerCase() === 'false'
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
            "text-[10px] px-2 py-0.5 rounded-full border transition-all",
            mode === 'builder'
              ? "bg-blue-50 border-blue-200 text-blue-700 font-medium"
              : "bg-transparent border-transparent text-gray-400 hover:text-gray-600"
          )}
        >
          Visual
        </button>
        <button
          onClick={() => setMode('code')}
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border transition-all",
            mode === 'code'
              ? "bg-purple-50 border-purple-200 text-purple-700 font-medium"
              : "bg-transparent border-transparent text-gray-400 hover:text-gray-600"
          )}
        >
          Code
        </button>
      </div>

      {mode === 'builder' ? (
        <div className="p-3 bg-gray-50/50 rounded-lg border border-gray-200 space-y-3">
          {/* Builder UI */}
          <div className="space-y-1">
            <label className="text-[10px] uppercase font-bold text-gray-400">Variable</label>
            <select
              className="w-full h-8 text-xs bg-white border border-gray-200 rounded px-2 outline-none focus:border-blue-400"
              value={builderState.variable}
              onChange={(e) => updateBuilder('variable', e.target.value)}
            >
              <option value="" disabled>Select state variable...</option>
              {graphStateFields?.map(f => (
                <option key={f.name} value={f.name}>{f.name} ({f.type})</option>
              ))}
              <option disabled>--- System ---</option>
              <option value="loop_count">loop_count</option>
              <option value="current_node">current_node</option>
              {!graphStateFields?.find(f => f.name === builderState.variable) && builderState.variable && (
                <option value={builderState.variable}>{builderState.variable}</option>
              )}
            </select>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-1 space-y-1">
              <label className="text-[10px] uppercase font-bold text-gray-400">Condition</label>
              <select
                className="w-full h-8 text-xs bg-white border border-gray-200 rounded px-2 outline-none focus:border-blue-400"
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
              <label className="text-[10px] uppercase font-bold text-gray-400">Value</label>
              {!['is_empty', 'is_not_empty'].includes(builderState.operator) && (
                <input
                  className="w-full h-8 text-xs bg-white border border-gray-200 rounded px-2 outline-none focus:border-blue-400"
                  placeholder="Value..."
                  value={builderState.value}
                  onChange={(e) => updateBuilder('value', e.target.value)}
                />
              )}
            </div>
          </div>

          <div className="pt-2 border-t border-gray-100">
            <p className="text-[9px] text-gray-400 font-mono truncate">
              Preview: <span className="text-blue-500">{localValue || '(empty)'}</span>
            </p>
          </div>
        </div>
      ) : (
        <div className="relative">
          <div
            className={cn(
              'relative min-h-[80px] rounded-lg border bg-white font-mono text-xs',
              'focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500',
              disabled && 'bg-gray-50 cursor-not-allowed opacity-60'
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
        <p className="text-[9px] text-gray-400 leading-tight italic">{description}</p>
      )}

      {variables && variables.length > 0 && mode === 'code' && (
        <div className="text-[9px] text-gray-500">
          <span className="font-medium">Available variables:</span>{' '}
          {variables.join(', ')}
        </div>
      )}
    </div>
  )
}
