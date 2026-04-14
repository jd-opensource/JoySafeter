'use client'

import { useCallback, useMemo, useState } from 'react'

import { useAvailableModels } from '@/hooks/queries/models'
import { splitModelId } from '@/lib/utils'

export interface ModelSelectorOption {
  id: string
  label: string
  provider: string
  provider_name: string
  name: string // raw model name from API
}

export interface SelectedModel {
  provider_name: string
  model_name: string
}

/**
 * Shared hook for model selection across Chat and Copilot.
 * Returns available model options, selected model state (split fields), and a label for display.
 */
export function useModelSelector() {
  const { data: availableModels = [] } = useAvailableModels('chat')
  const [selected, setSelected] = useState<SelectedModel | undefined>(undefined)

  const modelOptions = useMemo<ModelSelectorOption[]>(
    () =>
      availableModels
        .filter((m) => m.is_available)
        .map((m) => ({
          id: `${m.provider_name}:${m.name}`,
          label: m.display_name || m.name,
          provider: m.provider_display_name || m.provider_name,
          provider_name: m.provider_name,
          name: m.name,
        })),
    [availableModels],
  )

  const setSelectedModel = useCallback(
    (id: string | undefined) => {
      if (!id) {
        setSelected(undefined)
        return
      }
      const option = modelOptions.find((m) => m.id === id)
      if (option) {
        const next = { provider_name: option.provider_name, model_name: option.name }
        setSelected((prev) =>
          prev?.provider_name === next.provider_name && prev?.model_name === next.model_name
            ? prev
            : next,
        )
      } else {
        const [provider, model] = splitModelId(id)
        setSelected((prev) =>
          prev?.provider_name === provider && prev?.model_name === model
            ? prev
            : { provider_name: provider, model_name: model },
        )
      }
    },
    [modelOptions],
  )

  const selectedModel = selected
    ? `${selected.provider_name}:${selected.model_name}`
    : undefined

  const modelLabel = useMemo(() => {
    if (selectedModel) {
      const found = modelOptions.find((m) => m.id === selectedModel)
      if (found) return found.label
    }
    return modelOptions[0]?.label ?? ''
  }, [modelOptions, selectedModel])

  return { modelOptions, selectedModel, setSelectedModel, selectedProviderName: selected?.provider_name, selectedModelName: selected?.model_name, modelLabel }
}
