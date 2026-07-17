'use client'

import { useMemo } from 'react'

import { useProjectStore } from '@/stores/managed/project-store'

export interface ManagedRequestScope {
  orgId: string | null
  projectId: string | null
  key: string
}

export function managedScopeKey(orgId: string | null, projectId: string | null): string {
  return `${orgId ?? ''}:${projectId ?? ''}`
}

export function hasManagedRequestScope(scope: ManagedRequestScope): boolean {
  return Boolean(scope.orgId && scope.projectId)
}

export function managedRequestOptions(scope: ManagedRequestScope) {
  const headers: Record<string, string> = {}
  if (scope.orgId) headers['X-Org-Id'] = scope.orgId
  if (scope.projectId) headers['X-Project-Id'] = scope.projectId
  return { headers, skipManagedContext: true }
}

export function useManagedRequestScope(): ManagedRequestScope {
  const orgId = useProjectStore((state) => state.currentOrgId)
  const projectId = useProjectStore((state) => state.currentProjectId)
  return useMemo(
    () => ({ orgId, projectId, key: managedScopeKey(orgId, projectId) }),
    [orgId, projectId],
  )
}
