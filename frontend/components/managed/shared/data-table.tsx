'use client'

import { useState, type ReactNode } from 'react'
import { useTranslation } from '@/lib/i18n'
import { Pagination } from '@/components/ui/pagination'
import { ActionMenu, type MenuItem } from './action-menu'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  className?: string
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
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const allSelected = data.length > 0 && selected.size === data.length

  const toggleAll = () => {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(data.map((_, i) => i)))
    }
  }

  const toggleRow = (i: number) => {
    const next = new Set(selected)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    setSelected(next)
  }

  if (loading) {
    return (
      <div className="border border-border rounded-lg">
        <div className="p-8 text-center text-muted-foreground">
          {t('common.loading')}
        </div>
      </div>
    )
  }

  return (
    <div>
      <div
        className={`border border-border rounded-lg overflow-hidden relative transition-opacity ${fetching && !loading ? 'opacity-70' : ''}`}
      >
        {fetching && !loading && (
          <div className="absolute top-0 left-0 right-0 h-0.5 bg-primary/30 overflow-hidden z-10">
            <div className="h-full w-1/3 bg-primary animate-[slide_1s_ease-in-out_infinite]" />
          </div>
        )}
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              {selectable && (
                <th className="w-10 px-3 py-2.5">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    className="rounded border-border"
                  />
                </th>
              )}
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`px-4 py-2.5 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider ${col.className || ''}`}
                >
                  {col.header}
                </th>
              ))}
              {actionMenu && <th className="w-10" />}
            </tr>
          </thead>
          <tbody>
            {data.length === 0 ? (
              <tr>
                <td
                  colSpan={
                    columns.length +
                    (actionMenu ? 1 : 0) +
                    (selectable ? 1 : 0)
                  }
                  className="px-4 py-8 text-center text-muted-foreground text-sm"
                >
                  {emptyMessage || t('common.noData')}
                </td>
              </tr>
            ) : (
              data.map((row, i) => (
                <tr
                  key={i}
                  onClick={() => onRowClick?.(row)}
                  className={`border-b border-border last:border-b-0 transition-colors ${
                    onRowClick ? 'cursor-pointer hover:bg-accent/50' : ''
                  }`}
                >
                  {selectable && (
                    <td className="w-10 px-3 py-3">
                      <input
                        type="checkbox"
                        checked={selected.has(i)}
                        onChange={(e) => {
                          e.stopPropagation()
                          toggleRow(i)
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="rounded border-border"
                      />
                    </td>
                  )}
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-3 text-sm ${col.className || ''}`}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                  {actionMenu && (
                    <td
                      className="px-2 py-3"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <ActionMenu items={actionMenu(row)} />
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
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
