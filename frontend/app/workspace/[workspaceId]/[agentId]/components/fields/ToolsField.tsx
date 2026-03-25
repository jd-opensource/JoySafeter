'use client'

import { Loader2, Check, Search, X, Hammer, Server } from 'lucide-react'
import { useState, useMemo } from 'react'


import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { useBuiltinTools } from '@/hooks/queries/tools'
import { useMcpTools } from '@/hooks/use-mcp-tools'
import { useTranslation } from '@/lib/i18n'
import { parseMcpToolId } from '@/lib/mcp/utils'
import { cn } from '@/lib/utils'

import { ToolOption } from '../../services/agentService'

interface ToolsValue {
  builtin?: string[]
  mcp?: string[]
}

interface ToolsFieldProps {
  value: unknown
  onChange: (val: unknown) => void
}

export function ToolsField({ value, onChange }: ToolsFieldProps) {
  const { t } = useTranslation()

  const [searchQuery, setSearchQuery] = useState('')

  // Use React Query hook for builtin tools (with caching and request deduplication)
  const { data: builtinToolsData = [], isLoading: isLoadingBuiltin } = useBuiltinTools()

  // MCP tools are loaded without workspace scoping (use global/default scope)
  const { mcpTools: availableMcp, isLoading: isLoadingMcp } = useMcpTools()

  const typedValue = value as ToolsValue | undefined
  const builtinTools = typedValue?.builtin || []
  const mcpTools = typedValue?.mcp || []

  // Convert BuiltinTool[] to ToolOption[] and filter out MCP tools (MCP tools use "::" as separator in registry)
  const availableBuiltin: ToolOption[] = useMemo(() => {
    return (builtinToolsData || [])
      .filter((t) => !t.id.includes('::'))
      .map((t) => ({
        id: t.id,
        label: t.label,
        description: t.description,
        name: t.name,
        toolType: t.toolType,
        category: t.category,
        tags: t.tags,
        mcpServer: t.mcpServer,
      }))
  }, [builtinToolsData])

  const isLoadingData = isLoadingBuiltin || isLoadingMcp

  const toggleBuiltin = (toolId: string) => {
    const current = new Set(builtinTools)
    if (current.has(toolId)) current.delete(toolId)
    else current.add(toolId)
    onChange({ ...typedValue, builtin: Array.from(current) })
  }

  const removeMcp = (uid: string) => {
    const current = mcpTools.filter((t: string) => t !== uid)
    onChange({ ...typedValue, mcp: current })
  }

  const toggleMcp = (toolId: string) => {
    const current = new Set(mcpTools)
    if (current.has(toolId)) current.delete(toolId)
    else current.add(toolId)
    onChange({ ...typedValue, mcp: Array.from(current) })
  }

  type ListedTool =
    | (ToolOption & { source: 'builtin' })
    | ({ id: string; label: string; description?: string } & { source: 'mcp' })

  const allTools: ListedTool[] = useMemo(() => {
    const builtinList: ListedTool[] = availableBuiltin.map((t) => ({
      ...t,
      source: 'builtin',
    }))

    const mcpList: ListedTool[] = availableMcp.map((t) => ({
      id: t.id, // labelName (server_name::tool_name) - used for management and display
      label: `${t.serverName}: ${t.name}`, // Display format: serverName: realToolName
      description: t.description,
      source: 'mcp',
    }))

    return [...builtinList, ...mcpList]
  }, [availableBuiltin, availableMcp])

  const filteredTools = useMemo(() => {
    if (!searchQuery.trim()) return allTools
    const q = searchQuery.toLowerCase()
    return allTools.filter(
      (t) => t.label.toLowerCase().includes(q) || t.description?.toLowerCase().includes(q),
    )
  }, [allTools, searchQuery])

  const getToolLabel = (id: string) => availableBuiltin.find((t) => t.id === id)?.label || id

  return (
    <div className="space-y-2">
      {/* 1. Selected Tags (STRICTLY ABOVE) */}
      {(builtinTools.length > 0 || mcpTools.length > 0) && (
        <div className="mb-2.5 flex flex-wrap gap-1.5">
          {builtinTools.map((id: string) => (
            <Badge
              key={id}
              variant="secondary"
              className="gap-1 border-primary/20 bg-primary/5 py-0.5 pl-2 pr-1 text-[10px] text-primary shadow-sm"
            >
              <Hammer size={10} className="shrink-0" />
              {getToolLabel(id)}
              <button
                onClick={() => toggleBuiltin(id)}
                className="ml-0.5 rounded-full p-0.5 transition-colors hover:bg-primary/20"
              >
                <X size={10} />
              </button>
            </Badge>
          ))}
          {mcpTools.map((toolId: string) => {
            const parsed = parseMcpToolId(toolId)
            const displayName = parsed ? parsed.toolName : toolId
            return (
              <Badge
                key={toolId}
                variant="secondary"
                className="gap-1 border-purple-200 bg-purple-50 py-0.5 pl-2 pr-1 text-[10px] text-purple-700 shadow-sm"
              >
                <Server size={10} className="shrink-0" />
                {displayName}
                <button
                  onClick={() => removeMcp(toolId)}
                  className="ml-0.5 rounded-full p-0.5 transition-colors hover:bg-purple-200"
                >
                  <X size={10} />
                </button>
              </Badge>
            )
          })}
        </div>
      )}

      {/* 2. Search Area */}
      <div className="group relative">
        <Search
          size={13}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] transition-colors group-focus-within:text-primary"
        />
        <Input
          placeholder={t('workspace.searchTools')}
          className="h-8 border-[var(--border)] bg-[var(--surface-elevated)] pl-8 text-[11px] shadow-none focus-visible:ring-primary/10"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* 3. Available Selection List */}
      <div className="custom-scrollbar mt-1 max-h-[160px] divide-y divide-[var(--border-muted)] overflow-y-auto rounded-lg border border-[var(--border-muted)] bg-[var(--surface-2)]">
        {isLoadingData ? (
          <div className="flex flex-col items-center justify-center gap-2 p-4 text-[var(--text-muted)]">
            <Loader2 size={14} className="animate-spin text-primary" />
            <span className="text-[10px] font-medium tracking-tight">
              {t('workspace.syncingCatalog')}
            </span>
          </div>
        ) : filteredTools.length === 0 ? (
          <div className="p-6 text-center text-[10px] italic text-[var(--text-muted)]">
            {searchQuery ? t('workspace.noMatchingCapabilities') : t('workspace.catalogEmpty')}
          </div>
        ) : (
          filteredTools.map((tool) => {
            const isBuiltin = tool.source === 'builtin'
            const isSelectedBuiltin = isBuiltin && builtinTools.includes(tool.id)
            const isSelectedMcp = !isBuiltin && mcpTools.includes(tool.id)
            const isSelected = isSelectedBuiltin || isSelectedMcp

            const handleClick = () => {
              if (isBuiltin) {
                toggleBuiltin(tool.id)
              } else {
                toggleMcp(tool.id)
              }
            }

            return (
              <div
                key={tool.id}
                onClick={handleClick}
                className={cn(
                  'group flex cursor-pointer items-center justify-between p-2 transition-all hover:bg-[var(--surface-elevated)]',
                  isSelected ? 'bg-[var(--surface-elevated)]' : '',
                )}
              >
                <div className="flex min-w-0 flex-col pr-2">
                  <div className="flex items-center gap-1.5">
                    {isBuiltin ? (
                      <Hammer
                        size={11}
                        className={isSelected ? 'text-primary' : 'text-[var(--text-subtle)]'}
                      />
                    ) : (
                      <Server
                        size={11}
                        className={isSelected ? 'text-purple-500' : 'text-[var(--text-subtle)]'}
                      />
                    )}
                    <span
                      className={cn(
                        'truncate text-[11px] font-medium',
                        isSelected ? 'text-primary' : 'text-[var(--text-secondary)]',
                      )}
                    >
                      {tool.label}
                    </span>
                  </div>
                  {tool.description && (
                    <p className="mt-0.5 truncate pl-4 text-[9px] text-[var(--text-muted)]">
                      {tool.description}
                    </p>
                  )}
                </div>
                <div
                  className={cn(
                    'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border shadow-sm transition-all',
                    isSelected
                      ? 'border-primary bg-primary text-white'
                      : 'border-[var(--border)] bg-[var(--surface-elevated)] group-hover:border-[var(--border-strong)]',
                  )}
                >
                  {isSelected && <Check size={10} strokeWidth={3} />}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
