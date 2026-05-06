'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getExpandedRowModel,
  flexRender,
  type ExpandedState,
} from '@tanstack/react-table'
import { ChevronRight, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  transformJsonToTableData,
  getRowChildren,
  getEmptyValueDisplay,
  findOptimalExpansionLevel,
  type JsonTableRow,
} from '../lib/jsonTable'
import { JsonValueCell } from './JsonValueCell'
import { JsonSectionHeader } from './JsonSectionHeader'
import { useObservationJsonExpansion } from '../contexts/ObservationJsonExpansionContext'

interface PrettyJsonViewProps {
  data: unknown
  title: string
  section: 'input' | 'output' | 'metadata'
}

export function PrettyJsonView({ data, title, section }: PrettyJsonViewProps) {
  const emptyDisplay = getEmptyValueDisplay(data)
  const { formattedExpansion, setFormattedFieldExpansion } = useObservationJsonExpansion()

  const [rows, setRows] = useState<JsonTableRow[]>(() =>
    emptyDisplay ? [] : transformJsonToTableData(data, '', 0, '', true),
  )

  const externalExpansion = formattedExpansion[section]

  const [expanded, setExpanded] = useState<ExpandedState>(() => {
    if (Object.keys(externalExpansion).length > 0) return externalExpansion
    const optimalLevel = findOptimalExpansionLevel(rows)
    return buildDefaultExpansion(rows, optimalLevel)
  })

  const [expandedCells, setExpandedCells] = useState<Set<string>>(new Set())
  const toggleCellExpansion = useCallback((cellId: string) => {
    setExpandedCells((prev) => {
      const next = new Set(prev)
      if (next.has(cellId)) next.delete(cellId)
      else next.add(cellId)
      return next
    })
  }, [])

  const persistExpansion = useRef(expanded)
  persistExpansion.current = expanded
  useEffect(() => {
    return () => {
      if (persistExpansion.current !== true) {
        setFormattedFieldExpansion(section, persistExpansion.current as Record<string, boolean>)
      }
    }
  }, [section, setFormattedFieldExpansion])

  const handleLazyLoad = useCallback((rowId: string) => {
    setRows((prev) => loadChildren(prev, rowId))
  }, [])

  const columns = useMemo(
    () => [
      {
        accessorKey: 'key' as const,
        header: 'Path',
        size: 35,
        cell: ({
          row,
        }: {
          row: {
            original: JsonTableRow
            getIsExpanded: () => boolean
            toggleExpanded: () => void
            depth: number
          }
        }) => {
          const indent = row.original.level * 16 + 8
          return (
            <div className="flex items-center font-mono text-xs" style={{ paddingLeft: indent }}>
              {row.original.hasChildren ? (
                <button
                  className="mr-1 flex h-4 w-4 shrink-0 items-center justify-center rounded hover:bg-muted"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (row.original.rawChildData && !row.original.childrenGenerated) {
                      handleLazyLoad(row.original.id)
                    }
                    row.toggleExpanded()
                  }}
                >
                  {row.getIsExpanded() ? (
                    <ChevronDown className="h-3 w-3" />
                  ) : (
                    <ChevronRight className="h-3 w-3" />
                  )}
                </button>
              ) : (
                <span className="mr-1 w-4 shrink-0" />
              )}
              <span className="font-medium">{row.original.key}</span>
            </div>
          )
        },
      },
      {
        accessorKey: 'value' as const,
        header: 'Value',
        size: 65,
        cell: ({ row }: { row: { original: JsonTableRow } }) => (
          <JsonValueCell
            row={row.original}
            expandedCells={expandedCells}
            toggleCellExpansion={toggleCellExpansion}
          />
        ),
      },
    ],
    [toggleCellExpansion, handleLazyLoad],
  )

  const table = useReactTable({
    data: rows,
    columns,
    state: { expanded },
    onExpandedChange: setExpanded,
    getSubRows: (row) => row.subRows,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowId: (row) => row.id,
  })

  const allExpanded = useMemo(() => {
    const flatRows = table.getRowModel().flatRows
    return (
      flatRows.length > 0 &&
      flatRows.filter((r) => r.original.hasChildren).every((r) => r.getIsExpanded())
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps -- table ref changes when expanded changes
  }, [table])

  const handleToggleExpandAll = useCallback(() => {
    if (allExpanded) {
      setExpanded({})
    } else {
      setRows((prev) => loadAllChildren(prev))
      const newExpanded: Record<string, boolean> = {}
      table.getRowModel().flatRows.forEach((row) => {
        if (row.original.hasChildren) newExpanded[row.id] = true
      })
      setExpanded(newExpanded)
    }
  }, [allExpanded, table])

  if (emptyDisplay) {
    return (
      <div className="border-b last:border-b-0">
        <JsonSectionHeader
          title={title}
          data={data}
          allExpanded={false}
          onToggleExpandAll={() => {}}
          showExpandButton={false}
        />
        <div className="px-3 pb-3 text-xs italic text-muted-foreground">{emptyDisplay}</div>
      </div>
    )
  }

  if (data == null) return null

  return (
    <div className="border-b last:border-b-0">
      <JsonSectionHeader
        title={title}
        data={data}
        allExpanded={allExpanded}
        onToggleExpandAll={handleToggleExpandAll}
      />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b bg-muted/30">
              <th className="w-[35%] px-3 py-1.5 text-left font-medium text-muted-foreground">
                Path
              </th>
              <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">Value</th>
            </tr>
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={cn(
                  'border-border/50 border-b transition-colors hover:bg-muted/30',
                  row.original.hasChildren && 'cursor-pointer',
                )}
                onClick={() => {
                  if (row.original.hasChildren) {
                    if (row.original.rawChildData && !row.original.childrenGenerated) {
                      handleLazyLoad(row.original.id)
                    }
                    row.toggleExpanded()
                  }
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-1.5 align-top">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function buildDefaultExpansion(rows: JsonTableRow[], maxLevel: number): Record<string, boolean> {
  const expansion: Record<string, boolean> = {}
  const stack = [...rows]
  while (stack.length > 0) {
    const row = stack.pop()!
    if (row.hasChildren && row.level < maxLevel) {
      expansion[row.id] = true
      if (row.subRows) stack.push(...row.subRows)
    }
  }
  return expansion
}

function loadChildren(rows: JsonTableRow[], targetId: string): JsonTableRow[] {
  return rows.map((row) => {
    if (row.id === targetId && row.rawChildData && !row.childrenGenerated) {
      return { ...row, subRows: getRowChildren(row), childrenGenerated: true }
    }
    if (row.subRows) {
      const updated = loadChildren(row.subRows, targetId)
      if (updated !== row.subRows) return { ...row, subRows: updated }
    }
    return row
  })
}

function loadAllChildren(rows: JsonTableRow[]): JsonTableRow[] {
  return rows.map((row) => {
    let updated = row
    if (row.hasChildren && row.rawChildData && !row.childrenGenerated) {
      updated = { ...row, subRows: getRowChildren(row), childrenGenerated: true }
    }
    if (updated.subRows) {
      const childrenUpdated = loadAllChildren(updated.subRows)
      if (childrenUpdated !== updated.subRows) {
        updated =
          updated === row
            ? { ...row, subRows: childrenUpdated }
            : { ...updated, subRows: childrenUpdated }
      }
    }
    return updated
  })
}
