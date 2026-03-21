'use client'

import {
  Database,
  Copy,
  Check,
  AlertCircle,
  Info,
  Eye,
  X,
  Loader2,
  GitBranch,
  Layers,
} from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useMemo, useState, useEffect } from 'react'
import { Node, Edge } from 'reactflow'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { SearchInput } from '@/components/ui/search-input'
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet'
import { useToast } from '@/components/ui/use-toast'
import { cn } from '@/lib/utils'

import { getNodeAvailableVariables, getGraphVariables } from '../services/variableService'

interface VariableInfo {
  name: string
  path: string
  source: string
  source_node_id?: string
  scope: 'global' | 'loop' | 'task' | 'node'
  description?: string
  value_type?: string
  is_defined: boolean
  is_used: boolean
  usages?: Array<{
    node_id: string
    node_label: string
    usage_type: string
  }>
}

interface StateVariablePanelProps {
  nodes: Node[]
  edges: Edge[]
  selectedNodeId?: string | null
  onVariableSelect?: (variablePath: string) => void
  onClose?: () => void
}

export function StateVariablePanel({
  nodes,
  edges,
  selectedNodeId,
  onVariableSelect,
  onClose,
}: StateVariablePanelProps) {
  const { toast } = useToast()
  const params = useParams()
  const graphId = params.agentId as string
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedScope, setSelectedScope] = useState<'all' | 'global' | 'loop' | 'task' | 'node'>(
    'all',
  )
  const [copiedPath, setCopiedPath] = useState<string | null>(null)
  const [variables, setVariables] = useState<VariableInfo[]>([])
  const [isLoading, setIsLoading] = useState(false)

  // Fetch variable information from backend API
  useEffect(() => {
    const fetchVariables = async () => {
      if (!graphId) {
        // Fallback to frontend analysis
        setVariables(analyzeVariables(nodes, edges, selectedNodeId))
        return
      }

      setIsLoading(true)
      try {
        if (selectedNodeId) {
          // Get available variables for the node
          const vars = await getNodeAvailableVariables(graphId, selectedNodeId)
          setVariables(vars)
        } else {
          // Get all variables
          const vars = await getGraphVariables(graphId)
          setVariables(vars)
        }
      } catch (error) {
        console.error('Failed to fetch variables:', error)
        // Fallback to frontend analysis
        setVariables(analyzeVariables(nodes, edges, selectedNodeId))
      } finally {
        setIsLoading(false)
      }
    }

    fetchVariables()
  }, [graphId, nodes, edges, selectedNodeId])

  // Filter variables
  const filteredVariables = useMemo(() => {
    let filtered = variables

    // Filter by scope
    if (selectedScope !== 'all') {
      filtered = filtered.filter((v) => v.scope === selectedScope)
    }

    // Filter by search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(
        (v) =>
          v.name.toLowerCase().includes(query) ||
          v.path.toLowerCase().includes(query) ||
          v.source.toLowerCase().includes(query) ||
          v.description?.toLowerCase().includes(query),
      )
    }

    return filtered
  }, [variables, selectedScope, searchQuery])

  // Group by scope
  const groupedVariables = useMemo(() => {
    const groups: Record<string, VariableInfo[]> = {
      global: [],
      loop: [],
      task: [],
      node: [],
    }

    filteredVariables.forEach((v) => {
      groups[v.scope].push(v)
    })

    return groups
  }, [filteredVariables])

  const handleCopyPath = (path: string) => {
    navigator.clipboard.writeText(path)
    setCopiedPath(path)
    toast({
      title: 'Copied',
      description: `Variable path copied: ${path}`,
    })
    setTimeout(() => setCopiedPath(null), 2000)
  }

  const handleVariableClick = (variable: VariableInfo) => {
    if (onVariableSelect) {
      onVariableSelect(variable.path)
    }
  }

  const getScopeColor = (scope: string) => {
    switch (scope) {
      case 'global':
        return 'bg-blue-50/80 text-blue-700 border-blue-200/60 dark:bg-blue-950/30 dark:text-blue-400 dark:border-blue-800/40'
      case 'loop':
        return 'bg-cyan-50/80 text-cyan-700 border-cyan-200/60 dark:bg-cyan-950/30 dark:text-cyan-400 dark:border-cyan-800/40'
      case 'task':
        return 'bg-purple-50/80 text-purple-700 border-purple-200/60 dark:bg-purple-950/30 dark:text-purple-400 dark:border-purple-800/40'
      case 'node':
        return 'bg-emerald-50/80 text-emerald-700 border-emerald-200/60 dark:bg-emerald-950/30 dark:text-emerald-400 dark:border-emerald-800/40'
      default:
        return 'bg-gray-50/80 text-gray-700 border-gray-200/60 dark:bg-gray-950/30 dark:text-gray-400 dark:border-gray-800/40'
    }
  }

  const getScopeIcon = (scope: string) => {
    switch (scope) {
      case 'global':
        return <Database size={11} className="shrink-0" />
      case 'loop':
        return <GitBranch size={11} className="shrink-0" />
      case 'task':
        return <Layers size={11} className="shrink-0" />
      case 'node':
        return <Info size={11} className="shrink-0" />
      default:
        return <Info size={11} className="shrink-0" />
    }
  }

  const getScopeLabel = (scope: string) => {
    switch (scope) {
      case 'global':
        return 'Global'
      case 'loop':
        return 'Loop'
      case 'task':
        return 'Task'
      case 'node':
        return 'Node'
      default:
        return scope
    }
  }

  return (
    <Sheet open={true} onOpenChange={(open) => !open && onClose?.()}>
      <SheetContent
        side="left"
        className="flex w-[420px] flex-col border-r border-[var(--border)] bg-[var(--surface-2)] p-0 sm:max-w-[420px]"
      >
        {/* Header */}
        <div className="shrink-0 border-b border-[var(--border)] bg-gradient-to-r from-blue-50/50 to-indigo-50/50 px-4 py-3.5 backdrop-blur-sm dark:from-blue-950/20 dark:to-indigo-950/20">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-indigo-500 shadow-sm">
                <Database size={16} className="text-white" />
              </div>
              <div className="flex flex-col">
                <SheetTitle className="text-sm font-semibold leading-tight text-[var(--text-primary)]">
                  State Variables
                </SheetTitle>
                {selectedNodeId && (
                  <SheetDescription className="mt-0.5 text-[10px] leading-tight text-[var(--text-muted)]">
                    Available variables for selected node
                  </SheetDescription>
                )}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onClose?.()}
              className="h-7 w-7 text-[var(--text-muted)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]"
            >
              <X size={14} />
            </Button>
          </div>
        </div>

        {/* Search and Filter */}
        <div className="shrink-0 space-y-2.5 border-b border-[var(--border)] bg-[var(--surface-1)] px-4 py-3">
          <SearchInput
            placeholder="Search variables..."
            value={searchQuery}
            onValueChange={setSearchQuery}
            className="focus-within:border-[var(--brand-500)]/40 bg-[var(--surface-2)] transition-all focus-within:bg-[var(--surface-elevated)] focus-within:shadow-sm hover:bg-[var(--surface-3)]"
          />
          <div className="flex flex-wrap gap-1.5">
            {(['all', 'global', 'loop', 'task', 'node'] as const).map((scope) => (
              <Button
                key={scope}
                variant={selectedScope === scope ? 'default' : 'outline'}
                size="sm"
                onClick={() => setSelectedScope(scope)}
                className={cn(
                  'h-7 px-2.5 text-xs font-medium transition-all',
                  selectedScope === scope
                    ? 'hover:bg-[var(--brand-500)]/90 bg-[var(--brand-500)] text-white shadow-sm'
                    : 'border-[var(--border)] bg-[var(--surface-2)] text-[var(--text-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]',
                )}
              >
                {scope === 'all' ? 'All' : getScopeLabel(scope)}
              </Button>
            ))}
          </div>
        </div>

        {/* Variables List */}
        <ScrollArea className="flex-1">
          <div className="space-y-5 p-4">
            {isLoading ? (
              <div className="flex flex-col items-center justify-center py-12 text-[var(--text-muted)]">
                <Loader2 size={24} className="mb-3 animate-spin opacity-50" />
                <div className="text-xs font-medium">Loading variables...</div>
              </div>
            ) : filteredVariables.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-[var(--text-muted)]">
                <AlertCircle size={32} className="mb-3 opacity-40" />
                <div className="mb-1 text-xs font-medium">No variables found</div>
                {searchQuery && (
                  <div className="text-[10px] opacity-70">Try using different search terms</div>
                )}
              </div>
            ) : (
              <>
                {/* Global Variables */}
                {groupedVariables.global.length > 0 && (
                  <div className="space-y-2.5">
                    <div className="mb-2 flex items-center gap-2 px-1">
                      <div className="flex h-5 w-5 items-center justify-center rounded-md bg-blue-100 dark:bg-blue-950/40">
                        <Database size={11} className="text-blue-600 dark:text-blue-400" />
                      </div>
                      <Label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                        Global Variables
                      </Label>
                      <Badge
                        variant="secondary"
                        className="ml-auto h-4 border-0 bg-blue-50 px-1.5 text-[10px] text-blue-700 dark:bg-blue-950/30 dark:text-blue-400"
                      >
                        {groupedVariables.global.length}
                      </Badge>
                    </div>
                    {groupedVariables.global.map((variable) => (
                      <VariableItem
                        key={variable.path}
                        variable={variable}
                        onCopy={handleCopyPath}
                        onClick={handleVariableClick}
                        copiedPath={copiedPath}
                        getScopeColor={getScopeColor}
                        getScopeIcon={getScopeIcon}
                        getScopeLabel={getScopeLabel}
                      />
                    ))}
                  </div>
                )}

                {/* Loop Variables */}
                {groupedVariables.loop.length > 0 && (
                  <div className="space-y-2.5">
                    <div className="mb-2 flex items-center gap-2 px-1">
                      <div className="flex h-5 w-5 items-center justify-center rounded-md bg-cyan-100 dark:bg-cyan-950/40">
                        <GitBranch size={11} className="text-cyan-600 dark:text-cyan-400" />
                      </div>
                      <Label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                        Loop Variables
                      </Label>
                      <Badge
                        variant="secondary"
                        className="ml-auto h-4 border-0 bg-cyan-50 px-1.5 text-[10px] text-cyan-700 dark:bg-cyan-950/30 dark:text-cyan-400"
                      >
                        {groupedVariables.loop.length}
                      </Badge>
                    </div>
                    {groupedVariables.loop.map((variable) => (
                      <VariableItem
                        key={variable.path}
                        variable={variable}
                        onCopy={handleCopyPath}
                        onClick={handleVariableClick}
                        copiedPath={copiedPath}
                        getScopeColor={getScopeColor}
                        getScopeIcon={getScopeIcon}
                        getScopeLabel={getScopeLabel}
                      />
                    ))}
                  </div>
                )}

                {/* Task Variables */}
                {groupedVariables.task.length > 0 && (
                  <div className="space-y-2.5">
                    <div className="mb-2 flex items-center gap-2 px-1">
                      <div className="flex h-5 w-5 items-center justify-center rounded-md bg-purple-100 dark:bg-purple-950/40">
                        <Layers size={11} className="text-purple-600 dark:text-purple-400" />
                      </div>
                      <Label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                        Task Variables
                      </Label>
                      <Badge
                        variant="secondary"
                        className="ml-auto h-4 border-0 bg-purple-50 px-1.5 text-[10px] text-purple-700 dark:bg-purple-950/30 dark:text-purple-400"
                      >
                        {groupedVariables.task.length}
                      </Badge>
                    </div>
                    {groupedVariables.task.map((variable) => (
                      <VariableItem
                        key={variable.path}
                        variable={variable}
                        onCopy={handleCopyPath}
                        onClick={handleVariableClick}
                        copiedPath={copiedPath}
                        getScopeColor={getScopeColor}
                        getScopeIcon={getScopeIcon}
                        getScopeLabel={getScopeLabel}
                      />
                    ))}
                  </div>
                )}

                {/* Node Variables */}
                {groupedVariables.node.length > 0 && (
                  <div className="space-y-2.5">
                    <div className="mb-2 flex items-center gap-2 px-1">
                      <div className="flex h-5 w-5 items-center justify-center rounded-md bg-emerald-100 dark:bg-emerald-950/40">
                        <Info size={11} className="text-emerald-600 dark:text-emerald-400" />
                      </div>
                      <Label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                        Node Variables
                      </Label>
                      <Badge
                        variant="secondary"
                        className="ml-auto h-4 border-0 bg-emerald-50 px-1.5 text-[10px] text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400"
                      >
                        {groupedVariables.node.length}
                      </Badge>
                    </div>
                    {groupedVariables.node.map((variable) => (
                      <VariableItem
                        key={variable.path}
                        variable={variable}
                        onCopy={handleCopyPath}
                        onClick={handleVariableClick}
                        copiedPath={copiedPath}
                        getScopeColor={getScopeColor}
                        getScopeIcon={getScopeIcon}
                        getScopeLabel={getScopeLabel}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}

interface VariableItemProps {
  variable: VariableInfo
  onCopy: (path: string) => void
  onClick?: (variable: VariableInfo) => void
  copiedPath: string | null
  getScopeColor: (scope: string) => string
  getScopeIcon: (scope: string) => React.ReactNode
  getScopeLabel: (scope: string) => string
}

function VariableItem({
  variable,
  onCopy,
  onClick,
  copiedPath,
  getScopeColor,
  getScopeIcon,
  getScopeLabel,
}: VariableItemProps) {
  return (
    <div
      className={cn(
        'group relative rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3.5',
        'hover:border-[var(--brand-500)]/30 cursor-pointer hover:bg-[var(--surface-3)]',
        'shadow-sm transition-all duration-200 hover:shadow-md',
        onClick && 'hover:shadow-[0_0_0_1px_var(--brand-500)/20]',
      )}
      onClick={() => onClick?.(variable)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-2">
          {/* Header: Name and Scope Badge */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-[var(--text-primary)]">
              {variable.name}
            </span>
            <Badge
              variant="outline"
              className={cn(
                'flex h-5 items-center gap-1 rounded-md border px-1.5 text-[10px] font-medium',
                getScopeColor(variable.scope),
              )}
            >
              {getScopeIcon(variable.scope)}
              <span>{getScopeLabel(variable.scope)}</span>
            </Badge>
          </div>

          {/* Variable Path */}
          <div className="border-[var(--border)]/50 break-all rounded border bg-[var(--surface-2)] px-2 py-1.5 font-mono text-xs text-[var(--text-tertiary)]">
            {variable.path}
          </div>

          {/* Description */}
          {variable.description && (
            <div className="text-xs leading-relaxed text-[var(--text-secondary)]">
              {variable.description}
            </div>
          )}

          {/* Footer: Source and Type */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-muted)]">
              <span className="opacity-70">Source:</span>
              <span className="font-medium">{variable.source}</span>
            </div>
            {variable.value_type && (
              <Badge
                variant="secondary"
                className="h-4 border-0 bg-[var(--surface-3)] px-1.5 text-[10px] font-normal text-[var(--text-tertiary)]"
              >
                {variable.value_type}
              </Badge>
            )}
          </div>

          {/* Usages */}
          {variable.usages && variable.usages.length > 0 && (
            <div className="flex items-center gap-1.5 pt-0.5 text-[10px] text-[var(--text-muted)]">
              <Eye size={10} className="opacity-60" />
              <span>Used in {variable.usages.length} node(s)</span>
            </div>
          )}
        </div>

        {/* Copy Button */}
        <Button
          variant="ghost"
          size="icon"
          onClick={(e) => {
            e.stopPropagation()
            onCopy(variable.path)
          }}
          className={cn(
            'h-7 w-7 shrink-0 rounded-md p-0',
            'text-[var(--text-muted)] hover:text-[var(--text-primary)]',
            'transition-colors hover:bg-[var(--surface-4)]',
            'opacity-0 group-hover:opacity-100',
          )}
          title="Copy path"
        >
          {copiedPath === variable.path ? (
            <Check size={13} className="text-emerald-600 dark:text-emerald-400" />
          ) : (
            <Copy size={13} />
          )}
        </Button>
      </div>
    </div>
  )
}

// Frontend variable analysis function (simplified version, should call backend API in production)
function analyzeVariables(
  nodes: Node[],
  _edges: Edge[],
  _selectedNodeId?: string | null,
): VariableInfo[] {
  const variables: VariableInfo[] = []

  // Add system global variables
  variables.push({
    name: 'current_node',
    path: 'state.current_node',
    source: 'System',
    scope: 'global',
    description: 'Current executing node ID',
    value_type: 'string',
    is_defined: true,
    is_used: false,
  })

  variables.push({
    name: 'route_decision',
    path: 'state.route_decision',
    source: 'System',
    scope: 'global',
    description: 'Latest route decision from router/condition nodes',
    value_type: 'string',
    is_defined: true,
    is_used: false,
  })

  variables.push({
    name: 'loop_count',
    path: 'state.loop_count',
    source: 'System',
    scope: 'global',
    description: 'Global loop iteration count',
    value_type: 'number',
    is_defined: true,
    is_used: false,
  })

  // Analyze node configurations to extract variables
  nodes.forEach((node) => {
    const nodeData = node.data as {
      type?: string
      label?: string
      config?: Record<string, unknown>
    }
    const nodeType = nodeData.type || 'agent'
    const nodeLabel = nodeData.label || node.id
    const config = nodeData.config || {}

    // Analyze Router node
    if (nodeType === 'router_node') {
      const rules = (config.rules as Array<Record<string, unknown>>) || []
      rules.forEach((rule) => {
        const condition = rule.condition as string
        if (condition) {
          extractVariablesFromExpression(condition).forEach((varName) => {
            if (!variables.find((v) => v.name === varName)) {
              variables.push({
                name: varName,
                path: `state.${varName}`,
                source: nodeLabel,
                source_node_id: node.id,
                scope: 'global',
                is_defined: false,
                is_used: true,
              })
            }
          })
        }
      })
    }

    // Analyze Loop Condition node
    if (nodeType === 'loop_condition_node') {
      variables.push({
        name: `loop_count_${node.id}`,
        path: `loop_states.${node.id}.loop_count`,
        source: nodeLabel,
        source_node_id: node.id,
        scope: 'loop',
        description: `Loop count for loop '${nodeLabel}'`,
        value_type: 'number',
        is_defined: true,
        is_used: false,
      })
    }

    // Analyze Tool node
    if (nodeType === 'tool_node') {
      const inputMapping = (config.input_mapping as Record<string, string>) || {}
      Object.values(inputMapping).forEach((expression) => {
        extractVariablesFromExpression(expression).forEach((varName) => {
          if (!variables.find((v) => v.name === varName)) {
            variables.push({
              name: varName,
              path: `context.${varName}`,
              source: nodeLabel,
              source_node_id: node.id,
              scope: 'global',
              is_defined: false,
              is_used: true,
            })
          }
        })
      })
    }
  })

  return variables
}

function extractVariablesFromExpression(expression: string): string[] {
  const variables: string[] = []
  const patterns = [
    /state\.get\(['"]([^'"]+)['"]/g,
    /context\.get\(['"]([^'"]+)['"]/g,
    /state\[['"]([^'"]+)['"]/g,
    /context\[['"]([^'"]+)['"]/g,
  ]

  patterns.forEach((pattern) => {
    let match
    while ((match = pattern.exec(expression)) !== null) {
      variables.push(match[1])
    }
  })

  return [...new Set(variables)]
}
