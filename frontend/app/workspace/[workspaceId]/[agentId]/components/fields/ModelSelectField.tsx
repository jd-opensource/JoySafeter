'use client'

import { Loader2 } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useMemo } from 'react'


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
import type { AvailableModel } from '@/types/models'

import { ModelOption } from '../../services/agentService'

interface ModelSelectFieldProps {
  value: string
  onChange: (val: unknown) => void
  onModelChange?: (modelName: string, providerName: string) => void // Added: pass both model_name and provider_name simultaneously
}

export const ModelSelectField: React.FC<ModelSelectFieldProps> = ({ value, onChange, onModelChange }) => {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params?.workspaceId as string | undefined

  // Use React Query hook for models (with caching and request deduplication)
  const { data: availableModelsData = [], isLoading: loading, error: queryError } = useAvailableModels('chat', workspaceId)

  // Convert AvailableModel[] to ModelOption[]
  const models: ModelOption[] = useMemo(() => {
    return (availableModelsData || []).map((model: AvailableModel) => ({
      id: model.name,
      label: model.display_name || model.name,
      provider: model.provider_display_name || model.provider_name,
      provider_name: model.provider_name,
      isAvailable: model.is_available,
      isDefault: model.is_default,
    }))
  }, [availableModelsData])

  const error = useMemo(() => {
    if (queryError) {
      return queryError instanceof Error ? queryError.message : t('workspace.failedToLoadModels', { defaultValue: 'Failed to load models' })
    }
    if (models.length === 0 && !loading) {
      return t('workspace.noModelsAvailable', { defaultValue: 'No models available' })
    }
    return null
  }, [queryError, models.length, loading, t])

  if (loading) {
    return (
      <div className="flex h-8 w-full items-center rounded-md border border-gray-200 bg-white px-3 text-[10px] text-gray-400 italic">
        <Loader2 className="mr-2 h-3 w-3 animate-spin" />
        {t('workspace.initializing')}
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-8 w-full items-center rounded-md border border-red-200 bg-red-50 px-3 text-[10px] text-red-600">
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
    const selectedModel = models.find((m) => m.id === selectedModelId)
    if (selectedModel) {
      // Call original onChange (maintain backward compatibility)
      onChange(selectedModelId)
      // If onModelChange provided, pass both model_name and provider_name
      if (onModelChange) {
        onModelChange(selectedModel.id, selectedModel.provider_name)
      }
    } else {
      // If model not found, only call original onChange
      onChange(selectedModelId)
    }
  }

  return (
    <Select value={value || undefined} onValueChange={handleValueChange}>
      <SelectTrigger className="w-full h-8 text-xs">
        <SelectValue placeholder={t('workspace.selectModel')} />
      </SelectTrigger>
      <SelectContent>
        {/* Render available models, grouped by provider */}
        {availableProviders.map((provider) => {
          const providerModels = availableGroups.get(provider)!
          return (
            <SelectGroup key={provider}>
              <SelectLabel className="flex items-center gap-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-2 py-1.5 !pl-2">
                <span>{provider}</span>
                <div className="flex-1 h-px bg-gray-200" />
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
              <SelectLabel className="flex items-center gap-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-2 py-1.5 !pl-2">
                <span>{provider}</span>
                <div className="flex-1 h-px bg-gray-200" />
              </SelectLabel>
              {providerModels.map((model) => (
                <SelectItem
                  key={model.id}
                  value={model.id}
                  className="text-xs text-gray-400"
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
