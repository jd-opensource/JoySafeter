'use client'

import { useMemo, useState, type ReactNode } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
  type ColumnResizeMode,
} from '@tanstack/react-table'
import { useTranslation } from '@/lib/i18n'
import { Pagination } from '@/components/ui/pagination'
import { ActionMenu, type MenuItem } from './action-menu'

// ── Public API (unchanged — all 15 consumers keep working) ─────────────

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  className?: string
  headerClassName?: string
  cellClassName?: string
  align?: 'left' | 'center' | 'right'
  truncate?: boolean
  width?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  loading?: boolean
  fetching?: boolean
  onRowClick?: (row: T) => void
  actionMenu?: (row: T) => MenuItem[]
  selectable?: boolean
  pagination?: {
    hasNext: boolean
    hasPrev: boolean
    onNext: () => void
    onPrev: () => void
    page?: number
    totalPages?: number
    onPageChange?: (page: number) => void
    pageSize?: number
    pageSizeOptions?: number[]
    onPageSizeChange?: (pageSize: number) => void
  }
  emptyMessage?: string
}

// ── Helpers ─────────────────────────────────────────────────────────────

/** Parse a CSS width string (e.g. '14%', '120px', '10rem') into a rough
 * pixel estimate so TanStack's `size` has a sane starting value. Falls back
 * to 150 when the format isn't recognised. */
function widthToSize(w?: string): number | undefined {
  if (!w) return undefined
  const n = parseFloat(w)
  if (!Number.isFinite(n)) return undefined
  if (w.endsWith('%')) return Math.round((n / 100) * 1200) // assume ~1200px viewport
  if (w.endsWith('px')) return Math.round(n)
  return Math.round(n)
}

function alignClassName(align?: 'left' | 'center' | 'right') {
  switch (align) {
    case 'center':
      return 'text-center'
    case 'right':
      return 'text-right'
    default:
      return 'text-left'
  }
}

export type DataTableSelectionKey = string | number

export function dataTableSelectionKey<T>(row: T, index: number): DataTableSelectionKey {
  if (row && typeof row === 'object' && 'id' in row) {
    const id = (row as { id?: unknown }).id
    if (typeof id === 'string' || typeof id === 'number') return id
  }
  return index
}

// ── Component ───────────────────────────────────────────────────────────

