import { PrettyJsonView } from './PrettyJsonView'

interface IOPreviewPrettyProps {
  input: unknown
  output: unknown
  metadata?: Record<string, unknown> | null
}

export function IOPreviewPretty({ input, output, metadata }: IOPreviewPrettyProps) {
  return (
    <div>
      {input != null && <PrettyJsonView data={input} title="Input" section="input" />}
      {output != null && <PrettyJsonView data={output} title="Output" section="output" />}
      {metadata != null && Object.keys(metadata).length > 0 && (
        <PrettyJsonView data={metadata} title="Metadata" section="metadata" />
      )}
    </div>
  )
}
