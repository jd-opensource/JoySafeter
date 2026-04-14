'use client'

import { Loader2 } from 'lucide-react'
import { useMemo } from 'react'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SelectGroup,
  SelectLabel,
  SelectSeparator,
} from '@/components/ui/select'
import { useAvailableModels } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

import { ModelOption } from '../../services/agentService'

/**
 * Split a combined model id "provider:model_name" into [provider, model_name].
 * Only splits on the FIRST colon so Ollama-style names like "ollama:qwen3.5:latest"
 * correctly yield ["ollama", "qwen3.5:latest"] instead of truncating the tag.
 */
function splitModelId(id: string): [string, string] {
  const idx = id.indexOf(':')
  if (idx === -1) return ['', id]
  return [id.slice(0, idx), id.slice(idx + 1)]
}

interface ModelSelectFieldProps {
  value: string
  onChange: (val: unknown) => void
  onModelChange?: (modelName: string, providerName: string) => void
}

export function ModelSelectField({ value, onChange, onModelChange }: ModelSelectFieldProps) {
  const { t } = useTranslation()

  const {
    data: availableModelsData = [],
    isLoading: loading,
    error: queryError,
  } = useAvailableModels('chat')

  // Convert AvailableModel[] to ModelOption[] and deduplicate by id (provider_name:name)
  const models: ModelOption[] = useMemo(() => {
    const modelMap: Record<string, ModelOption> = {}

    for (const model of availableModelsData || []) {
      const id = `${model.provider_name}:${model.name}`
      if (!modelMap[id]) {
        modelMap[id] = {
          id,
          name: model.name,
          label: model.display_name || model.name,
          provider: model.provider_display_name || model.provider_name,
          provider_name: model.provider_name,
          isAvailable: model.is_available,
        }
      } else {
        const existing = modelMap[id]
        modelMap[id] = {
          ...existing,
          isAvailable: existing.isAvailable || model.is_available,
          label: model.display_name || existing.label,
        }
      }
    }

    return Object.values(modelMap)
  }, [availableModelsData])

  const error = useMemo(() => {
    if (queryError) {
      return queryError instanceof Error
        ? queryError.message
        : t('workspace.failedToLoadModels', { defaultValue: 'Failed to load models' })
    }
    if (models.length === 0 && !loading) {
      return t('workspace.noModelsAvailable', { defaultValue: 'No models available' })
    }
    return null
  }, [queryError, models.length, loading, t])

  // Convert value to new format if it's in old format (backward compatibility)
  const normalizedValue = useMemo(() => {
    if (!value) return value
    // If value is already in new format (contains ':'), use it as is
    if (value.includes(':')) return value
    // If value is in old format (name only), try to find matching model and convert to new format
    const matchedModel = models.find((m) => {
      const [, modelName] = splitModelId(m.id)
      return modelName === value
    })
    return matchedModel ? matchedModel.id : value
  }, [value, models])

  if (loading) {
    return (
      <div className="flex h-8 w-full items-center rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] px-3 text-xs italic text-[var(--text-muted)]">
        <Loader2 className="mr-2 h-3 w-3 animate-spin" />
        {t('workspace.initializing')}
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-8 w-full items-center rounded-md border border-[var(--status-error-border)] bg-[var(--status-error-bg)] px-3 text-xs text-[var(--status-error)]">
        {error}
      </div>
    )
  }

  // Utility function to group by provider
  const groupByProvider = (modelList: ModelOption[]): Map<string, ModelOption[]> => {
    const grouped = new Map<string, ModelOption[]>()
    modelList.forEach((model) => {
      const provider = model.provider || t('workspace.other', { defaultValue: 'Other' })
      if (!grouped.has(provider)) {
        grouped.set(provider, [])
      }
      grouped.get(provider)!.push(model)
    })
    // Sort models in each group by label
    grouped.forEach((modelArray) => {
      modelArray.sort((a, b) => a.label.localeCompare(b.label))
    })
    return grouped
  }

  // Separate available and unavailable models
  const availableModels = models.filter((m) => m.isAvailable !== false)
  const unavailableModels = models.filter((m) => m.isAvailable === false)

  // Group by provider
  const availableGroups = groupByProvider(availableModels)
  const unavailableGroups = groupByProvider(unavailableModels)

  // Get provider list (sorted)
  const availableProviders = Array.from(availableGroups.keys()).sort()
  const unavailableProviders = Array.from(unavailableGroups.keys()).sort()

  const handleValueChange = (selectedModelId: string) => {
    // Find the selected model
    let selectedModel = models.find((m) => m.id === selectedModelId)

    // Backward compatibility: try matching by model name only (old format)
    if (!selectedModel && !selectedModelId.includes(':')) {
      selectedModel = models.find((m) => {
        const [, modelName] = splitModelId(m.id)
        return modelName === selectedModelId
      })
    }

    if (selectedModel) {
      onChange(selectedModel.id)

      // Pass raw API model name + provider_name (no split truncation)
      if (onModelChange) {
        onModelChange(selectedModel.name, selectedModel.provider_name)
      }
    } else {
      onChange(selectedModelId)
    }
  }

  return (
    <Select value={normalizedValue || undefined} onValueChange={handleValueChange}>
      <SelectTrigger className="h-8 w-full text-xs">
        <SelectValue placeholder={t('workspace.selectModel')} />
      </SelectTrigger>
      <SelectContent>
        {/* Render available models, grouped by provider */}
        {availableProviders.map((provider) => {
          const providerModels = availableGroups.get(provider)!
          return (
            <SelectGroup key={provider}>
              <SelectLabel className="flex items-center gap-2 px-2 py-1.5 !pl-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                <span>{provider}</span>
                <div className="h-px flex-1 bg-[var(--border)]" />
              </SelectLabel>
              {providerModels.map((model) => (
                <SelectItem key={model.id} value={model.id} className="text-xs">
                  {model.label}
                </SelectItem>
              ))}
            </SelectGroup>
          )
        })}

        {/* Separator between available and unavailable models */}
        {availableProviders.length > 0 && unavailableProviders.length > 0 && (
          <SelectSeparator className="my-1" />
        )}

        {/* Render unavailable models, grouped by provider */}
        {unavailableProviders.map((provider) => {
          const providerModels = unavailableGroups.get(provider)!
          return (
            <SelectGroup key={`unavailable-${provider}`}>
              <SelectLabel className="flex items-center gap-2 px-2 py-1.5 !pl-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                <span>{provider}</span>
                <div className="h-px flex-1 bg-[var(--border)]" />
              </SelectLabel>
              {providerModels.map((model) => (
                <SelectItem
                  key={model.id}
                  value={model.id}
                  className="text-xs text-[var(--text-muted)]"
                  disabled
                >
                  {model.label}
                </SelectItem>
              ))}
            </SelectGroup>
          )
        })}
      </SelectContent>
    </Select>
  )
}
