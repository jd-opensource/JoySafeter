/**
 * MCP Server Card Component
 * 可复用的 MCP 服务器卡片组件
 */
'use client'

import { Server, MoreHorizontal, Wrench, Edit2, Trash2, Ban, Check } from 'lucide-react'
import React from 'react'
import { useTranslation } from 'react-i18next'

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
import {
  getConnectionStatusIcon,
  getConnectionStatusText,
  formatToolCount,
} from '@/lib/mcp/utils'
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
    <div className="surface-panel-flat group flex items-center justify-between gap-4 p-4 transition duration-200 hover:border-[var(--border-hover)] hover:bg-white">
      <div className="flex items-center gap-4">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--divider)] bg-white/80 text-[var(--brand-500)]">
          <Server size={18} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold tracking-[-0.02em] text-[var(--text-primary)]">
              {server.name}
            </h3>
            <Badge
              variant="outline"
              className="border-[var(--divider)] bg-white/80 px-2 py-0 text-[9px] uppercase tracking-[0.16em] text-[var(--text-secondary)]"
            >
              {t('settings.mcpTag')}
            </Badge>
          </div>
          <div className="flex items-center gap-3 mt-0.5">
            <p className="text-xs text-[var(--text-secondary)]">
              {server.url || `${t('settings.transport')}: ${server.transport}`}
            </p>
            {displayToolCount > 0 && (
              <Badge
                variant="outline"
                className="border-[rgba(54,93,130,0.16)] bg-[rgba(54,93,130,0.08)] px-2 py-0 text-[9px] uppercase tracking-[0.16em] text-[var(--status-running)]"
              >
                {formatToolCount(displayToolCount, t)}
              </Badge>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Connection Status */}
        <div className="flex items-center gap-1.5 rounded-full border border-[var(--divider)] bg-white/80 px-3 py-1.5">
          {getConnectionStatusIcon(connectionStatus)}
          <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-secondary)]">
            {getConnectionStatusText(connectionStatus, t)}
          </span>
        </div>

        {/* Active Status */}
        <div className="flex items-center gap-1.5 rounded-full border border-[var(--divider)] bg-white/80 px-3 py-1.5">
          <div
            className={cn(
              'w-1.5 h-1.5 rounded-full',
              isActive ? 'bg-[var(--status-healthy)]' : 'bg-[var(--text-subtle)]'
            )}
          />
          <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-secondary)]">
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
                className="h-8 w-8 rounded-full text-[var(--text-muted)] hover:bg-white hover:text-[var(--text-primary)]"
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
                <DropdownMenuItem
                  onClick={() => onToggleEnabled(server)}
                  disabled={isUpdating}
                >
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
  toolType,
  category,
  tags,
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
          <div className="surface-panel-flat group flex cursor-default items-center justify-between gap-4 p-4 transition duration-200 hover:border-[var(--border-hover)] hover:bg-white">
            <div className="flex items-center gap-4">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--divider)] bg-white/80 text-[var(--brand-500)]">
                <Wrench size={18} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold tracking-[-0.02em] text-[var(--text-primary)]">
                    {displayName}
                  </h3>
                  <Badge
                    variant="outline"
                    className="border-[var(--divider)] bg-white/80 px-2 py-0 text-[9px] uppercase tracking-[0.16em] text-[var(--text-secondary)]"
                  >
                    {t('settings.builtinTag')}
                  </Badge>
                </div>
                <p className="mt-0.5 text-xs text-[var(--text-secondary)]">{truncatedDescription}</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 rounded-full border border-[var(--divider)] bg-white/80 px-3 py-1.5">
                <div className="h-1.5 w-1.5 rounded-full bg-[var(--status-healthy)]" />
                <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-secondary)]">
                  {t('settings.active')}
                </span>
              </div>
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          align="start"
          className="max-w-[90vw] space-y-1 rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] p-3 text-[var(--text-primary)] shadow-[0_18px_32px_rgba(15,23,42,0.08)] sm:max-w-md"
        >
          <div className="text-[11px] font-semibold">{name || label || id}</div>
          {fullDescription && (
            <div className="whitespace-pre-line text-[11px] text-[var(--text-secondary)]">
              {fullDescription}
            </div>
          )}
          <div className="pt-1 text-[9px] uppercase tracking-[0.14em] text-[var(--text-muted)]">
            ID: {id}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
