'use client'

import React from 'react'
import { Node, Edge } from 'reactflow'

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
import { cn } from '@/lib/utils'

import { FieldSchema } from '../services/nodeRegistry'
import type { StateField } from '../types/graph'

import { ModelSelectField } from './fields/ModelSelectField'
import { SkillsField } from './fields/SkillsField'
import { ToolsField } from './fields/ToolsField'

interface SchemaFieldRendererProps {
  schema: FieldSchema
  value: unknown
  onChange: (val: unknown) => void
  disabled?: boolean
  canEdit?: boolean
  t: (key: string, options?: Record<string, unknown>) => string
  onModelChange?: (modelName: string, providerName: string) => void
  nodes?: Node[]
  edges?: Edge[]
  currentNodeId?: string
  onCreateEdge?: (targetNodeId: string, routeKey: string) => void
  graphStateFields?: StateField[]
}

const SchemaFieldRenderer = React.memo(function SchemaFieldRenderer({
  schema,
  value,
  onChange,
  disabled = false,
  canEdit = true,
  t,
  onModelChange,
  nodes,
  edges,
  currentNodeId,
}: SchemaFieldRendererProps) {
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
            'flex cursor-pointer select-none items-center justify-between rounded-lg border p-2 transition-all',
            value ? 'border-[var(--brand-200)] bg-[var(--brand-50)]' : 'border-[var(--border)] bg-[var(--surface-2)]',
          )}
          onClick={() => onChange(!value)}
        >
          <span className="text-sm font-medium text-[var(--text-secondary)]">
            {value ? t('workspace.enabled') : t('workspace.disabled')}
          </span>
          <div
            className={cn(
              'relative h-4 w-7 rounded-full border transition-all',
              value ? 'border-[var(--brand-600)] bg-[var(--brand-500)]' : 'border-[var(--border-strong)] bg-[var(--surface-3)]',
            )}
          >
            <div
              className={cn(
                'absolute top-[2px] h-2.5 w-2.5 rounded-full bg-[var(--surface-1)] transition-all',
                value ? 'right-[2px]' : 'left-[2px]',
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
    case 'textarea': {
      // Check if variable input support is needed (for expression fields)
      const needsVariableSupport = [
        'expression',
        'prompt',
        'template',
      ].includes(schema.key)

      if (needsVariableSupport && nodes && edges && currentNodeId) {
        input = (
          <Textarea
            value={(value as string) || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={schema.placeholder}
            className="min-h-[60px] resize-none py-2 font-mono text-xs focus-visible:ring-1"
          />
        )
      } else {
        input = (
          <Textarea
            value={(value as string) || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={schema.placeholder}
            className="min-h-[60px] resize-none py-2 text-xs focus-visible:ring-1"
          />
        )
      }
      break
    }
    case 'select':
      input = (
        <Select value={(value as string) || ''} onValueChange={onChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue
              placeholder={t('workspace.selectOption', { defaultValue: 'Select option' })}
            />
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
    case 'modelSelect':
      // Save both provider_name and model_name simultaneously
      // Note: Need to determine if it's 'model' or 'memoryModel' based on field name
      input = (
        <ModelSelectField
          value={value as string}
          onChange={(modelName) => {
            // Only call onChange if onModelChange is not handling the update
            // to avoid two competing state updates that race
            if (!onModelChange) {
              onChange(modelName)
            }
          }}
          onModelChange={(modelName, providerName) => {
            // Update both model_name and provider_name simultaneously
            if (onModelChange) {
              onModelChange(modelName, providerName)
            } else {
              // Fallback: just update the field value with combined id
              onChange(`${providerName}:${modelName}`)
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
    default:
      input = (
        <div className="text-xs text-[var(--status-error)]">
          {t('workspace.unknownFieldType', {
            type: schema.type,
            defaultValue: `Unknown field type: ${schema.type}`,
          })}
        </div>
      )
  }

  return (
    <div className="space-y-1.5 duration-200 animate-in fade-in">
      <Label className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
        {translatedLabel} {schema.required && <span className="text-[var(--status-error)]">*</span>}
      </Label>
      {input}
      {schema.description && (
        <p className="text-xs italic leading-tight text-[var(--text-muted)]">{schema.description}</p>
      )}
    </div>
  )
})

export { SchemaFieldRenderer }
export type { SchemaFieldRendererProps }
