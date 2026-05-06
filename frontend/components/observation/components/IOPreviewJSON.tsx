import { Copy, Check, ChevronRight, ChevronDown } from 'lucide-react'
import { JsonView } from '@/components/execution/JsonView'
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard'
import { useObservationJsonExpansion } from '../contexts/ObservationJsonExpansionContext'

interface IOPreviewJSONProps {
  input: unknown
  output: unknown
  metadata?: Record<string, unknown> | null
}

function JsonSection({
  label,
  data,
  expanded,
  onToggle,
}: {
  label: string
  data: unknown
  expanded: boolean
  onToggle: () => void
}) {
  const { copied, handleCopy } = useCopyToClipboard(1500)
  if (data == null) return null

  const onCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    handleCopy(JSON.stringify(data, null, 2))
  }

  return (
    <div className="border-b last:border-b-0">
      <button
        className="group flex w-full items-center justify-between px-3 py-2 text-left text-sm font-medium text-foreground hover:bg-muted/50"
        onClick={onToggle}
      >
        <div className="flex items-center gap-1.5">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          )}
          {label}
        </div>
        <div
          role="button"
          tabIndex={0}
          className="flex h-6 w-6 items-center justify-center rounded opacity-0 transition-opacity hover:bg-muted group-hover:opacity-100"
          onClick={onCopy}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onCopy(e as unknown as React.MouseEvent)
            }
          }}
          title="Copy section"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-green-600" />
          ) : (
            <Copy className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </div>
      </button>
      {expanded && (
        <div className="px-3 pb-3">
          <JsonView data={data} />
        </div>
      )}
    </div>
  )
}

export function IOPreviewJSON({ input, output, metadata }: IOPreviewJSONProps) {
  const { jsonExpansion, setJsonFieldExpansion } = useObservationJsonExpansion()

  return (
    <div>
      <JsonSection
        label="Input"
        data={input}
        expanded={jsonExpansion.input}
        onToggle={() => setJsonFieldExpansion('input', !jsonExpansion.input)}
      />
      <JsonSection
        label="Output"
        data={output}
        expanded={jsonExpansion.output}
        onToggle={() => setJsonFieldExpansion('output', !jsonExpansion.output)}
      />
      <JsonSection
        label="Metadata"
        data={metadata}
        expanded={jsonExpansion.metadata}
        onToggle={() => setJsonFieldExpansion('metadata', !jsonExpansion.metadata)}
      />
    </div>
  )
}
