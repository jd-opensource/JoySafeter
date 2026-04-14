'use client'

import { useCallback, useMemo, useState } from 'react'

import { useAvailableModels } from '@/hooks/queries/models'

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

  // Accept combined id from UI select, split into provider_name + model_name
  const setSelectedModel = useCallback(
    (id: string | undefined) => {
      if (!id) {
        setSelected(undefined)
        return
      }
      const option = modelOptions.find((m) => m.id === id)
      if (option) {
        setSelected({ provider_name: option.provider_name, model_name: option.name })
      } else {
        // Fallback: split on first colon
        const idx = id.indexOf(':')
        if (idx !== -1) {
          setSelected({ provider_name: id.slice(0, idx), model_name: id.slice(idx + 1) })
        } else {
          setSelected({ provider_name: '', model_name: id })
        }
      }
    },
    [modelOptions],
  )

  // Combined id for UI select value binding
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
