export interface JsonTableRow {
  id: string
  key: string
  value: unknown
  type: 'string' | 'number' | 'boolean' | 'object' | 'array' | 'null' | 'undefined'
  hasChildren: boolean
  level: number
  subRows?: JsonTableRow[]
  rawChildData?: unknown
  childrenGenerated?: boolean
}

function getValueType(value: unknown): JsonTableRow['type'] {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  if (Array.isArray(value)) return 'array'
  return typeof value as JsonTableRow['type']
}

function hasChildren(value: unknown, valueType: JsonTableRow['type']): boolean {
  return (
    (valueType === 'object' && Object.keys(value as Record<string, unknown>).length > 0) ||
    (valueType === 'array' && Array.isArray(value) && value.length > 0)
  )
}

const MAX_DEPTH = 25

export function transformJsonToTableData(
  json: unknown,
  parentKey = '',
  level = 0,
  parentId = '',
  lazy = false,
): JsonTableRow[] {
  if (level > MAX_DEPTH) return []

  if (typeof json !== 'object' || json === null) {
    return [
      {
        id: parentId || '0',
        key: parentKey || 'root',
        value: json,
        type: getValueType(json),
        hasChildren: false,
        level,
      },
    ]
  }

  const entries: [string, unknown][] = Array.isArray(json)
    ? json.map((item, index) => [String(index), item])
    : Object.entries(json)

  return entries.map(([key, value]) => {
    const id = parentId ? `${parentId}-${key}` : key
    const valueType = getValueType(value)
    const childrenExist = hasChildren(value, valueType)

    const row: JsonTableRow = {
      id,
      key,
      value,
      type: valueType,
      hasChildren: childrenExist,
      level,
      childrenGenerated: false,
    }

    if (childrenExist) {
      if (lazy && level === 0) {
        row.rawChildData = value
        row.subRows = []
      } else {
        row.subRows = transformJsonToTableData(value, key, level + 1, id, lazy)
        row.childrenGenerated = true
      }
    }

    return row
  })
}

export function getRowChildren(row: JsonTableRow): JsonTableRow[] {
  if (row.subRows && row.subRows.length > 0) return row.subRows
  if (row.rawChildData && row.level <= MAX_DEPTH) {
    return transformJsonToTableData(row.rawChildData, row.key, row.level + 1, row.id, false)
  }
  return []
}

export function getEmptyValueDisplay(value: unknown): string | null {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  if (value === '') return 'empty string'
  if (typeof value === 'object' && Object.keys(value as object).length === 0)
    return Array.isArray(value) ? 'empty list' : 'empty object'
  return null
}

export function findOptimalExpansionLevel(rows: JsonTableRow[], maxRows = 20): number {
  let bestLevel = 0
  for (let level = 1; level <= 5; level++) {
    const count = countVisibleRows(rows, level)
    if (count <= maxRows) bestLevel = level
    else break
  }
  return bestLevel
}

function countVisibleRows(rows: JsonTableRow[], maxExpandLevel: number): number {
  let count = 0
  const stack = [...rows]
  while (stack.length > 0) {
    const row = stack.pop()!
    count++
    if (row.hasChildren && row.level < maxExpandLevel && row.subRows) {
      stack.push(...row.subRows)
    }
  }
  return count
}
