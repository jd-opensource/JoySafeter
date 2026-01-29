'use client'

import { ChevronDown, ChevronUp } from 'lucide-react'
import React, { useState } from 'react'

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
import { cn } from '@/lib/core/utils/cn'

interface DockerConfigFieldProps {
  label: string
  value: Record<string, unknown> | undefined
  onChange: (value: Record<string, unknown>) => void
  description?: string
  disabled?: boolean
}

export const DockerConfigField: React.FC<DockerConfigFieldProps> = ({
  label,
  value = {},
  onChange,
  description,
  disabled = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(false)

  const updateField = (key: string, fieldValue: unknown) => {
    onChange({
      ...value,
      [key]: fieldValue,
    })
  }

  const config = value as {
    image?: string
    memory_limit?: string
    cpu_quota?: number
    network_mode?: string
    working_dir?: string
    auto_remove?: boolean
    max_output_size?: number
    command_timeout?: number
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="space-y-0.5">
          <Label className="text-xs font-semibold text-gray-700">{label}</Label>
          {description && (
            <p className="text-[10px] text-gray-500 leading-relaxed">{description}</p>
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
            <ChevronUp size={14} className="text-gray-400" />
          ) : (
            <ChevronDown size={14} className="text-gray-400" />
          )}
        </Button>
      </div>

      {isExpanded && (
        <div className="space-y-3 pl-4 border-l-2 border-blue-100 bg-blue-50/30 rounded-r-md p-3 animate-in slide-in-from-top-2 duration-200">
          {/* Docker Image */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-gray-600">Docker Image</Label>
            <Input
              value={config.image || 'python:3.12-slim'}
              onChange={(e) => updateField('image', e.target.value)}
              placeholder="python:3.12-slim"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-gray-400">Docker image to use for the sandbox</p>
          </div>

          {/* Memory Limit */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-gray-600">Memory Limit</Label>
            <Input
              value={config.memory_limit || '512m'}
              onChange={(e) => updateField('memory_limit', e.target.value)}
              placeholder="512m"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-gray-400">Memory limit (e.g., 512m, 1g)</p>
          </div>

          {/* CPU Quota */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-gray-600">CPU Quota</Label>
            <Input
              type="number"
              value={config.cpu_quota || 50000}
              onChange={(e) => updateField('cpu_quota', Number(e.target.value))}
              placeholder="50000"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-gray-400">
              CPU quota in microseconds (50000 = 50% of one core)
            </p>
          </div>

          {/* Network Mode */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-gray-600">Network Mode</Label>
            <Select
              value={config.network_mode || 'none'}
              onValueChange={(val) => updateField('network_mode', val)}
              disabled={disabled}
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">none (Isolated)</SelectItem>
                <SelectItem value="bridge">bridge (Network Access)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[9px] text-gray-400">
              Network isolation mode (none recommended for production)
            </p>
          </div>

          {/* Working Directory */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-gray-600">Working Directory</Label>
            <Input
              value={config.working_dir || '/workspace'}
              onChange={(e) => updateField('working_dir', e.target.value)}
              placeholder="/workspace"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-gray-400">Working directory in container</p>
          </div>

          {/* Auto Remove */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-gray-600">Auto Remove</Label>
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
            <p className="text-[9px] text-gray-400">Auto-remove container on exit</p>
          </div>

          {/* Max Output Size */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-gray-600">Max Output Size</Label>
            <Input
              type="number"
              value={config.max_output_size || 100000}
              onChange={(e) => updateField('max_output_size', Number(e.target.value))}
              placeholder="100000"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-gray-400">Maximum command output size in characters</p>
          </div>

          {/* Command Timeout */}
          <div className="space-y-1">
            <Label className="text-[10px] font-medium text-gray-600">Command Timeout</Label>
            <Input
              type="number"
              value={config.command_timeout || 30}
              onChange={(e) => updateField('command_timeout', Number(e.target.value))}
              placeholder="30"
              disabled={disabled}
              className="h-7 text-xs"
            />
            <p className="text-[9px] text-gray-400">Command execution timeout in seconds</p>
          </div>
        </div>
      )}
    </div>
  )
}
