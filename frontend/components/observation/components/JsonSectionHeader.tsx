import { Copy, Check, UnfoldVertical, FoldVertical } from 'lucide-react'
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard'

interface JsonSectionHeaderProps {
  title: string
  data: unknown
  allExpanded: boolean
  onToggleExpandAll: () => void
  showExpandButton?: boolean
}

export function JsonSectionHeader({
  title,
  data,
  allExpanded,
  onToggleExpandAll,
  showExpandButton = true,
}: JsonSectionHeaderProps) {
  const { copied, handleCopy } = useCopyToClipboard(1500)

  const onCopy = () => {
    const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
    handleCopy(text)
  }

  return (
    <div className="group flex items-center justify-between px-3 py-1.5 text-sm font-medium capitalize">
      <span>{title}</span>
      <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        {showExpandButton && (
          <button
            className="flex h-6 w-6 items-center justify-center rounded hover:bg-muted"
            onClick={onToggleExpandAll}
            title={allExpanded ? 'Collapse all rows' : 'Expand all rows'}
          >
            {allExpanded ? (
              <FoldVertical className="h-3.5 w-3.5 text-muted-foreground" />
            ) : (
              <UnfoldVertical className="h-3.5 w-3.5 text-muted-foreground" />
            )}
          </button>
        )}
        <button
          className="flex h-6 w-6 items-center justify-center rounded hover:bg-muted"
          onClick={onCopy}
          title="Copy section"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-green-600" />
          ) : (
            <Copy className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </button>
      </div>
    </div>
  )
}
