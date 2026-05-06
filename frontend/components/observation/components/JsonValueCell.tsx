import { memo, type FC } from 'react'
import ReactMarkdown, { type Options } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Copy, Check } from 'lucide-react'
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard'
import type { JsonTableRow } from '../lib/jsonTable'

const MAX_DISPLAY_CHARS = 2000
const SMALL_ARRAY_THRESHOLD = 5
const ARRAY_PREVIEW_ITEMS = 3

const PREVIEW_CLASSES = 'italic text-gray-500 dark:text-gray-400'

const MemoizedReactMarkdown: FC<Options> = memo(ReactMarkdown)

const REMARK_PLUGINS: Options['remarkPlugins'] = [remarkGfm]

const smallHeading = ({ children }: { children?: React.ReactNode }) => (
  <span className="block text-xs font-bold">{children}</span>
)

const MARKDOWN_COMPONENTS: Options['components'] = {
  p({ children }) {
    return <span className="whitespace-pre-wrap">{children}</span>
  },
  ul({ children }) {
    return <ul className="list-inside list-disc">{children}</ul>
  },
  ol({ children }) {
    return <ol className="list-inside list-decimal">{children}</ol>
  },
  li({ children }) {
    return <li className="mt-0.5 [&>ol]:pl-4 [&>ul]:pl-4">{children}</li>
  },
  code({ children }) {
    return <code className="rounded border bg-muted px-1 py-0.5">{children}</code>
  },
  pre({ children }) {
    return (
      <pre className="my-1 overflow-auto rounded bg-black/10 p-2 dark:bg-white/10">{children}</pre>
    )
  },
  a({ children, href }) {
    return (
      <a href={href ?? undefined} className="underline" target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    )
  },
  h1({ children }) {
    return <span className="block text-base font-bold">{children}</span>
  },
  h2({ children }) {
    return <span className="block text-sm font-bold">{children}</span>
  },
  h3: smallHeading,
  h4: smallHeading,
  h5: smallHeading,
  h6: smallHeading,
  blockquote({ children }) {
    return <blockquote className="border-l-2 pl-2 italic">{children}</blockquote>
  },
  table({ children }) {
    return (
      <div className="overflow-x-auto rounded border">
        <table className="min-w-full divide-y">{children}</table>
      </div>
    )
  },
  thead({ children }) {
    return <thead>{children}</thead>
  },
  tbody({ children }) {
    return <tbody className="divide-y">{children}</tbody>
  },
  tr({ children }) {
    return <tr>{children}</tr>
  },
  th({ children }) {
    return <th className="px-2 py-1 text-left font-medium">{children}</th>
  },
  td({ children }) {
    return <td className="px-2 py-1">{children}</td>
  },
}

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
  if (arr.length === 0) return <span className={PREVIEW_CLASSES}>empty list</span>
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
  if (keys.length === 0) return <span className={PREVIEW_CLASSES}>empty object</span>
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
      const display =
        needsTruncation && !isCellExpanded ? str.substring(0, MAX_DISPLAY_CHARS) + '...' : str
      content = (
        <span className="text-green-600 dark:text-green-400">
          &quot;
          <MemoizedReactMarkdown remarkPlugins={REMARK_PLUGINS} components={MARKDOWN_COMPONENTS}>
            {display}
          </MemoizedReactMarkdown>
          &quot;
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
    <div className="group relative max-w-full break-words font-mono text-xs">
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
