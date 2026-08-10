export function parseCollection<T>(response: unknown, parseItem: (item: unknown) => T): T[] {
  const raw = response as unknown[] | { data?: unknown[] }
  return (Array.isArray(raw) ? raw : raw.data || []).map((item) => parseItem(item))
}
