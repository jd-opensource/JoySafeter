'use client'

import { cn } from '@/lib/utils'
import { useObservationData } from '../contexts/ObservationDataContext'
import { useObservationSelection } from '../contexts/ObservationSelectionContext'
import { useStreamingText } from '../contexts/StreamingTextContext'
import { ObservationDetailHeader } from './ObservationDetailHeader'
import { IOPreview } from './IOPreview'
import { PrettyJsonView } from './PrettyJsonView'
import {
  formatIntervalSeconds,
  usdFormatter,
} from '../lib/helpers'
import type { ObservationNode } from '../lib/types'

function TraceSummaryView() {
  const { roots } = useObservationData()

  if (roots.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No trace data. Run a debug execution or select a historical trace.
      </div>
    )
  }

  const totalCost = roots.reduce((sum, r) => sum + r.totalCost, 0)
  const totalDuration = Math.max(...roots.map((r) => r.latency ?? 0))

  return (
    <div className="space-y-2 p-4">
      <h3 className="text-sm font-medium">Trace Summary</h3>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="text-muted-foreground">Duration</div>
        <div>{formatIntervalSeconds(totalDuration)}</div>
        <div className="text-muted-foreground">Total Cost</div>
        <div>{usdFormatter(totalCost)}</div>
      </div>
    </div>
  )
}

function StreamingTextView({ text }: { text: string }) {
  return (
    <div className="space-y-2 px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
        <span className="text-xs font-medium text-muted-foreground">Streaming</span>
      </div>
      <div className="whitespace-pre-wrap rounded-sm bg-muted/30 p-3 font-mono text-xs leading-relaxed">
        {text}
        <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-foreground align-middle" />
      </div>
    </div>
  )
}

function ViewPrefToggle() {
  const { viewPref, setViewPref } = useObservationSelection()

  return (
    <div className="ml-auto flex items-center gap-0.5 rounded-md bg-muted p-0.5">
      <button
        className={cn(
          'rounded px-2 py-0.5 text-xs transition-colors',
          viewPref === 'formatted' && 'bg-background shadow-sm',
        )}
        onClick={() => setViewPref('formatted')}
      >
        Formatted
      </button>
      <button
        className={cn(
          'rounded px-2 py-0.5 text-xs transition-colors',
          viewPref === 'json' && 'bg-background shadow-sm',
        )}
        onClick={() => setViewPref('json')}
      >
        JSON
      </button>
    </div>
  )
}

function ObservationDetail({ node }: { node: ObservationNode }) {
  const { viewPref } = useObservationSelection()
  const streamingText = useStreamingText(node.id)
  const isStreaming = streamingText !== undefined && node.endTime === null

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <ObservationDetailHeader node={node} />

      <div className="flex h-9 shrink-0 items-center border-b px-3">
        <span className="text-xs font-medium text-foreground">Preview</span>
        <ViewPrefToggle />
      </div>

      <div className="flex-1 overflow-auto">
        {isStreaming ? (
          <>
            {node.input != null && (
              <PrettyJsonView data={node.input} title="Input" section="input" />
            )}
            <StreamingTextView text={streamingText ?? ''} />
          </>
        ) : (
          <IOPreview
            input={node.input}
            output={node.output}
            metadata={node.metadata}
            currentView={viewPref === 'formatted' ? 'pretty' : 'json'}
          />
        )}
      </div>
    </div>
  )
}

export function ObservationDetailPanel() {
  const { nodeMap } = useObservationData()
  const { selectedNodeId } = useObservationSelection()

  const selectedNode = selectedNodeId ? nodeMap.get(selectedNodeId) : null

  if (!selectedNode) return <TraceSummaryView />
  return <ObservationDetail node={selectedNode} />
}
