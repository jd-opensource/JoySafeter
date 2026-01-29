'use client'

import { ChevronLeft, ChevronRight } from 'lucide-react'
import * as React from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

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
  className,
  showTotal = true,
}: PaginationProps) {
  const { t } = useTranslation()

  // If no data, don't show pagination
  if (total === 0) {
    return null
  }

  const handlePrevious = () => {
    if (page > 1 && !isLoading) {
      onPageChange(page - 1)
    }
  }

  const handleNext = () => {
    if (page < totalPages && !isLoading) {
      onPageChange(page + 1)
    }
  }

  return (
    <div className={cn('flex items-center justify-between', className)}>
      {showTotal && (
        <div className="text-xs text-gray-500">
          {total} {t('common.items')}, {t('common.page')} {page} / {totalPages}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={handlePrevious}
          disabled={page === 1 || isLoading}
          className="text-xs"
        >
          <ChevronLeft className="h-4 w-4" />
          {t('common.previous')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleNext}
          disabled={page === totalPages || isLoading}
          className="text-xs"
        >
          {t('common.next')}
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

