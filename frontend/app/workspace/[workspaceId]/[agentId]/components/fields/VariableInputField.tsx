'use client'

import { Database } from 'lucide-react'
import React, { useState, useRef, useEffect } from 'react'
import { Node, Edge } from 'reactflow'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/core/utils/cn'

import Editor from 'react-simple-code-editor'
import Prism from 'prismjs'
// Import a basic theme, we will override it with Tailwind classes for our custom tokens
import 'prismjs/themes/prism.css'

import { StateVariablePanel } from '../StateVariablePanel'

// Add custom prism language definition for our variables
Prism.languages.joyvariables = {
  // Matches state.get('variable_name') or state.get("variable_name")
  variable_function: {
    pattern: /state\.get\(['"]([^'"]+)['"]\)/,
    inside: {
      keyword: /^state\.get/,
      punctuation: /[()]/,
      string: /['"][^'"]+['"]/,
    },
    alias: 'magic-pill',
  },
  // Matches state.variable_name
  variable_dot: {
    pattern: /state\.([a-zA-Z0-9_]+)/,
    inside: {
      keyword: /^state\./,
      property: /[a-zA-Z0-9_]+$/,
    },
    alias: 'magic-pill',
  },
  // Matches result.variable_name (used in output mappings)
  variable_result: {
    pattern: /result\.([a-zA-Z0-9_]+)/,
    inside: {
      keyword: /^result\./,
      property: /[a-zA-Z0-9_]+$/,
    },
    alias: 'magic-pill',
  },
}

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

  const handleInputChange = (newValue: string) => {
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
    // Try to get cursor position or default to end
    // For Editor, we might not have direct selectionStart natively easily without ref digging,
    // so appending to end is safest if cursor is lost.
    const start = localValue.length
    const before = localValue
    const newValue = before + (before.endsWith(' ') || before === '' ? '' : ' ') + variablePath + ' '

    setLocalValue(newValue)
    setShowVariablePanel(false)
    onChange(newValue)
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

      <div className="relative group">
        <div className={cn(
          "min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-within:ring-1 focus-within:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          "editor-container" // Hook for custom CSS
        )}>
          <Editor
            value={localValue}
            onValueChange={handleInputChange}
            highlight={code => Prism.highlight(code, Prism.languages.joyvariables, 'joyvariables')}
            padding={0}
            onKeyDown={(e) => {
              if (e.key === '@' && !showVariablePanel) {
                // Don't prevent default, let the @ type out, then open panel
                setTimeout(() => setShowVariablePanel(true), 50)
              }
            }}
            onBlur={handleBlur}
            style={{
              fontFamily: '"JetBrains Mono", "Fira Code", monospace',
              fontSize: 12,
              minHeight: '40px',
              outline: 'none',
              border: 'none',
              background: 'transparent'
            }}
            placeholder={placeholder || 'Type @ to insert variable...'}
            textareaClassName="focus:outline-none"
          />
        </div>

        {/* CSS to style the highlighted tokens as data pills */}
        <style dangerouslySetInnerHTML={{
          __html: `
          .editor-container .token.magic-pill {
            background-color: var(--blue-100, #e0f2fe);
            color: var(--blue-700, #0369a1);
            border: 1px solid var(--blue-200, #bae6fd);
            border-radius: 9999px;
            padding: 2px 6px;
            font-size: 11px;
            font-weight: 600;
            display: inline-block;
            line-height: 1;
            margin: 0 2px;
            pointer-events: none; /* Let clicks pass through to editor */
          }
          .editor-container .token.magic-pill .keyword,
          .editor-container .token.magic-pill .property,
          .editor-container .token.magic-pill .string,
          .editor-container .token.magic-pill .punctuation {
             color: inherit !important;
             background: transparent !important;
             text-shadow: none !important;
          }
        `}} />
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
