'use client'

import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface DockerConfigFieldProps {
  label: string
  value: Record<string, unknown> | undefined
  onChange: (value: Record<string, unknown>) => void
  description?: string
  disabled?: boolean
}

export function DockerConfigField({
  label,
  value = {},
  onChange,
  description,
  disabled = false,
}: DockerConfigFieldProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  const updateField = (key: string, fieldValue: unknown) => {
    onChange({
      ...value,
      [key]: fieldValue,
    })
  }

  const config = value as {
    image?: string
    working_dir?: string
    auto_remove?: boolean
    max_output_size?: number
    command_timeout?: number
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="space-y-0.5">
          <Label className="text-xs font-semibold text-[var(--text-secondary)]">{label}</Label>
          {description && (
            <p className="text-[10px] leading-relaxed text-[var(--text-tertiary)]">{description}</p>
          )}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setIsExpanded(!isExpanded)}
          disabled={disabled}
          className="h-6 w-6 p-0"
        >
          {isExpanded ? (
            <ChevronUp size={14} className="text-[var(--text-muted)]" />
          ) : (
            <ChevronDown size={14} className="text-[var(--text-muted)]" />
          )}
        </Button>
      </div>

      {isExpanded && (
        <div className="space-y-3 rounded-r-md border-l-2 border-primary/20 bg-primary/5 p-3 pl-4 duration-200 animate-in slide-in-from-top-2">
          {/* Docker Image */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-[var(--text-secondary)]">Docker Image</Label>
            <Input
              value={config.image || 'python:3.12-slim'}
              onChange={(e) => updateField('image', e.target.value)}
              placeholder="python:3.12-slim"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-[var(--text-muted)]">Docker image to use for the sandbox</p>
          </div>

          {/* Working Directory */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-[var(--text-secondary)]">Working Directory</Label>
            <Input
              value={config.working_dir || '/workspace'}
              onChange={(e) => updateField('working_dir', e.target.value)}
              placeholder="/workspace"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-[var(--text-muted)]">Working directory in container</p>
          </div>

          {/* Auto Remove */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-[var(--text-secondary)]">Auto Remove</Label>
            <Select
              value={String(config.auto_remove !== false)}
              onValueChange={(val) => updateField('auto_remove', val === 'true')}
              disabled={disabled}
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true">true</SelectItem>
                <SelectItem value="false">false</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[9px] text-[var(--text-muted)]">Auto-remove container on exit</p>
          </div>

          {/* Max Output Size */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-[var(--text-secondary)]">Max Output Size</Label>
            <Input
              type="number"
              value={config.max_output_size || 100000}
              onChange={(e) => updateField('max_output_size', Number(e.target.value))}
              placeholder="100000"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-[var(--text-muted)]">Maximum command output size in characters</p>
          </div>

          {/* Command Timeout */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-[var(--text-secondary)]">Command Timeout</Label>
            <Input
              type="number"
              value={config.command_timeout || 30}
              onChange={(e) => updateField('command_timeout', Number(e.target.value))}
              placeholder="30"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-[var(--text-muted)]">Command execution timeout in seconds</p>
          </div>
        </div>
      )}
    </div>
  )
}
