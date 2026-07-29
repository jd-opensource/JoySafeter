'use client'

const URL_KEY_SUFFIXES = ['URL', 'URI', 'ENDPOINT']
const CONFIG_KEY_SUFFIXES = [
  ...URL_KEY_SUFFIXES,
  'API_KEY',
  'AUTH_TOKEN',
  'TOKEN',
  'SECRET',
  'MODEL',
  'MODEL_NAME',
  'NAME',
  'TITLE',
  'DESCRIPTION',
]
const CONFIG_KEY_EXACT = new Set([
  'MODEL',
  'NAME',
  'TITLE',
  'DESCRIPTION',
  'TOKEN_VALUE',
  'CLIENT_SECRET',
  'REFRESH_TOKEN',
])

function normalizeKey(key: string): string {
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^a-zA-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase()
}

export function isUrlLikeKey(key: string | undefined): boolean {
  if (!key) return false
  const normalized = normalizeKey(key)
  if (!normalized) return false
  return URL_KEY_SUFFIXES.some(
    (suffix) => normalized === suffix || normalized.endsWith(`_${suffix}`),
  )
}

export function isConfigStringKey(key: string | undefined): boolean {
  if (!key) return false
  const normalized = normalizeKey(key)
  if (!normalized) return false
  return (
    CONFIG_KEY_EXACT.has(normalized) ||
    CONFIG_KEY_SUFFIXES.some((suffix) => normalized === suffix || normalized.endsWith(`_${suffix}`))
  )
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Object.prototype.toString.call(value) === '[object Object]'
}

export function trimConfigStringFields<T>(value: T, key?: string): T {
  if (typeof value === 'string') {
    return (isConfigStringKey(key) ? value.trim() : value) as T
  }

  if (Array.isArray(value)) {
    return value.map((item) => trimConfigStringFields(item)) as T
  }

  if (!isPlainObject(value)) {
    return value
  }

  return Object.fromEntries(
    Object.entries(value).map(([entryKey, entryValue]) => [
      entryKey,
      trimConfigStringFields(entryValue, entryKey),
    ]),
  ) as T
}

export const trimUrlFields = trimConfigStringFields
