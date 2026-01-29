'use client'

import { ChevronUp, Sparkles } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import type { ModelProvider, AvailableModel } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

import { ModelListItem } from './model-list-item'

interface ModelListProps {
  provider: ModelProvider
  models: AvailableModel[]
  onCollapse: () => void
}

export function ModelList({ provider, models, onCollapse }: ModelListProps) {
  const { t } = useTranslation()

  // Sort by default model, default models first
  const sortedModels = [...models].sort((a, b) => {
    if (a.is_default && !b.is_default) return -1
    if (!a.is_default && b.is_default) return 1
    if (a.is_available && !b.is_available) return -1
    if (!a.is_available && b.is_available) return 1
    return 0
  })

  return (
    <div className="border-t border-gray-100">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-gray-50/80">
        <div className="flex items-center gap-2 text-xs font-medium text-gray-500">
          <Sparkles size={12} className="text-gray-400" />
          <span>{t('settings.modelsNum', { num: models.length })}</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[10px] text-gray-500 hover:text-gray-700 hover:bg-gray-100"
          onClick={onCollapse}
        >
          <ChevronUp className="mr-1 w-3 h-3" />
          {t('settings.collapse')}
        </Button>
      </div>

      {/* Models List */}
      <div className="max-h-[280px] overflow-y-auto">
        {sortedModels.map((model, index) => (
          <ModelListItem
            key={model.name}
            model={model}
            provider={provider}
            isLast={index === sortedModels.length - 1}
          />
        ))}
        {models.length === 0 && (
          <div className="px-4 py-8 text-center">
            <div className="text-gray-300 mb-2">
              <Sparkles size={24} className="mx-auto" />
            </div>
            <p className="text-sm text-gray-400">
              {t('settings.noModelsAvailable')}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
