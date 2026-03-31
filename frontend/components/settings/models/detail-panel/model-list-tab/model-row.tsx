'use client'

import { Settings } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { AvailableModel } from '@/types/models'

const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  no_credentials: '未配置凭证',
  invalid_credentials: '凭证无效',
  model_not_found: '模型不在列表中',
  provider_error: '供应商错误',
}

interface ModelRowProps {
  model: AvailableModel
  onEditParams: () => void
}

export function ModelRow({ model, onEditParams }: ModelRowProps) {
  const unavailableLabel = model.unavailable_reason
    ? UNAVAILABLE_REASON_LABELS[model.unavailable_reason] ?? model.unavailable_reason
    : null

  return (
    <div className="flex items-center justify-between rounded-lg border border-[var(--border-muted)] bg-[var(--surface-elevated)] px-4 py-3 hover:bg-[var(--surface-3)] transition-colors">
      <div className="flex items-center gap-3 min-w-0">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[var(--text-primary)] truncate">
            {model.display_name || model.name}
          </p>
          {model.description && (
            <p className="text-xs text-[var(--text-tertiary)] truncate">{model.description}</p>
          )}
          {model.model_parameters && Object.keys(model.model_parameters).length > 0 && (
            <p className="text-xs text-[var(--text-muted)] truncate">
              {Object.entries(model.model_parameters)
                .slice(0, 3)
                .map(([k, v]) => `${k}: ${v}`)
                .join(', ')}
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0 ml-3">
        {model.is_available ? (
          <Badge variant="outline" className="text-green-600 border-green-200 bg-green-50 text-xs">
            可用
          </Badge>
        ) : (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="outline" className="text-red-600 border-red-200 bg-red-50 text-xs cursor-help">
                  不可用
                </Badge>
              </TooltipTrigger>
              {unavailableLabel && <TooltipContent>{unavailableLabel}</TooltipContent>}
            </Tooltip>
          </TooltipProvider>
        )}

        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onEditParams}>
          <Settings className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
