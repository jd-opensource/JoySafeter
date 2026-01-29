'use client'

import { Database } from 'lucide-react'
import React, { useState, useRef, useEffect } from 'react'
import { Node, Edge } from 'reactflow'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/core/utils/cn'


import { StateVariablePanel } from '../StateVariablePanel'

interface VariableInputFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  description?: string
  nodes: Node[]
  edges: Edge[]
  currentNodeId?: string
  className?: string
}

export const VariableInputField: React.FC<VariableInputFieldProps> = ({
  label,
  value,
  onChange,
  placeholder,
  description,
  nodes,
  edges,
  currentNodeId,
  className,
}) => {
  const [showVariablePanel, setShowVariablePanel] = useState(false)
  // Use local state to prevent losing focus during input
  const [localValue, setLocalValue] = useState(value)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Sync external value to local state when it changes from outside
  useEffect(() => {
    setLocalValue(value)
  }, [value])

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value
    // Update local state immediately to prevent losing focus
    setLocalValue(newValue)
    // Don't call onChange here to prevent parent re-render
  }

  const handleBlur = () => {
    // Update parent only when user finishes editing (on blur)
    if (localValue !== value) {
      onChange(localValue)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Keep @ key handler for variable panel if needed
    if (e.key === '@' && !showVariablePanel) {
      e.preventDefault()
      setShowVariablePanel(true)
    }
  }

  const handleVariableSelect = (variablePath: string) => {
    if (textareaRef.current) {
      const textarea = textareaRef.current
      const start = textarea.selectionStart || 0
      const end = textarea.selectionEnd || start
      const before = localValue.substring(0, start)
      const after = localValue.substring(end)
      const newValue = before + variablePath + after
      setLocalValue(newValue)
      setShowVariablePanel(false)
      
      // Set cursor position after inserted variable
      setTimeout(() => {
        textarea.focus()
        const newPosition = start + variablePath.length
        textarea.setSelectionRange(newPosition, newPosition)
        // Update parent after variable insertion
        onChange(newValue)
      }, 0)
    }
  }


  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-center justify-between">
        <Label className="text-xs font-semibold">{label}</Label>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowVariablePanel(!showVariablePanel)}
          className="h-7 text-xs"
          title="Show available variables"
        >
          <Database size={14} />
          <span className="ml-1">Variables</span>
        </Button>
      </div>

      <div className="relative">
        <Textarea
          ref={textareaRef}
          value={localValue}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          placeholder={placeholder || 'Type @ to insert variable...'}
          className="min-h-[60px] text-xs font-mono"
        />
      </div>

      {/* Description */}
      {description && (
        <p className="text-[10px] text-gray-500">{description}</p>
      )}

      {/* Variable Panel */}
      {showVariablePanel && (
        <StateVariablePanel
          nodes={nodes}
          edges={edges}
          selectedNodeId={currentNodeId}
          onVariableSelect={handleVariableSelect}
          onClose={() => setShowVariablePanel(false)}
        />
      )}
    </div>
  )
}

