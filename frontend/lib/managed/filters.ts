export function filterByCreatedTime(createdAt: string, filter: string): boolean {
  if (filter === 'all') return true
  if (!createdAt) return false
  const now = Date.now()
  const created = new Date(createdAt).getTime()
  if (Number.isNaN(created)) return false
  const diffMs = now - created
  switch (filter) {
    case '1h': return diffMs <= 3_600_000
    case '24h': return diffMs <= 86_400_000
    case '7d': return diffMs <= 604_800_000
    case '30d': return diffMs <= 2_592_000_000
    case '90d': return diffMs <= 7_776_000_000
    default: return true
  }
}

export function createCreatedTimeFilter(t: (key: string) => string) {
  return {
    key: 'created',
    label: t('managed.filters.created'),
    options: [
      { value: 'all', label: t('managed.filters.allTime') },
      { value: '1h', label: t('managed.filters.lastHour') },
      { value: '24h', label: t('managed.filters.last24h') },
      { value: '7d', label: t('managed.filters.last7d') },
    ],
  }
}

export function matchesSearch(query: string, values: Array<unknown>): boolean {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return true
  return values.some((value) => String(value ?? '').toLowerCase().includes(normalized))
}
