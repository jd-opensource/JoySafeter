'use client'

import { useMemo, useState } from 'react'

import { useAvailableModels } from '@/hooks/queries/models'

export interface ModelSelectorOption {
  id: string
  label: string
  provider: string
}

/**
 * Shared hook for model selection across Chat and Copilot.
 * Returns available model options, selected model state, and a label for display.
 */
export function useModelSelector() {
  const { data: availableModels = [] } = useAvailableModels('chat')
  const [selectedModel, setSelectedModel] = useState<string | undefined>(undefined)

  const modelOptions = useMemo<ModelSelectorOption[]>(
    () =>
      availableModels
        .filter((m) => m.is_available)
        .map((m) => ({
          id: `${m.provider_name}:${m.name}`,
          label: m.display_name || m.name,
          provider: m.provider_display_name || m.provider_name,
        })),
    [availableModels],
  )

  const modelLabel = useMemo(() => {
    if (selectedModel) {
      const found = modelOptions.find((m) => m.id === selectedModel)
      if (found) return found.label
    }
    return modelOptions[0]?.label ?? ''
  }, [modelOptions, selectedModel])

  return { modelOptions, selectedModel, setSelectedModel, modelLabel }
}
