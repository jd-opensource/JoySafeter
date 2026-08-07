import { parseAnyEntityId, type AnyEntityId } from '@/types/entity-id'

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

export function apiResourceId(id: AnyEntityId): AnyEntityId {
  return parseAnyEntityId(id)
}

export function apiCollectionPath(resource: string, query?: Record<string, QueryValue>): string {
  return appendQuery(`/${resource.replace(/^\/+|\/+$/g, '')}`, query)
}

export function apiResourcePath(
  resource: string,
  id: AnyEntityId,
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
  id: AnyEntityId,
  segments: Array<string | number>,
  query?: Record<string, QueryValue>,
): string {
  return appendQuery(apiResourcePath(resource, id, ...segments), query)
}
