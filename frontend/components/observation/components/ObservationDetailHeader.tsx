'use client'

import { Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard'
import { ItemBadge } from './ItemBadge'
import {
  formatIntervalSeconds,
  usdFormatter,
  formatTokenCounts,
  formatLocalIsoMs,
} from '../lib/helpers'
import type { ObservationNode } from '../lib/types'

interface ObservationDetailHeaderProps {
  node: ObservationNode
}

function CopyIdButton({ id }: { id: string }) {
  const { copied, handleCopy } = useCopyToClipboard(1500)

  return (
    <button
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded opacity-50 hover:bg-muted hover:opacity-100 transition-opacity"
      onClick={() => handleCopy(id)}
      title="Copy observation ID"
    >
      {copied ? (
        <Check className="h-3 w-3 text-green-600" />
      ) : (
        <Copy className="h-3 w-3 text-muted-foreground" />
      )}
    </button>
  )
}

function UsageTooltipContent({ node }: { node: ObservationNode }) {
  const details = node.usageDetails
  if (!details) return null

  return (
    <div className="space-y-1 text-xs">
      {details.input != null && (
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Input</span>
          <span>{details.input.toLocaleString()}</span>
        </div>
      )}
      {details.output != null && (
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Output</span>
          <span>{details.output.toLocaleString()}</span>
        </div>
      )}
      {details.total != null && (
        <div className="flex justify-between gap-4 border-t pt-1">
          <span className="text-muted-foreground">Total</span>
          <span className="font-medium">{details.total.toLocaleString()}</span>
        </div>
      )}
    </div>
  )
}

function CostTooltipContent({ node }: { node: ObservationNode }) {
  const hasBreakdown =
    node.calculatedInputCost != null || node.calculatedOutputCost != null

  if (!hasBreakdown) return null

  return (
    <div className="space-y-1 text-xs">
      {node.calculatedInputCost != null && (
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Input</span>
          <span>{usdFormatter(node.calculatedInputCost)}</span>
        </div>
      )}
      {node.calculatedOutputCost != null && (
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Output</span>
          <span>{usdFormatter(node.calculatedOutputCost)}</span>
        </div>
      )}
      {node.calculatedTotalCost != null && (
        <div className="flex justify-between gap-4 border-t pt-1">
          <span className="text-muted-foreground">Total</span>
          <span className="font-medium">{usdFormatter(node.calculatedTotalCost)}</span>
        </div>
      )}
    </div>
  )
}

export function ObservationDetailHeader({ node }: ObservationDetailHeaderProps) {
  const ttft =
    node.completionStartTime && node.startTime
      ? (node.completionStartTime.getTime() - node.startTime.getTime()) / 1000
      : null

  return (
    <div className="space-y-1.5 border-b px-4 py-3">
      <div className="flex items-center gap-2">
        <ItemBadge type={node.type} showLabel />
        <span className="truncate text-sm font-medium">{node.name}</span>
        <CopyIdButton id={node.id} />
      </div>

      <div className="text-xs text-muted-foreground">
        {formatLocalIsoMs(node.startTime)}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {node.latency != null && (
          <Badge variant="secondary" className="text-[10px] font-normal">
            {formatIntervalSeconds(node.latency)}
          </Badge>
        )}

        {ttft != null && (
          <Badge variant="secondary" className="text-[10px] font-normal">
            TTFT {formatIntervalSeconds(ttft)}
          </Badge>
        )}

        <TooltipProvider delayDuration={200}>
          {node.totalCost > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="secondary" className="cursor-default text-[10px] font-normal">
                  {node.children.length > 0 ? '∑ ' : ''}
                  {usdFormatter(node.totalCost)}
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <CostTooltipContent node={node} />
              </TooltipContent>
            </Tooltip>
          )}

          {(node.totalUsage ?? node.inputUsage ?? node.outputUsage) != null && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="secondary" className="cursor-default text-[10px] font-normal">
                  {formatTokenCounts(node.inputUsage, node.outputUsage, node.totalUsage)} tokens
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <UsageTooltipContent node={node} />
              </TooltipContent>
            </Tooltip>
          )}

          {node.model && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge variant="secondary" className="cursor-default text-[10px] font-normal">
                  {node.model}
                </Badge>
              </TooltipTrigger>
              {node.modelParameters && Object.keys(node.modelParameters).length > 0 && (
                <TooltipContent>
                  <div className="space-y-1 text-xs">
                    {Object.entries(node.modelParameters).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-4">
                        <span className="text-muted-foreground">{k}</span>
                        <span>{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </TooltipContent>
              )}
            </Tooltip>
          )}
        </TooltipProvider>

        {node.environment && (
          <Badge variant="secondary" className="text-[10px] font-normal">
            {node.environment}
          </Badge>
        )}

        {node.promptName && (
          <Badge variant="secondary" className="text-[10px] font-normal">
            {node.promptName}{node.promptVersion != null ? ` v${node.promptVersion}` : ''}
          </Badge>
        )}

        {node.level !== 'DEFAULT' && (
          <Badge
            variant={node.level === 'ERROR' ? 'destructive' : 'secondary'}
            className={cn(
              'text-[10px] font-normal',
              node.level === 'WARNING' && 'bg-yellow-100 text-yellow-700 hover:bg-yellow-100/80',
              node.level === 'DEBUG' && 'bg-gray-100 text-gray-600 hover:bg-gray-100/80',
            )}
          >
            {node.level}
          </Badge>
        )}

        {node.statusMessage && (
          <Badge
            variant={node.level === 'ERROR' ? 'destructive' : 'secondary'}
            className="max-w-[200px] truncate text-[10px] font-normal"
            title={node.statusMessage}
          >
            {node.statusMessage}
          </Badge>
        )}
      </div>
    </div>
  )
}
