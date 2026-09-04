'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { managedGet } from '@/lib/api-client'
import { apiCollectionPath } from '@/lib/managed/api-paths'
import { parseManagedCursorPage, type ManagedCursorPage } from '@/lib/managed/cursor-page'
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

export interface ManagedPaginatedListPageRequest<CursorId extends string> {
  limit: number
  afterId?: CursorId
  includeArchived?: boolean
}

export type ManagedPaginatedListFetcher<T, CursorId extends string> = (
  request: ManagedPaginatedListPageRequest<CursorId>,
  scope: ManagedRequestScope,
) => Promise<ManagedCursorPage<T, CursorId>>

interface UsePaginatedListBaseOptions<
  T extends { id?: CursorId },
  CursorId extends string = Extract<T['id'], string>,
> {
  queryKey: string
  cacheVersion?: string
  paginationScopeKey?: string
  requiresManagedScope?: boolean
  limit?: number
  pageSize?: number
  onPageSizeChange?: (pageSize: number) => void
  pageSizeOptions?: number[]
  enabled?: boolean
  includeArchived?: boolean
  parseCursor: (cursor: string) => CursorId
  refetchInterval?: (page: PageResult<T, CursorId> | undefined) => number | false
}

type UsePaginatedListOptions<
  T extends { id?: CursorId },
  CursorId extends string = Extract<T['id'], string>,
> = UsePaginatedListBaseOptions<T, CursorId> &
  (
    | {
        path: string
        query?: Record<string, string | number | boolean | null | undefined>
        parseItem?: (item: unknown) => T
        sourceKey?: never
        fetchPage?: never
      }
    | {
        sourceKey: string
        fetchPage: ManagedPaginatedListFetcher<T, CursorId>
        path?: never
        query?: never
        parseItem?: never
      }
  )

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

  const response = await managedGet<unknown>(url, managedRequestOptions(scope))
  const page = parseManagedCursorPage(response, {
    parseItem: parseItem ?? ((item) => item as T),
    parseCursor,
  })
  return {
    data: page.items,
    has_more: page.hasMore,
    first_id: page.firstId,
    last_id: page.lastId,
  }
}

export function usePaginatedList<
  T extends { id?: CursorId },
  CursorId extends string = Extract<T['id'], string>,
>({
  queryKey,
  path,
  query,
  sourceKey,
  cacheVersion,
  paginationScopeKey,
  requiresManagedScope = true,
  limit = 10,
  pageSize: controlledPageSize,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50],
  enabled = true,
  includeArchived,
  parseItem,
  parseCursor,
  fetchPage,
  refetchInterval,
}: UsePaginatedListOptions<T, CursorId>): UsePaginatedListResult<T> {
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const queryScope = query ? JSON.stringify(query) : ''
  const sourceIdentity = useMemo(
    () => {
      if (fetchPage) {
        if (!sourceKey) throw new TypeError('sourceKey is required with fetchPage')
        return sourceKey
      }
      if (!path) throw new TypeError('path is required without fetchPage')
      return query ? apiCollectionPath(path, query) : path
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fetchPage, path, queryScope, sourceKey],
  )
  const defaultPageSize = pageSizeOptions.includes(limit) ? limit : pageSizeOptions[0]
  const [internalPageSize, setInternalPageSize] = useState(defaultPageSize)
  const requestedPageSize = controlledPageSize ?? internalPageSize
  const effectivePageSize = pageSizeOptions.includes(requestedPageSize)
    ? requestedPageSize
    : defaultPageSize
  const effectiveScopeKey = paginationScopeKey ?? managedScope.key
  const listScope = `${queryKey}:${sourceIdentity}:${effectiveScopeKey}:${includeArchived}:${effectivePageSize}:${cacheVersion ?? ''}`
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
    effectiveScopeKey,
    sourceIdentity,
    cursor,
    includeArchived,
    effectivePageSize,
    ...(cacheVersion ? [cacheVersion] : []),
  ]
  const queryEnabled = enabled && (!requiresManagedScope || hasManagedRequestScope(managedScope))

  useEffect(() => {
    setCursorState((state) =>
      state.scope === listScope ? state : loadCursorState(listScope, parseCursor),
    )
  }, [listScope, parseCursor])

  useEffect(() => {
    if (cursorState.scope === listScope) saveCursorState(cursorState)
  }, [cursorState, listScope])

  const loadPage = useCallback(
    async (pageCursor: CursorId | undefined): Promise<PageResult<T, CursorId>> => {
      if (!fetchPage) {
        return apiPage<T, CursorId>(
          sourceIdentity,
          managedScope,
          pageCursor,
          effectivePageSize,
          includeArchived,
          parseItem,
          parseCursor,
        )
      }
      const page = await fetchPage(
        {
          limit: effectivePageSize,
          afterId: pageCursor,
          includeArchived,
        },
        managedScope,
      )
      return {
        data: page.items,
        has_more: page.hasMore,
        first_id: page.firstId,
        last_id: page.lastId,
      }
    },
    [
      effectivePageSize,
      fetchPage,
      includeArchived,
      managedScope,
      parseCursor,
      parseItem,
      sourceIdentity,
    ],
  )

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: fullKey,
    queryFn: () => loadPage(cursor),
    enabled: queryEnabled,
    placeholderData: (previousData, previousQuery) => {
      const previousKey = previousQuery?.queryKey
      if (
        Array.isArray(previousKey) &&
        previousKey[0] === queryKey &&
        previousKey[1] === effectiveScopeKey &&
        previousKey[2] === sourceIdentity &&
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
        effectiveScopeKey,
        sourceIdentity,
        page.last_id,
        includeArchived,
        effectivePageSize,
        ...(cacheVersion ? [cacheVersion] : []),
      ]
      queryClient.prefetchQuery({
        queryKey: nextKey,
        queryFn: () => loadPage(page.last_id),
        staleTime: 30_000,
      })
    }
  }, [
    page.has_more,
    page.last_id,
    queryKey,
    effectiveScopeKey,
    sourceIdentity,
    effectivePageSize,
    cacheVersion,
    includeArchived,
    queryEnabled,
    queryClient,
    loadPage,
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
