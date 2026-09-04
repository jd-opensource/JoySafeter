export interface ManagedCursorPage<Item, CursorId extends string> {
  items: Item[]
  hasMore: boolean
  firstId?: CursorId
  lastId?: CursorId
}

interface CollectManagedCursorPagesOptions<Item, CursorId extends string> {
  fetchPage: (afterId?: CursorId) => Promise<ManagedCursorPage<Item, CursorId>>
  responseName?: string
}

interface ParseManagedCursorPageOptions<Item, CursorId extends string> {
  parseItem: (item: unknown) => Item
  parseCursor: (cursor: string) => CursorId
  responseName?: string
}

export function parseManagedCursorPage<Item, CursorId extends string>(
  response: unknown,
  {
    parseItem,
    parseCursor,
    responseName = 'managed cursor page response',
  }: ParseManagedCursorPageOptions<Item, CursorId>,
): ManagedCursorPage<Item, CursorId> {
  if (!response || typeof response !== 'object' || Array.isArray(response)) {
    throw new Error(`Invalid ${responseName}`)
  }

  const raw = response as {
    data?: unknown
    has_more?: unknown
    first_id?: unknown
    last_id?: unknown
  }
  if (!Array.isArray(raw.data) || typeof raw.has_more !== 'boolean') {
    throw new Error(`Invalid ${responseName}`)
  }
  if (
    (raw.first_id !== undefined && raw.first_id !== null && typeof raw.first_id !== 'string') ||
    (raw.last_id !== undefined && raw.last_id !== null && typeof raw.last_id !== 'string')
  ) {
    throw new Error(`Invalid ${responseName}`)
  }
  if (raw.has_more && (raw.data.length === 0 || typeof raw.last_id !== 'string')) {
    throw new Error(`Invalid ${responseName}`)
  }

  return {
    items: raw.data.map(parseItem),
    hasMore: raw.has_more,
    firstId: typeof raw.first_id === 'string' ? parseCursor(raw.first_id) : undefined,
    lastId: typeof raw.last_id === 'string' ? parseCursor(raw.last_id) : undefined,
  }
}

export async function collectManagedCursorPages<Item, CursorId extends string>({
  fetchPage,
  responseName = 'managed cursor pagination',
}: CollectManagedCursorPagesOptions<Item, CursorId>): Promise<Item[]> {
  const items: Item[] = []
  const seenCursors = new Set<CursorId>()
  let afterId: CursorId | undefined

  for (;;) {
    const page = await fetchPage(afterId)
    items.push(...page.items)
    if (!page.hasMore) return items

    const nextCursor = page.lastId
    if (!nextCursor || nextCursor === afterId || seenCursors.has(nextCursor)) {
      throw new Error(`${responseName} returned an invalid cursor`)
    }
    seenCursors.add(nextCursor)
    afterId = nextCursor
  }
}
