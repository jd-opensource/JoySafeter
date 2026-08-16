'use client'

import { Filter, Plus, Search, X } from 'lucide-react'
import type { ReactNode } from 'react'

import { ActionMenu, type MenuItem } from '@/components/managed/shared/action-menu'
import { DataTable, type Column } from '@/components/managed/shared/data-table'
import type { FilterDef } from '@/components/managed/shared/filter-bar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { useTranslation } from '@/lib/i18n'

interface PanelStateCopy {
  title: string
  description: string
}

interface PanelPagination {
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

interface CredentialListPanelProps<T> {
  data: T[]
  columns: Column<T>[]
  loading?: boolean
  fetching?: boolean
  searchPlaceholder: string
  searchValue: string
  onSearchChange: (value: string) => void
  filters?: FilterDef[]
  showArchived?: boolean
  onArchivedChange?: (value: boolean) => void
  createAction?: { label: string; onClick: () => void }
  emptyState: PanelStateCopy
  noResultsState: PanelStateCopy
  onClearFilters: () => void
  onRowClick?: (row: T) => void
  actionMenu?: (row: T) => MenuItem[]
  mobileCard: (row: T) => ReactNode
  mobileCardAriaLabel?: (row: T) => string
  pagination?: PanelPagination
}

function inferredCardLabel<T>(row: T): string | undefined {
  if (!row || typeof row !== 'object' || !('name' in row)) return undefined
  const name = (row as { name?: unknown }).name
  return typeof name === 'string' ? name : undefined
}

export function CredentialListPanel<T>({
  data,
  columns,
  loading = false,
  fetching = false,
  searchPlaceholder,
  searchValue,
  onSearchChange,
  filters = [],
  showArchived = false,
  onArchivedChange,
  createAction,
  emptyState,
  noResultsState,
  onClearFilters,
  onRowClick,
  actionMenu,
  mobileCard,
  mobileCardAriaLabel,
  pagination,
}: CredentialListPanelProps<T>) {
  const { t } = useTranslation()
  const activeFilters = filters.filter((filter) => filter.value !== 'all')
  const activeFilterCount = activeFilters.length + (showArchived ? 1 : 0)
  const hasQuery = searchValue.trim().length > 0
  const hasActiveFilters = hasQuery || activeFilterCount > 0
  const showEmptyState = !loading && data.length === 0
  const showToolbarCreate = !!createAction && !showEmptyState

  const mobilePagination = pagination ? (
    <Pagination
      page={pagination.page ?? 1}
      totalPages={pagination.totalPages ?? 0}
      total={0}
      pageSize={pagination.pageSize ?? 10}
      pageSizeOptions={pagination.pageSizeOptions}
      hasNext={pagination.hasNext}
      hasPrev={pagination.hasPrev}
      isLoading={loading || fetching}
      showTotal={false}
      onPageChange={(nextPage) => {
        const page = pagination.page ?? 1
        if (nextPage === page + 1) pagination.onNext()
        else if (nextPage === page - 1) pagination.onPrev()
        else pagination.onPageChange?.(nextPage)
      }}
      onPageSizeChange={pagination.onPageSizeChange}
    />
  ) : null

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex flex-col gap-3 border-b border-border p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative min-w-0 flex-1 sm:max-w-md">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label={searchPlaceholder}
              placeholder={searchPlaceholder}
              value={searchValue}
              onChange={(event) => onSearchChange(event.currentTarget.value)}
              className="pl-9 pr-9"
            />
            {hasQuery ? (
              <button
                type="button"
                aria-label={t('managed.credentials.filters.clearSearch')}
                className="absolute right-2 top-1/2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                onClick={() => onSearchChange('')}
              >
                <X className="size-4" />
              </button>
            ) : null}
          </div>

          <div className="flex items-center gap-2 sm:ml-auto">
            {(filters.length > 0 || onArchivedChange) && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    aria-label={t('managed.credentials.filters.open')}
                  >
                    <Filter data-icon="inline-start" />
                    {t('managed.credentials.filters.label')}
                    {activeFilterCount > 0 ? (
                      <Badge variant="secondary" className="ml-1 px-1.5 py-0">
                        {activeFilterCount}
                      </Badge>
                    ) : null}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-64">
                  {filters.map((filter, index) => (
                    <div key={filter.key}>
                      {index > 0 ? <DropdownMenuSeparator /> : null}
                      <DropdownMenuLabel>{filter.label}</DropdownMenuLabel>
                      <DropdownMenuRadioGroup value={filter.value} onValueChange={filter.onChange}>
                        {filter.options.map((option) => (
                          <DropdownMenuRadioItem key={option.value} value={option.value}>
                            {option.label}
                          </DropdownMenuRadioItem>
                        ))}
                      </DropdownMenuRadioGroup>
                    </div>
                  ))}
                  {onArchivedChange ? (
                    <>
                      {filters.length > 0 ? <DropdownMenuSeparator /> : null}
                      <DropdownMenuCheckboxItem
                        checked={showArchived}
                        onCheckedChange={(checked) => onArchivedChange(checked === true)}
                      >
                        {t('managed.filters.showArchived')}
                      </DropdownMenuCheckboxItem>
                    </>
                  ) : null}
                  {activeFilterCount > 0 ? (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onSelect={onClearFilters}>
                        {t('managed.credentials.filters.clearAll')}
                      </DropdownMenuItem>
                    </>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>
            )}

            {showToolbarCreate ? (
              <Button type="button" onClick={createAction.onClick} className="ml-auto sm:ml-0">
                <Plus data-icon="inline-start" />
                {createAction.label}
              </Button>
            ) : null}
          </div>
        </div>

        {activeFilterCount > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            {activeFilters.map((filter) => {
              const selected = filter.options.find((option) => option.value === filter.value)
              return (
                <Button
                  key={filter.key}
                  type="button"
                  variant="secondary"
                  size="sm"
                  aria-label={t('managed.credentials.filters.removeCreated')}
                  onClick={() => filter.onChange('all')}
                >
                  {selected?.label ?? filter.value}
                  <X data-icon="inline-end" />
                </Button>
              )
            })}
            {showArchived && onArchivedChange ? (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                aria-label={t('managed.credentials.filters.removeArchived')}
                onClick={() => onArchivedChange(false)}
              >
                {t('managed.filters.showArchived')}
                <X data-icon="inline-end" />
              </Button>
            ) : null}
            {!showEmptyState ? (
              <Button type="button" variant="ghost" size="sm" onClick={onClearFilters}>
                {t('managed.credentials.filters.clearAll')}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      {loading ? (
        <div className="flex flex-col gap-3 p-4">
          {[0, 1, 2].map((item) => (
            <Skeleton key={item} className="h-16 w-full" />
          ))}
        </div>
      ) : showEmptyState ? (
        <div className="flex min-h-64 flex-col items-center justify-center px-6 py-12 text-center">
          <div className="max-w-md">
            <h2 className="text-base font-semibold text-foreground">
              {hasActiveFilters ? noResultsState.title : emptyState.title}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {hasActiveFilters ? noResultsState.description : emptyState.description}
            </p>
          </div>
          <div className="mt-5">
            {hasActiveFilters ? (
              <Button type="button" variant="outline" onClick={onClearFilters}>
                {t('managed.credentials.filters.clearAll')}
              </Button>
            ) : createAction ? (
              <Button type="button" onClick={createAction.onClick}>
                <Plus data-icon="inline-start" />
                {createAction.label}
              </Button>
            ) : null}
          </div>
        </div>
      ) : (
        <>
          <div className="hidden md:block">
            <DataTable
              columns={columns}
              data={data}
              loading={false}
              fetching={fetching}
              onRowClick={onRowClick}
              actionMenu={actionMenu}
              pagination={pagination}
              variant="embedded"
            />
          </div>
          <div className="flex flex-col gap-3 p-4 md:hidden">
            {data.map((row, index) => {
              const items = actionMenu?.(row) ?? []
              const label = mobileCardAriaLabel?.(row) ?? inferredCardLabel(row)
              return (
                <article
                  key={
                    row && typeof row === 'object' && 'id' in row
                      ? String((row as { id: unknown }).id)
                      : index
                  }
                  className="relative flex items-start gap-3 rounded-lg border border-border bg-background p-4 text-left"
                >
                  {onRowClick ? (
                    <button
                      type="button"
                      aria-label={label}
                      onClick={() => onRowClick(row)}
                      className="absolute inset-0 z-0 rounded-lg bg-transparent transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                  ) : null}
                  <div
                    className={`relative z-10 min-w-0 flex-1 ${onRowClick ? 'pointer-events-none' : ''}`}
                  >
                    {mobileCard(row)}
                  </div>
                  {items.length > 0 ? (
                    <div
                      className="relative z-10 shrink-0"
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => event.stopPropagation()}
                    >
                      <ActionMenu items={items} ariaLabel={t('managed.table.actions')} />
                    </div>
                  ) : null}
                </article>
              )
            })}
            {mobilePagination}
          </div>
        </>
      )}
    </section>
  )
}
