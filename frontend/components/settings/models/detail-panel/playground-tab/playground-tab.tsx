'use client'

import { useState } from 'react'
import { Send, Square, RotateCcw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useAvailableModels } from '@/hooks/queries/models'
import { useTestModelStream } from '@/hooks/use-test-model-stream'
import type { ModelProvider } from '@/types/models'

interface PlaygroundTabProps {
  providerName: string
  provider: ModelProvider
}

const DEFAULT_PROMPT = 'Hello, please briefly introduce yourself.'

export function PlaygroundTab({ providerName }: PlaygroundTabProps) {
  const { data: availableModels = [] } = useAvailableModels('chat')
  const providerModels = availableModels.filter(
    (m) => m.provider_name === providerName && m.is_available,
  )

  const [selectedModel, setSelectedModel] = useState<string>('')
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)

  const { output, metrics, error, isStreaming, run, stop, reset } = useTestModelStream()

  const effectiveModel = selectedModel || providerModels[0]?.name || ''

  const handleRun = () => {
    if (!effectiveModel || !prompt.trim()) return
    run({ model_name: effectiveModel, input: prompt.trim() })
  }

  const handleReset = () => {
    reset()
    setPrompt(DEFAULT_PROMPT)
  }

  if (providerModels.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center text-[var(--text-muted)]">
        <p className="text-sm">No available models for this provider. Please configure credentials first.</p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Model selector */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-[var(--text-muted)] shrink-0">Model</span>
        <select
          value={effectiveModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          className="flex-1 rounded-md border border-[var(--border-muted)] bg-[var(--surface-elevated)] px-2 py-1 text-sm text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--border-focus)]"
        >
          {providerModels.map((m) => (
            <option key={m.name} value={m.name}>
              {m.display_name || m.name}
            </option>
          ))}
        </select>
      </div>

      {/* Prompt input */}
      <div className="flex flex-col gap-1.5">
        <span className="text-xs text-[var(--text-muted)]">Input</span>
        <Textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Enter test text..."
          rows={4}
          className="resize-none text-sm"
          disabled={isStreaming}
        />
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        {isStreaming ? (
          <Button size="sm" variant="destructive" onClick={stop} className="gap-1.5">
            <Square className="h-3.5 w-3.5" />
            Stop
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={handleRun}
            disabled={!effectiveModel || !prompt.trim()}
            className="gap-1.5"
          >
            <Send className="h-3.5 w-3.5" />
            Run
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={handleReset} disabled={isStreaming} className="gap-1.5">
          <RotateCcw className="h-3.5 w-3.5" />
          Reset
        </Button>
      </div>

      {/* Output */}
      {(output || error || isStreaming) && (
        <div className="flex flex-col gap-1.5 flex-1 min-h-0">
          <span className="text-xs text-[var(--text-muted)]">Output</span>
          <div className="flex-1 min-h-[120px] rounded-md border border-[var(--border-muted)] bg-[var(--surface-3)] p-3 overflow-y-auto">
            {error ? (
              <p className="text-sm text-[var(--status-error)]">{error}</p>
            ) : (
              <p className="text-sm text-[var(--text-primary)] whitespace-pre-wrap break-words">
                {output}
                {isStreaming && (
                  <span className="inline-block w-1.5 h-4 ml-0.5 bg-[var(--text-primary)] animate-pulse align-middle" />
                )}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Metrics */}
      {metrics && !isStreaming && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 rounded-md border border-[var(--border-muted)] bg-[var(--surface-3)] px-3 py-2">
          <MetricItem label="First token" value={`${metrics.ttft_ms} ms`} />
          <MetricItem label="Total time" value={`${metrics.total_time_ms} ms`} />
          <MetricItem label="Input tokens" value={String(metrics.input_tokens)} />
          <MetricItem label="Output tokens" value={String(metrics.output_tokens)} />
          <MetricItem label="Speed" value={`${metrics.tokens_per_second} tok/s`} />
        </div>
      )}
    </div>
  )
}

function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-xs text-[var(--text-muted)]">{label}:</span>
      <span className="text-xs font-medium text-[var(--text-primary)]">{value}</span>
    </div>
  )
}
