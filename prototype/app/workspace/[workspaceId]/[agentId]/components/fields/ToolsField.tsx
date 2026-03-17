'use client'

import { Loader2, Check, Search, X, Hammer, Server } from 'lucide-react'
import React, { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { useBuiltinTools } from '@/hooks/queries/tools'
import { useMcpTools } from '@/hooks/use-mcp-tools'
import { cn } from '@/lib/core/utils/cn'
import { parseMcpToolId } from '@/lib/mcp/utils'

import { ToolOption } from '../../services/agentService'

interface ToolsValue {
  builtin?: string[]
  mcp?: string[]
}

interface ToolsFieldProps {
  value: unknown
  onChange: (val: unknown) => void
}

export const ToolsField: React.FC<ToolsFieldProps> = ({ value, onChange }) => {
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
      (t) =>
        t.label.toLowerCase().includes(q) ||
        t.description?.toLowerCase().includes(q)
    )
  }, [allTools, searchQuery])

  const getToolLabel = (id: string) => availableBuiltin.find((t) => t.id === id)?.label || id

  return (
    <div className="space-y-2">
      {/* 1. Selected Tags (STRICTLY ABOVE) */}
      {(builtinTools.length > 0 || mcpTools.length > 0) && (
        <div className="flex flex-wrap gap-1.5 mb-2.5">
          {builtinTools.map((id: string) => (
            <Badge
              key={id}
              variant="secondary"
              className="pl-2 pr-1 py-0.5 gap-1 text-[10px] bg-blue-50 text-blue-700 border-blue-200 shadow-sm"
            >
              <Hammer size={10} className="shrink-0" />
              {getToolLabel(id)}
              <button
                onClick={() => toggleBuiltin(id)}
                className="ml-0.5 p-0.5 hover:bg-blue-200 rounded-full transition-colors"
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
                className="pl-2 pr-1 py-0.5 gap-1 text-[10px] bg-purple-50 text-purple-700 border-purple-200 shadow-sm"
              >
                <Server size={10} className="shrink-0" />
                {displayName}
                <button
                  onClick={() => removeMcp(toolId)}
                  className="ml-0.5 p-0.5 hover:bg-purple-200 rounded-full transition-colors"
                >
                  <X size={10} />
                </button>
              </Badge>
            )
          })}
        </div>
      )}

      {/* 2. Search Area */}
      <div className="relative group">
        <Search
          size={13}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-blue-500 transition-colors"
        />
                <Input
                  placeholder={t('workspace.searchTools')}
                  className="pl-8 h-8 text-[11px] border-gray-200 bg-white shadow-none focus-visible:ring-blue-100"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
      </div>

      {/* 3. Available Selection List */}
      <div className="max-h-[160px] overflow-y-auto custom-scrollbar border border-gray-100 rounded-lg divide-y divide-gray-50 bg-gray-50/30 mt-1">
        {isLoadingData ? (
          <div className="p-4 flex flex-col items-center justify-center gap-2 text-gray-400">
            <Loader2 size={14} className="animate-spin text-blue-500" />
                        <span className="text-[10px] font-medium tracking-tight">
                          {t('workspace.syncingCatalog')}
                        </span>
          </div>
        ) : filteredTools.length === 0 ? (
          <div className="p-6 text-center text-[10px] text-gray-400 italic">
                    {searchQuery
                      ? t('workspace.noMatchingCapabilities')
                      : t('workspace.catalogEmpty')}
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
                  'p-2 flex items-center justify-between cursor-pointer transition-all hover:bg-white group',
                  isSelected ? 'bg-white' : ''
                )}
              >
                <div className="flex flex-col min-w-0 pr-2">
                  <div className="flex items-center gap-1.5">
                    {isBuiltin ? (
                      <Hammer
                        size={11}
                        className={isSelected ? 'text-blue-500' : 'text-gray-300'}
                      />
                    ) : (
                      <Server
                        size={11}
                        className={isSelected ? 'text-purple-500' : 'text-gray-300'}
                      />
                    )}
                    <span
                      className={cn(
                        'text-[11px] font-medium truncate',
                        isSelected ? 'text-blue-700' : 'text-gray-600'
                      )}
                    >
                      {tool.label}
                    </span>
                  </div>
                  {tool.description && (
                    <p className="text-[9px] text-gray-400 truncate mt-0.5 pl-4">
                      {tool.description}
                    </p>
                  )}
                </div>
                <div
                  className={cn(
                    'w-4 h-4 rounded-full border flex items-center justify-center transition-all shrink-0 shadow-sm',
                    isSelected
                      ? 'bg-blue-500 border-blue-600 text-white'
                      : 'border-gray-200 bg-white group-hover:border-gray-300'
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
