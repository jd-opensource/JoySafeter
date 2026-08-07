import { stripIdPrefix } from '@/lib/managed/id'
import { isEntityId } from '@/types/entity-id'

type QueryValue = string | number | boolean | null | undefined

function appendQuery(path: string, query?: Record<string, QueryValue>): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined) continue
    params.set(key, String(value))
  }
  const suffix = params.toString()
  const separator = path.includes('?') ? '&' : '?'
  return suffix ? `${path}${separator}${suffix}` : path
}

function cleanSegment(segment: string | number): string {
  return encodeURIComponent(String(segment).replace(/^\/+|\/+$/g, ''))
}

export function apiResourceId(id: string | null | undefined): string {
  const value = id ?? ''
  if (
    isEntityId(value, 'agent') ||
    isEntityId(value, 'session') ||
    isEntityId(value, 'task') ||
    isEntityId(value, 'trigger') ||
    isEntityId(value, 'environment') ||
    isEntityId(value, 'secret') ||
    isEntityId(value, 'vault') ||
    isEntityId(value, 'credential') ||
    isEntityId(value, 'memoryStore') ||
    isEntityId(value, 'memory') ||
    isEntityId(value, 'memoryVersion') ||
    isEntityId(value, 'skill') ||
    isEntityId(value, 'skillFile') ||
    isEntityId(value, 'skillSecurityScan') ||
    isEntityId(value, 'skillVersion') ||
    isEntityId(value, 'skillVersionFile') ||
    isEntityId(value, 'skillUsage') ||
    isEntityId(value, 'file') ||
    isEntityId(value, 'sessionResource')
  ) {
    return value
  }
  return stripIdPrefix(value)
}

export function apiCollectionPath(resource: string, query?: Record<string, QueryValue>): string {
  return appendQuery(`/${resource.replace(/^\/+|\/+$/g, '')}`, query)
}

export function apiResourcePath(
  resource: string,
  id: string | null | undefined,
  ...segments: Array<string | number>
): string {
  const pathSegments = [
    resource.replace(/^\/+|\/+$/g, ''),
    apiResourceId(id),
    ...segments.map(cleanSegment),
  ].filter(Boolean)
  return `/${pathSegments.join('/')}`
}

export function apiResourceSubpath(
  resource: string,
  id: string | null | undefined,
  segments: Array<string | number>,
  query?: Record<string, QueryValue>,
): string {
  return appendQuery(apiResourcePath(resource, id, ...segments), query)
}