export function DataTable<T>({
  columns,
  data,
  loading,
  fetching,
  onRowClick,
  actionMenu,
  selectable,
  pagination,
  emptyMessage,
}: DataTableProps<T>) {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<Set<DataTableSelectionKey>>(new Set())
  const [columnResizeMode] = useState<ColumnResizeMode>('onChange')

  const allSelected =
    data.length > 0 && data.every((row, index) => selected.has(dataTableSelectionKey(row, index)))

  const toggleAll = () => {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(data.map((row, i) => dataTableSelectionKey(row, i))))
  }

  const toggleRow = (key: DataTableSelectionKey) => {
    const next = new Set(selected)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setSelected(next)
  }

  // Map our Column<T>[] → TanStack ColumnDef<T>[]
  const tanstackColumns = useMemo<ColumnDef<T, unknown>[]>(() => {
    const cols: ColumnDef<T, unknown>[] = []

    // Optional checkbox column
    if (selectable) {
      cols.push({
        id: '__select__',
        size: 40,
        minSize: 40,
        maxSize: 40,
        enableResizing: false,
        header: () => (
          <input
            type="checkbox"
            checked={allSelected}
            onChange={toggleAll}
            className="rounded border-border"
          />
        ),
        cell: ({ row }) => {
          const key = dataTableSelectionKey(row.original, row.index)
          return (
            <input
              type="checkbox"
              checked={selected.has(key)}
              onChange={(e) => {
                e.stopPropagation()
                toggleRow(key)
              }}
              onClick={(e) => e.stopPropagation()}
              className="rounded border-border"
            />
          )
        },
      })
    }

    // User-defined columns
    for (const col of columns) {
      const size = widthToSize(col.width)
      cols.push({
        id: col.key,
        header: col.header,
        cell: ({ row }) => col.render(row.original),
        size: size ?? 150,
        minSize: 50,
        enableResizing: true,
        meta: {
          className: col.className,
          headerClassName: col.headerClassName,
          cellClassName: col.cellClassName,
          align: col.align,
          truncate: col.truncate ?? true,
          cssWidth: col.width,
        },
      })
    }

    // Optional action menu column
    if (actionMenu) {
      cols.push({
        id: '__action__',
        size: 60,
        minSize: 60,
        maxSize: 60,
        enableResizing: false,
        header: t('managed.table.actions'),
        meta: { align: 'center', truncate: false },
        cell: ({ row }) => (
          <div onClick={(e) => e.stopPropagation()}>
            <ActionMenu items={actionMenu(row.original)} />
          </div>
        ),
      })
    }

    return cols
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns, selectable, actionMenu, allSelected, selected])

  const table = useReactTable({
    data,
    columns: tanstackColumns,
    columnResizeMode,
    getCoreRowModel: getCoreRowModel(),
    enableColumnResizing: true,
  })

  // ── Loading state ─────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="rounded-lg border border-border">
        <div className="p-8 text-center text-muted-foreground">{t('common.loading')}</div>
      </div>
    )
  }

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div>
      <div
        className={`relative overflow-hidden rounded-lg border border-border transition-opacity ${
          fetching && !loading ? 'opacity-70' : ''
        }`}
      >
        {fetching && !loading && (
          <div className="absolute left-0 right-0 top-0 z-10 h-0.5 overflow-hidden bg-primary/30">
            <div className="h-full w-1/3 animate-[slide_1s_ease-in-out_infinite] bg-primary" />
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full table-fixed">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id} className="border-b border-border bg-muted/30">
                  {headerGroup.headers.map((header) => {
                    const meta = header.column.columnDef.meta as
                      | {
                          className?: string
                          headerClassName?: string
                          align?: 'left' | 'center' | 'right'
                          cssWidth?: string
                        }
                      | undefined
                    const headerAlignClassName = alignClassName(meta?.align)
                    return (
                      <th
                        key={header.id}
                        className={`group/th relative px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-muted-foreground ${headerAlignClassName} ${meta?.className || ''} ${meta?.headerClassName || ''}`}
                        style={{ width: header.getSize() }}
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(header.column.columnDef.header, header.getContext())}
                        {/* Resize handle — wide hit area, visible only on hover/drag */}
                        {header.column.getCanResize() && (
                          <div
                            onMouseDown={header.getResizeHandler()}
                            onTouchStart={header.getResizeHandler()}
                            onDoubleClick={() => header.column.resetSize()}
                            className="absolute -right-px top-0 z-10 flex h-full w-4 cursor-col-resize touch-none select-none items-center justify-center opacity-0 hover:opacity-100 group-hover/th:opacity-100"
                          >
                            <div
                              className={`h-3/5 transition-colors ${
                                header.column.getIsResizing()
                                  ? 'w-0.5 bg-primary'
                                  : 'w-px bg-border hover:w-0.5 hover:bg-primary/60'
                              }`}
                            />
                          </div>
                        )}
                      </th>
                    )
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {data.length === 0 ? (
                <tr>
                  <td
                    colSpan={table.getAllColumns().length}
                    className="px-4 py-8 text-center text-sm text-muted-foreground"
                  >
                    {emptyMessage || t('common.noData')}
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => onRowClick?.(row.original)}
                    className={`border-b border-border transition-colors last:border-b-0 ${
                      onRowClick ? 'cursor-pointer hover:bg-accent/50' : ''
                    }`}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const meta = cell.column.columnDef.meta as
                        | {
                            className?: string
                            cellClassName?: string
                            align?: 'left' | 'center' | 'right'
                            truncate?: boolean
                          }
                        | undefined
                      const cellAlignClassName = alignClassName(meta?.align)
                      const truncateClassName =
                        meta?.truncate === false ? '' : 'overflow-hidden truncate'
                      return (
                        <td
                          key={cell.id}
                          className={`${truncateClassName} px-4 py-3 text-sm ${cellAlignClassName} ${meta?.className || ''} ${meta?.cellClassName || ''}`}
                          style={{ width: cell.column.getSize() }}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      )
                    })}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {pagination && (
        <Pagination
          className="mt-3"
          page={pagination.page || 1}
          totalPages={pagination.totalPages || 0}
          total={0}
          pageSize={pagination.pageSize || 10}
          pageSizeOptions={pagination.pageSizeOptions}
          hasNext={pagination.hasNext}
          hasPrev={pagination.hasPrev}
          isLoading={fetching || loading}
          showTotal={false}
          onPageChange={(page) => {
            if (page === (pagination.page || 1) + 1) pagination.onNext()
            else if (page === (pagination.page || 1) - 1) pagination.onPrev()
            else pagination.onPageChange?.(page)
          }}
          onPageSizeChange={pagination.onPageSizeChange}
        />
      )}
    </div>
  )
}
