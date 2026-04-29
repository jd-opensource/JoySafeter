import { memo } from 'react'
import { Copy, Check } from 'lucide-react'
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard'
import type { JsonTableRow } from '../lib/jsonTable'

const MAX_DISPLAY_CHARS = 2000
const SMALL_ARRAY_THRESHOLD = 5
const ARRAY_PREVIEW_ITEMS = 3

const PREVIEW_CLASSES = 'italic text-gray-500 dark:text-gray-400'

function getCopyValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function renderArrayPreview(arr: unknown[]) {
  if (arr.length === 0)
    return <span className={PREVIEW_CLASSES}>empty list</span>
  if (arr.length <= SMALL_ARRAY_THRESHOLD) {
    const items = arr.map((item) => {
      if (typeof item === 'string') return `"${item}"`
      if (typeof item === 'object' && item !== null) return Array.isArray(item) ? '[...]' : '{...}'
      return String(item)
    })
    return <span className={PREVIEW_CLASSES}>[{items.join(', ')}]</span>
  }
  const preview = arr.slice(0, ARRAY_PREVIEW_ITEMS).map((item) => {
    if (typeof item === 'string') return `"${item}"`
    if (typeof item === 'object' || Array.isArray(item)) return '...'
    return String(item)
  })
  return (
    <span className={PREVIEW_CLASSES}>
      [{preview.join(', ')}, ...{arr.length - ARRAY_PREVIEW_ITEMS} more]
    </span>
  )
}

function renderObjectPreview(obj: Record<string, unknown>) {
  const keys = Object.keys(obj)
  if (keys.length === 0)
    return <span className={PREVIEW_CLASSES}>empty object</span>
  return <span className={PREVIEW_CLASSES}>{keys.length} items</span>
}

interface JsonValueCellProps {
  row: JsonTableRow
  expandedCells: Set<string>
  toggleCellExpansion: (cellId: string) => void
}

export const JsonValueCell = memo(function JsonValueCell({
  row,
  expandedCells,
  toggleCellExpansion,
}: JsonValueCellProps) {
  const { value, type } = row
  const cellId = `${row.id}-value`
  const isCellExpanded = expandedCells.has(cellId)
  const { copied, handleCopy } = useCopyToClipboard(1500)

  const onCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    handleCopy(getCopyValue(value))
  }

  let content: React.ReactNode
  let needsTruncation = false

  switch (type) {
    case 'string': {
      const str = String(value)
      needsTruncation = str.length > MAX_DISPLAY_CHARS
      const display = needsTruncation && !isCellExpanded
        ? str.substring(0, MAX_DISPLAY_CHARS) + '...'
        : str
      content = (
        <span className="whitespace-pre-line text-green-600 dark:text-green-400">
          &quot;{display}&quot;
        </span>
      )
      break
    }
    case 'number':
      content = <span className="text-blue-600 dark:text-blue-400">{String(value)}</span>
      break
    case 'boolean':
      content = <span className="text-orange-600 dark:text-orange-400">{String(value)}</span>
      break
    case 'null':
      content = <span className="italic text-gray-500 dark:text-gray-400">null</span>
      break
    case 'undefined':
      content = <span className="text-gray-500 dark:text-gray-400">undefined</span>
      break
    case 'array':
      content = renderArrayPreview(value as unknown[])
      break
    case 'object':
      content = renderObjectPreview(value as Record<string, unknown>)
      break
    default:
      content = <span className="text-gray-600">{String(value)}</span>
  }

  return (
    <div className="group relative max-w-full font-mono text-xs break-words">
      <span className="cursor-text">{content}</span>
      {needsTruncation && !row.hasChildren && (
        <span
          className="inline cursor-pointer opacity-50"
          onClick={(e) => {
            e.stopPropagation()
            toggleCellExpansion(cellId)
          }}
        >
          {isCellExpanded
            ? '\n...collapse'
            : `\n...expand (${String(value).length - MAX_DISPLAY_CHARS} more characters)`}
        </span>
      )}
      <button
        className="absolute right-0 top-0 flex h-5 w-5 items-center justify-center rounded border bg-background/80 p-0.5 opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
        onClick={onCopy}
        title="Copy value"
      >
        {copied ? (
          <Check className="h-2.5 w-2.5 text-green-600" />
        ) : (
          <Copy className="h-2.5 w-2.5 text-muted-foreground" />
        )}
      </button>
    </div>
  )
})
