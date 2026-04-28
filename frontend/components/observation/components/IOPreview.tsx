import { IOPreviewPretty } from './IOPreviewPretty'
import { IOPreviewJSON } from './IOPreviewJSON'

interface IOPreviewProps {
  input: unknown
  output: unknown
  metadata?: Record<string, unknown> | null
  observationName?: string
  currentView: 'pretty' | 'json'
}

export function IOPreview({
  input,
  output,
  metadata,
  observationName,
  currentView,
}: IOPreviewProps) {
  if (currentView === 'json') {
    return <IOPreviewJSON input={input} output={output} metadata={metadata} />
  }
  return (
    <IOPreviewPretty
      input={input}
      output={output}
      observationName={observationName}
    />
  )
}
