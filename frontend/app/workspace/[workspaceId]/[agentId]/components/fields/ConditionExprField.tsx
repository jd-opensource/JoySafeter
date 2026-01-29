'use client'

import { highlight, languages } from 'prismjs'
import React, { useState, useEffect } from 'react'
import Editor from 'react-simple-code-editor'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-javascript'
import { Node, Edge } from 'reactflow'

import { cn } from '@/lib/core/utils/cn'

import { VariableInputField } from './VariableInputField'

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
}

/**
 * ConditionExprField - Code editor for condition expressions
 *
 * Features:
 * - Syntax highlighting (Python)
 * - Variable support (via VariableInputField)
 */
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
}) => {
  // Use local state to prevent losing focus during input
  const [localValue, setLocalValue] = useState(value)

  // Sync external value to local state when it changes from outside
  useEffect(() => {
    setLocalValue(value)
  }, [value])

  const handleChange = (code: string) => {
    // Update local state immediately to prevent losing focus
    setLocalValue(code)
    // Don't call onChange here to prevent parent re-render
  }

  const handleBlur = () => {
    // Update parent only when user finishes editing (on blur)
    if (localValue !== value) {
      onChange(localValue)
    }
  }

  // If we have nodes/edges, use VariableInputField for better variable support
  const useVariableInput = nodes && edges && currentNodeId

  if (useVariableInput) {
    return (
      <div className={cn('space-y-1.5', className)}>
        <VariableInputField
          label=""
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          description={description}
          nodes={nodes}
          edges={edges}
          currentNodeId={currentNodeId}
          className={className}
        />
      </div>
    )
  }

  return (
    <div className={cn('space-y-1.5', className)}>
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

      {/* Description */}
      {description && (
        <p className="text-[9px] text-gray-400 leading-tight italic">{description}</p>
      )}

      {/* Variable Hints */}
      {variables && variables.length > 0 && (
        <div className="text-[9px] text-gray-500">
          <span className="font-medium">Available variables:</span>{' '}
          {variables.join(', ')}
        </div>
      )}
    </div>
  )
}
