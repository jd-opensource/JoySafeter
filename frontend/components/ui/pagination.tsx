'use client'

import { ChevronLeft, ChevronRight } from 'lucide-react'
import * as React from 'react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

export interface PaginationProps {
  /** Current page number */
  page: number
  /** Total pages */
  totalPages: number
  /** Total records */
  total: number
  /** Records per page */
  pageSize: number
  /** Whether loading */
  isLoading?: boolean
  /** Page change callback */
  onPageChange: (page: number) => void
  /** Page size options */
  pageSizeOptions?: number[]
  /** Page size change callback */
  onPageSizeChange?: (pageSize: number) => void
  /** Whether next page is available when totalPages is unknown */
  hasNext?: boolean
  /** Whether previous page is available when totalPages is unknown */
  hasPrev?: boolean
  /** Custom class name */
  className?: string
  /** Whether to show total records */
  showTotal?: boolean
}

export function Pagination({
  page,
  totalPages,
  total,
  pageSize,
  isLoading = false,
  onPageChange,
  pageSizeOptions = [10, 25, 50],
  onPageSizeChange,
  hasNext,
  hasPrev,
  className,
  showTotal = true,
}: PaginationProps) {
  const { t } = useTranslation()
  const normalizedPageSize = Number(pageSize)
  const activePageSize = pageSizeOptions.includes(normalizedPageSize)
    ? normalizedPageSize
    : pageSizeOptions[0]

  // If no data and no cursor navigation/page-size controls, don't show pagination.
  // Cursor-paginated managed tables do not know total, but still need page-size controls.
  if (total === 0 && totalPages === 0 && !hasNext && !hasPrev && !onPageSizeChange) {
    return null
  }

  const effectiveTotalPages = Math.max(totalPages, page)
  const canGoPrev = hasPrev ?? page > 1
  const canGoNext = hasNext ?? page < effectiveTotalPages

  const handlePrevious = () => {
    if (canGoPrev && !isLoading) {
      onPageChange(page - 1)
    }
  }

  const handleNext = () => {
    if (canGoNext && !isLoading) {
      onPageChange(page + 1)
    }
  }

  const getPageItems = () => {
    if (totalPages > 0) {
      const pages = new Set<number>([1, page, totalPages])
      for (let item = page - 1; item <= page + 1; item += 1) {
        if (item >= 1 && item <= totalPages) pages.add(item)
      }
      return Array.from(pages)
        .sort((a, b) => a - b)
        .reduce<Array<number | 'ellipsis'>>((items, item) => {
          const prev = items[items.length - 1]
          if (typeof prev === 'number' && item - prev > 1) items.push('ellipsis')
          items.push(item)
          return items
        }, [])
    }

    const pages: Array<number | 'ellipsis'> = []
    for (let item = 1; item <= page; item += 1) pages.push(item)
    if (canGoNext) pages.push(page + 1)
    return pages
  }

  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-3', className)}>
      {showTotal && (
        <div className="text-xs text-[var(--text-tertiary)]">
          {totalPages > 0
            ? `${total} ${t('common.items')}, ${t('common.page')} ${page} / ${totalPages}`
            : `${t('common.page')} ${page}`}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="icon"
          onClick={handlePrevious}
          disabled={!canGoPrev || isLoading}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
          {getPageItems().map((item, index) =>
            item === 'ellipsis' ? (
              <span key={`ellipsis-${index}`} className="px-2 text-sm text-muted-foreground">
                …
              </span>
            ) : (
              <Button
                key={item}
                variant={item === page ? 'secondary' : 'ghost'}
                size="sm"
                className="h-7 min-w-7 px-2"
                onClick={() => onPageChange(item)}
                disabled={item === page || isLoading || (totalPages === 0 && item > page && !canGoNext)}
              >
                {item}
              </Button>
            ),
          )}
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={handleNext}
          disabled={!canGoNext || isLoading}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      {onPageSizeChange && (
        <div className="flex items-center gap-1 rounded-lg bg-muted p-1">
          {pageSizeOptions.map((size) => {
            const isActive = Number(size) === activePageSize
            return (
              <Button
                key={size}
                type="button"
                variant={isActive ? 'default' : 'ghost'}
                size="sm"
                className="h-8 px-3"
                onClick={() => onPageSizeChange(size)}
                aria-current={isActive ? 'page' : undefined}
              >
                {size}
              </Button>
            )
          })}
        </div>
      )}
    </div>
  )
}
