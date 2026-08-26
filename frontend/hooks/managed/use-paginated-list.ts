'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { managedGet } from '@/lib/api-client'
import { apiCollectionPath } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'

interface PageResult<T, CursorId extends string> {
  data: T[]
  has_more: boolean
  first_id?: CursorId
  last_id?: CursorId
}

interface UsePaginatedListOptions<
  T extends { id?: CursorId },
  CursorId extends string = Extract<T['id'], string>,
> {
  queryKey: string
  path: string
  query?: Record<string, string | number | boolean | null | undefined>
  cacheVersion?: string
  limit?: number
  pageSize?: number
  onPageSizeChange?: (pageSize: number) => void
  pageSizeOptions?: number[]
  enabled?: boolean
  includeArchived?: boolean
  parseItem?: (item: unknown) => T
  parseCursor: (cursor: string) => CursorId
  refetchInterval?: (page: PageResult<T, CursorId> | undefined) => number | false
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

interface CursorState<CursorId extends string> {
  scope: string
  cursor?: CursorId
  stack: Array<CursorId | ''>
}

const STORAGE_PREFIX = 'joysafeter:managed:list-pagination:'

function storageKey(scope: string) {
  return `${STORAGE_PREFIX}${scope}`
}

function normalizeStoredCursor<CursorId extends string>(
  value: unknown,
  parseCursor: (cursor: string) => CursorId,
): CursorId | undefined {
  if (typeof value !== 'string' || !value) return undefined
  try {
    return parseCursor(value)
  } catch {
    return undefined
  }
}

function normalizeCursorState<CursorId extends string>(
  scope: string,
  value: unknown,
  parseCursor: (cursor: string) => CursorId,
): CursorState<CursorId> {
  if (!value || typeof value !== 'object') return { scope, cursor: undefined, stack: [] }
  const maybeState = value as { scope?: unknown; cursor?: unknown; stack?: unknown }
  if (maybeState.scope !== scope) return { scope, cursor: undefined, stack: [] }
  const stack: Array<CursorId | ''> = []
  if (Array.isArray(maybeState.stack)) {
    for (const item of maybeState.stack) {
      if (item === '') {
        stack.push('')
        continue
      }
      const cursor = normalizeStoredCursor(item, parseCursor)
      if (cursor) stack.push(cursor)
    }
  }
  return {
    scope,
    cursor: normalizeStoredCursor(maybeState.cursor, parseCursor),
    stack,
  }
}

function loadCursorState<CursorId extends string>(
  scope: string,
  parseCursor: (cursor: string) => CursorId,
): CursorState<CursorId> {
  if (typeof window === 'undefined') return { scope, cursor: undefined, stack: [] }
  try {
    const raw = window.sessionStorage.getItem(storageKey(scope))
    return normalizeCursorState(scope, raw ? JSON.parse(raw) : null, parseCursor)
  } catch {
    return { scope, cursor: undefined, stack: [] }
  }
}

function saveCursorState<CursorId extends string>(state: CursorState<CursorId>) {
  if (typeof window === 'undefined') return
  try {
    if (!state.cursor && state.stack.length === 0) {
      window.sessionStorage.removeItem(storageKey(state.scope))
      return
    }
    window.sessionStorage.setItem(storageKey(state.scope), JSON.stringify(state))
  } catch {
    return
  }
}

async function apiPage<T extends { id?: CursorId }, CursorId extends string>(
  path: string,
  scope: ManagedRequestScope,
  cursor: CursorId | undefined,
  limit = 10,
  includeArchived?: boolean,
  parseItem?: (item: unknown) => T,
  parseCursor?: (cursor: string) => CursorId,
): Promise<PageResult<T, CursorId>> {
  if (!parseCursor) throw new TypeError('parseCursor is required')
  const url = apiCollectionPath(path, {
    limit,
    after_id: cursor,
    include_archived: includeArchived,
  })

  const res = await managedGet<
    unknown[] | { data: unknown[]; has_more: boolean; first_id?: string; last_id?: string }
  >(url, managedRequestOptions(scope))

  if (Array.isArray(res)) {
    return { data: parseItem ? res.map(parseItem) : (res as T[]), has_more: false }
  }
  const items = parseItem ? res.data.map(parseItem) : (res.data as T[])
  const firstCursor = res.first_id ?? items[0]?.id
  const lastCursor = res.last_id ?? items[items.length - 1]?.id
  const firstId = firstCursor ? parseCursor(firstCursor) : undefined
  const lastId = lastCursor ? parseCursor(lastCursor) : undefined
  return { data: items, has_more: res.has_more, first_id: firstId, last_id: lastId }
}

export function usePaginatedList<
  T extends { id?: CursorId },
  CursorId extends string = Extract<T['id'], string>,
>({
  queryKey,
  path,
  query,
  cacheVersion,
  limit = 10,
  pageSize: controlledPageSize,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50],
  enabled = true,
  includeArchived,
  parseItem,
  parseCursor,
  refetchInterval,
}: UsePaginatedListOptions<T, CursorId>): UsePaginatedListResult<T> {
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const queryScope = query ? JSON.stringify(query) : ''
  const scopedPath = useMemo(
    () => (query ? apiCollectionPath(path, query) : path),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [path, queryScope],
  )
  const defaultPageSize = pageSizeOptions.includes(limit) ? limit : pageSizeOptions[0]
  const [internalPageSize, setInternalPageSize] = useState(defaultPageSize)
  const requestedPageSize = controlledPageSize ?? internalPageSize
  const effectivePageSize = pageSizeOptions.includes(requestedPageSize)
    ? requestedPageSize
    : defaultPageSize
  const listScope = `${queryKey}:${scopedPath}:${managedScope.key}:${includeArchived}:${effectivePageSize}:${cacheVersion ?? ''}`
  const [cursorState, setCursorState] = useState<CursorState<CursorId>>(() =>
    loadCursorState(listScope, parseCursor),
  )
  const cursor = cursorState.scope === listScope ? cursorState.cursor : undefined
  const cursorStack = useMemo(
    () => (cursorState.scope === listScope ? cursorState.stack : []),
    [cursorState, listScope],
  )

  const fullKey = [
    queryKey,
    managedScope.key,
    scopedPath,
    cursor,
    includeArchived,
    effectivePageSize,
    ...(cacheVersion ? [cacheVersion] : []),
  ]
  const queryEnabled = enabled && hasManagedRequestScope(managedScope)

  useEffect(() => {
    setCursorState((state) =>
      state.scope === listScope ? state : loadCursorState(listScope, parseCursor),
    )
  }, [listScope, parseCursor])

  useEffect(() => {
    if (cursorState.scope === listScope) saveCursorState(cursorState)
  }, [cursorState, listScope])

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: fullKey,
    queryFn: () =>
      apiPage<T, CursorId>(
        scopedPath,
        managedScope,
        cursor,
        effectivePageSize,
        includeArchived,
        parseItem,
        parseCursor,
      ),
    enabled: queryEnabled,
    placeholderData: (previousData, previousQuery) => {
      const previousKey = previousQuery?.queryKey
      if (
        Array.isArray(previousKey) &&
        previousKey[0] === queryKey &&
        previousKey[1] === managedScope.key &&
        previousKey[2] === scopedPath &&
        previousKey[4] === includeArchived &&
        previousKey[5] === effectivePageSize &&
        previousKey[6] === cacheVersion
      ) {
        return previousData
      }
      return undefined
    },
    refetchInterval: refetchInterval
      ? (query) => refetchInterval(query.state.data as PageResult<T, CursorId> | undefined)
      : undefined,
    staleTime: 30_000,
  })

  const page: PageResult<T, CursorId> = data || { data: [], has_more: false }

  // Prefetch next page when current page has more
  useEffect(() => {
    if (page.has_more && page.last_id && queryEnabled) {
      const nextKey = [
        queryKey,
        managedScope.key,
        scopedPath,
        page.last_id,
        includeArchived,
        effectivePageSize,
        ...(cacheVersion ? [cacheVersion] : []),
      ]
      queryClient.prefetchQuery({
        queryKey: nextKey,
        queryFn: () =>
          apiPage<T, CursorId>(
            scopedPath,
            managedScope,
            page.last_id,
            effectivePageSize,
            includeArchived,
            parseItem,
            parseCursor,
          ),
        staleTime: 30_000,
      })
    }
  }, [
    page.has_more,
    page.last_id,
    queryKey,
    managedScope,
    scopedPath,
    effectivePageSize,
    cacheVersion,
    includeArchived,
    parseItem,
    parseCursor,
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

  const setPageSize = useCallback(
    (nextPageSize: number) => {
      if (controlledPageSize === undefined) setInternalPageSize(nextPageSize)
      onPageSizeChange?.(nextPageSize)
    },
    [controlledPageSize, onPageSizeChange],
  )

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
