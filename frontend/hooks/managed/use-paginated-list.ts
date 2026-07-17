'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { managedGet } from '@/lib/api-client'
import { apiCollectionPath, apiResourceId } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'

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
  scope: ManagedRequestScope,
  cursor?: string,
  limit = 10,
  includeArchived = false,
): Promise<PageResult<T>> {
  const url = apiCollectionPath(path, {
    limit,
    after_id: cursor ? apiResourceId(cursor) : undefined,
    include_archived: includeArchived || undefined,
  })

  const res = await managedGet<
    T[] | { data: T[]; has_more: boolean; first_id?: string; last_id?: string }
  >(url, managedRequestOptions(scope))

  if (Array.isArray(res)) {
    return { data: res, has_more: false }
  }
  const items = res.data
  const firstId = res.first_id
    ? apiResourceId(res.first_id)
    : items.length > 0
      ? apiResourceId(items[0].id || '')
      : undefined
  const lastId = res.last_id
    ? apiResourceId(res.last_id)
    : items.length > 0
      ? apiResourceId(items[items.length - 1].id || '')
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
  const managedScope = useManagedRequestScope()
  const defaultPageSize = pageSizeOptions.includes(limit) ? limit : pageSizeOptions[0]
  const [pageSize, setPageSizeState] = useState(defaultPageSize)
  const effectivePageSize = pageSizeOptions.includes(pageSize) ? pageSize : defaultPageSize
  const listScope = `${queryKey}:${path}:${managedScope.key}:${includeArchived}:${effectivePageSize}`
  const [cursorState, setCursorState] = useState<{
    scope: string
    cursor?: string
    stack: string[]
  }>({
    scope: listScope,
    cursor: undefined,
    stack: [],
  })
  const cursor = cursorState.scope === listScope ? cursorState.cursor : undefined
  const cursorStack = useMemo(
    () => (cursorState.scope === listScope ? cursorState.stack : []),
    [cursorState, listScope],
  )

  const fullKey = [queryKey, managedScope.key, path, cursor, includeArchived, effectivePageSize]
  const queryEnabled = enabled && hasManagedRequestScope(managedScope)

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: fullKey,
    queryFn: () => apiPage<T>(path, managedScope, cursor, effectivePageSize, includeArchived),
    enabled: queryEnabled,
    placeholderData: (previousData, previousQuery) => {
      const previousKey = previousQuery?.queryKey
      if (
        Array.isArray(previousKey) &&
        previousKey[0] === queryKey &&
        previousKey[1] === managedScope.key &&
        previousKey[2] === path &&
        previousKey[4] === includeArchived &&
        previousKey[5] === effectivePageSize
      ) {
        return previousData
      }
      return undefined
    },
    staleTime: 30_000,
  })

  const page: PageResult<T> = data || { data: [], has_more: false }

  // Prefetch next page when current page has more
  useEffect(() => {
    if (page.has_more && page.last_id && queryEnabled) {
      const nextKey = [
        queryKey,
        managedScope.key,
        path,
        page.last_id,
        includeArchived,
        effectivePageSize,
      ]
      queryClient.prefetchQuery({
        queryKey: nextKey,
        queryFn: () =>
          apiPage<T>(path, managedScope, page.last_id, effectivePageSize, includeArchived),
        staleTime: 30_000,
      })
    }
  }, [
    page.has_more,
    page.last_id,
    queryKey,
    managedScope,
    path,
    effectivePageSize,
    includeArchived,
    queryEnabled,
    queryClient,
  ])

  const goNext = useCallback(() => {
    if (page.last_id) {
      setCursorState((state) => {
        const stack = state.scope === listScope ? state.stack : []
        const activeCursor = state.scope === listScope ? state.cursor : undefined
        return {
          scope: listScope,
          cursor: page.last_id,
          stack: [...stack, activeCursor || ''],
        }
      })
    }
  }, [page.last_id, listScope])

  const goPrev = useCallback(() => {
    const prev = cursorStack[cursorStack.length - 1]
    setCursorState((state) => ({
      scope: listScope,
      cursor: prev || undefined,
      stack: state.scope === listScope ? state.stack.slice(0, -1) : [],
    }))
  }, [cursorStack, listScope])

  const goToPage = useCallback(
    (targetPage: number) => {
      const currentPage = cursorStack.length + 1
      if (targetPage === currentPage) return
      if (targetPage < 1) return
      if (targetPage < currentPage) {
        const nextStack = cursorStack.slice(0, targetPage - 1)
        const nextCursor = targetPage === 1 ? undefined : cursorStack[targetPage - 1]
        setCursorState({
          scope: listScope,
          cursor: nextCursor || undefined,
          stack: nextStack,
        })
      }
    },
    [cursorStack, listScope],
  )

  const setPageSize = useCallback((nextPageSize: number) => {
    setPageSizeState(nextPageSize)
  }, [])

  const reset = useCallback(() => {
    setCursorState({ scope: listScope, cursor: undefined, stack: [] })
  }, [listScope])

  return {
    data: page.data,
    isLoading,
    isFetching,
    isError,
    error,
    hasNext: page.has_more,
    hasPrev: cursorStack.length > 0,
    page: cursorStack.length + 1,
    pageSize: effectivePageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
    reset,
  }
}
