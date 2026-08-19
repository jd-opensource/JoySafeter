'use client'

import { useQuery } from '@tanstack/react-query'

import { managedGet } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'

export type CredentialReferenceResourceType = 'agent' | 'trigger' | 'environment' | 'session'

export interface CredentialReferenceItem {
  surface: string
  resourceType: CredentialReferenceResourceType
  id: string
  name: string | null
}

export interface CredentialReferences {
  references: CredentialReferenceItem[]
  otherCount: number
  canArchive: boolean
  canDelete: boolean
}

export function parseReferencesResponse(raw: unknown): CredentialReferences {
  const obj = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const rawItems = Array.isArray(obj.references) ? obj.references : []
  const references: CredentialReferenceItem[] = rawItems.map((entry) => {
    const item = (entry && typeof entry === 'object' ? entry : {}) as Record<string, unknown>
    return {
      surface: typeof item.surface === 'string' ? item.surface : '',
      resourceType: item.resource_type as CredentialReferenceResourceType,
      id: typeof item.id === 'string' ? item.id : '',
      name: typeof item.name === 'string' ? item.name : null,
    }
  })
  return {
    references,
    otherCount: typeof obj.other_count === 'number' ? obj.other_count : 0,
    canArchive: obj.can_archive === undefined ? true : obj.can_archive === true,
    canDelete: obj.can_delete === undefined ? true : obj.can_delete === true,
  }
}

function useReferences(
  collection: 'credentials' | 'credential-groups',
  id: string,
  enabled: boolean,
) {
  const scope = useManagedRequestScope()
  return useQuery({
    queryKey: ['credential-references', collection, scope.key, id],
    queryFn: async () => {
      const raw = await managedGet<unknown>(
        apiResourcePath(collection, id, 'references'),
        managedRequestOptions(scope),
      )
      return parseReferencesResponse(raw)
    },
    enabled: enabled && !!id && hasManagedRequestScope(scope),
    staleTime: 15_000,
  })
}

export function useCredentialReferences(id: string, opts: { enabled?: boolean } = {}) {
  return useReferences('credentials', id, opts.enabled ?? true)
}

export function useCredentialGroupReferences(id: string, opts: { enabled?: boolean } = {}) {
  return useReferences('credential-groups', id, opts.enabled ?? true)
}
