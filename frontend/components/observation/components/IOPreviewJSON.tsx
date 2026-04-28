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
  if (data == null) return null

  return (
    <div className="border-b last:border-b-0">
      <button
        className="flex w-full items-center gap-2 px-4 py-2 text-left text-xs font-medium text-muted-foreground hover:bg-muted/50"
        onClick={onToggle}
      >
        <span className={expanded ? 'rotate-90' : ''}>▶</span>
        {label}
      </button>
      {expanded && (
        <pre className="overflow-auto px-4 pb-3 text-xs">
          {JSON.stringify(data, null, 2)}
        </pre>
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
