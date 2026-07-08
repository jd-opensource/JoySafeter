'use client'

import { useState, useCallback, useEffect } from 'react'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { managedGet } from '@/lib/api-client'
import { stripIdPrefix } from '@/lib/managed/id'

interface PageResult<T> {
  data: T[]
  has_more: boolean
  first_id?: string
  last_id?: string
}

interface UsePaginatedListOptions {
  queryKey: string
  path: string
  limit?: number
  pageSizeOptions?: number[]
  enabled?: boolean
  includeArchived?: boolean
}

interface UsePaginatedListResult<T> {
  data: T[]
  isLoading: boolean
  isFetching: boolean
  isError: boolean
  error: unknown
  hasNext: boolean
  hasPrev: boolean
  page: number
  pageSize: number
  pageSizeOptions: number[]
  goNext: () => void
  goPrev: () => void
  goToPage: (page: number) => void
  setPageSize: (pageSize: number) => void
  reset: () => void
}

async function apiPage<T extends { id?: string }>(
  path: string,
  cursor?: string,
  limit = 10,
  includeArchived = false,
): Promise<PageResult<T>> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (cursor) params.set('after_id', cursor)
  if (includeArchived) params.set('include_archived', 'true')
  const sep = path.includes('?') ? '&' : '?'
  const url = `${path}${sep}${params.toString()}`

  const res = await managedGet<
    T[] | { data: T[]; has_more: boolean; first_id?: string; last_id?: string }
  >(url)

  if (Array.isArray(res)) {
    return { data: res, has_more: false }
  }
  const items = res.data
  const firstId = res.first_id
    ? stripIdPrefix(res.first_id)
    : items.length > 0
      ? stripIdPrefix(items[0].id || '')
      : undefined
  const lastId =
    res.last_id
      ? stripIdPrefix(res.last_id)
      : items.length > 0
        ? stripIdPrefix(items[items.length - 1].id || '')
        : undefined
  return { data: items, has_more: res.has_more, first_id: firstId, last_id: lastId }
}

export function usePaginatedList<T extends { id?: string }>({
  queryKey,
  path,
  limit = 10,
  pageSizeOptions = [10, 25, 50],
  enabled = true,
  includeArchived = false,
}: UsePaginatedListOptions): UsePaginatedListResult<T> {
  const queryClient = useQueryClient()
  const defaultPageSize = pageSizeOptions.includes(limit) ? limit : pageSizeOptions[0]
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [cursorStack, setCursorStack] = useState<string[]>([])
  const [pageSize, setPageSizeState] = useState(defaultPageSize)

  const fullKey = [queryKey, cursor, includeArchived, pageSize]

  // Reset to first page when filters change
  useEffect(() => {
    setCursor(undefined)
    setCursorStack([])
  }, [includeArchived, pageSize])

  useEffect(() => {
    if (!pageSizeOptions.includes(pageSize)) {
      setPageSizeState(defaultPageSize)
      setCursor(undefined)
      setCursorStack([])
    }
  }, [defaultPageSize, pageSize, pageSizeOptions])

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: fullKey,
    queryFn: () => apiPage<T>(path, cursor, pageSize, includeArchived),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })

  const page: PageResult<T> = data || { data: [], has_more: false }

  // Prefetch next page when current page has more
  useEffect(() => {
    if (page.has_more && page.last_id && enabled) {
      const nextKey = [queryKey, page.last_id, includeArchived, pageSize]
      queryClient.prefetchQuery({
        queryKey: nextKey,
        queryFn: () => apiPage<T>(path, page.last_id, pageSize, includeArchived),
        staleTime: 30_000,
      })
    }
  }, [page.has_more, page.last_id, queryKey, path, pageSize, includeArchived, enabled, queryClient])

  const goNext = useCallback(() => {
    if (page.last_id) {
      setCursorStack((s) => [...s, cursor || ''])
      setCursor(page.last_id)
    }
  }, [page.last_id, cursor])

  const goPrev = useCallback(() => {
    const prev = cursorStack[cursorStack.length - 1]
    setCursorStack((s) => s.slice(0, -1))
    setCursor(prev || undefined)
  }, [cursorStack])

  const goToPage = useCallback(
    (targetPage: number) => {
      const currentPage = cursorStack.length + 1
      if (targetPage === currentPage) return
      if (targetPage < 1) return
      if (targetPage < currentPage) {
        const nextStack = cursorStack.slice(0, targetPage - 1)
        const nextCursor = nextStack[nextStack.length - 1]
        setCursorStack(nextStack)
        setCursor(nextCursor || undefined)
      }
    },
    [cursorStack],
  )

  const setPageSize = useCallback((nextPageSize: number) => {
    setPageSizeState(nextPageSize)
    setCursor(undefined)
    setCursorStack([])
  }, [])

  const reset = useCallback(() => {
    setCursor(undefined)
    setCursorStack([])
  }, [])

  return {
    data: page.data,
    isLoading,
    isFetching,
    isError,
    error,
    hasNext: page.has_more,
    hasPrev: cursorStack.length > 0,
    page: cursorStack.length + 1,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
    reset,
  }
}
