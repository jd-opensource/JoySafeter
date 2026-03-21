/**
 * MCP Server Card Component
 * 可复用的 MCP 服务器卡片组件
 */
'use client'

import { Server, MoreHorizontal, Wrench, Edit2, Trash2, Ban, Check } from 'lucide-react'
import React from 'react'


import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { McpServer } from '@/hooks/queries/mcp'
import { useTranslation } from '@/lib/i18n'
import { getConnectionStatusIcon, getConnectionStatusText, formatToolCount } from '@/lib/mcp/utils'
import { cn } from '@/lib/utils'

interface McpServerCardProps {
  server: McpServer
  toolCount?: number
  onEdit?: (server: McpServer) => void
  onToggleEnabled?: (server: McpServer) => void
  onDelete?: (serverId: string) => void
  isUpdating?: boolean
  isDeleting?: boolean
}

interface BuiltinToolCardProps {
  id: string
  label: string
  name?: string
  description?: string
  toolType?: string
  category?: string | null
  tags?: string[]
}

/**
 * MCP Server Card Component
 */
export function McpServerCard({
  server,
  toolCount,
  onEdit,
  onToggleEnabled,
  onDelete,
  isUpdating = false,
  isDeleting = false,
}: McpServerCardProps) {
  const { t } = useTranslation()
  const connectionStatus = server.connectionStatus || 'disconnected'
  const isActive = server.enabled
  const displayToolCount = toolCount ?? server.toolCount ?? 0

  return (
    <div className="group flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition-all hover:border-blue-200 hover:shadow-md">
      <div className="flex items-center gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-purple-100 bg-purple-50 text-purple-600">
          <Server size={18} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-gray-900">{server.name}</h3>
            <Badge
              variant="outline"
              className="border-purple-100 bg-purple-50 px-1.5 py-0 text-[9px] text-purple-600"
            >
              {t('settings.mcpTag')}
            </Badge>
          </div>
          <div className="mt-0.5 flex items-center gap-3">
            <p className="text-xs text-gray-500">
              {server.url || `${t('settings.transport')}: ${server.transport}`}
            </p>
            {displayToolCount > 0 && (
              <Badge
                variant="outline"
                className="border-blue-100 bg-blue-50 px-1.5 py-0 text-[9px] text-blue-600"
              >
                {formatToolCount(displayToolCount, t)}
              </Badge>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Connection Status */}
        <div className="flex items-center gap-1.5 rounded-md border border-gray-100 bg-gray-50 px-2 py-1">
          {getConnectionStatusIcon(connectionStatus)}
          <span className="text-[10px] font-medium text-gray-600">
            {getConnectionStatusText(connectionStatus, t)}
          </span>
        </div>

        {/* Active Status */}
        <div className="flex items-center gap-1.5 rounded-md border border-gray-100 bg-gray-50 px-2 py-1">
          <div
            className={cn('h-1.5 w-1.5 rounded-full', isActive ? 'bg-emerald-500' : 'bg-gray-300')}
          />
          <span className="text-[10px] font-medium uppercase text-gray-600">
            {isActive ? t('settings.active') : t('settings.inactive')}
          </span>
        </div>

        {/* Actions Menu */}
        {(onEdit || onToggleEnabled || onDelete) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-gray-400 hover:text-gray-900"
              >
                <MoreHorizontal size={16} />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {onEdit && (
                <DropdownMenuItem onClick={() => onEdit(server)}>
                  <Edit2 size={14} className="mr-2" />
                  {t('settings.edit')}
                </DropdownMenuItem>
              )}
              {onToggleEnabled && (
                <DropdownMenuItem onClick={() => onToggleEnabled(server)} disabled={isUpdating}>
                  {server.enabled ? (
                    <Ban size={14} className="mr-2" />
                  ) : (
                    <Check size={14} className="mr-2" />
                  )}
                  {server.enabled ? t('settings.disable') : t('settings.enable')}
                </DropdownMenuItem>
              )}
              {onDelete && (
                <DropdownMenuItem
                  onClick={() => onDelete(server.id)}
                  className="text-red-600 focus:text-red-600"
                  disabled={isDeleting}
                >
                  <Trash2 size={14} className="mr-2" />
                  {t('settings.delete')}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  )
}

/**
 * Builtin Tool Card Component
 */
export function BuiltinToolCard({
  id,
  label,
  name,
  description,
  _toolType,
  _category,
  _tags,
}: BuiltinToolCardProps) {
  const { t } = useTranslation()
  const displayName = label || name || id
  const fullDescription = description || ''
  const maxLength = 100
  const truncatedDescription =
    fullDescription.length > maxLength
      ? `${fullDescription.slice(0, maxLength)}…`
      : fullDescription || t('settings.noDescription')

  return (
    <TooltipProvider>
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <div className="group flex cursor-default items-center justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition-all hover:border-blue-200 hover:shadow-md">
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-100 bg-blue-50 text-blue-600">
                <Wrench size={18} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-gray-900">{displayName}</h3>
                  <Badge
                    variant="outline"
                    className="bg-gray-100 px-1.5 py-0 text-[9px] text-gray-500"
                  >
                    {t('settings.builtinTag')}
                  </Badge>
                </div>
                <p className="mt-0.5 text-xs text-gray-500">{truncatedDescription}</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 rounded-md border border-gray-100 bg-gray-50 px-2 py-1">
                <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                <span className="text-[10px] font-medium uppercase text-gray-600">
                  {t('settings.active')}
                </span>
              </div>
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          align="start"
          className="max-w-[90vw] space-y-1 rounded-md border border-gray-200 bg-white p-3 text-gray-900 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-50 sm:max-w-md"
        >
          <div className="text-[11px] font-semibold">{name || label || id}</div>
          {fullDescription && (
            <div className="whitespace-pre-line text-[11px] text-gray-700 dark:text-slate-100/80">
              {fullDescription}
            </div>
          )}
          <div className="pt-1 text-[9px] text-primary-foreground/60">ID: {id}</div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
