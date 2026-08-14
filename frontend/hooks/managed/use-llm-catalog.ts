'use client'

import { useQuery } from '@tanstack/react-query'

import { managedGet } from '@/lib/api-client'
import { parseLlmCatalogResponse } from '@/lib/managed/llm-catalog'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'

export const LLM_CATALOG_QUERY_KEY = ['llm-catalog'] as const

export function useLlmCatalog() {
  const managedScope = useManagedRequestScope()
  return useQuery({
    queryKey: LLM_CATALOG_QUERY_KEY,
    queryFn: async () =>
      parseLlmCatalogResponse(
        await managedGet<unknown>('/llm/catalog', managedRequestOptions(managedScope)),
      ),
    enabled: hasManagedRequestScope(managedScope),
    placeholderData: (previousData) => previousData,
    staleTime: 5 * 60_000,
  })
}
