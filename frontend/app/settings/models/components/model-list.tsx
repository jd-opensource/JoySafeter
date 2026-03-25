'use client'

import { ChevronUp, Plus, Sparkles } from 'lucide-react'
import React, { useState } from 'react'

import { Button } from '@/components/ui/button'
import type { ModelProvider, AvailableModel } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

import { AddCustomModelDialog } from './add-custom-model-dialog'
import { ModelListItem } from './model-list-item'

interface ModelListProps {
  provider: ModelProvider
  models: AvailableModel[]
  onCollapse: () => void
}

export function ModelList({ provider, models, onCollapse }: ModelListProps) {
  const { t } = useTranslation()
  const [showAddCustomModel, setShowAddCustomModel] = useState(false)
  const isCustomProvider = provider.provider_name === 'custom'

  // Sort by default model, default models first
  const sortedModels = [...models].sort((a, b) => {
    if (a.is_default && !b.is_default) return -1
    if (!a.is_default && b.is_default) return 1
    if (a.is_available && !b.is_available) return -1
    if (!a.is_available && b.is_available) return 1
    return 0
  })

  return (
    <div className="border-t border-[var(--border-muted)]">
      {/* Header */}
      <div className="flex items-center justify-between bg-[var(--surface-1)]/80 px-4 py-2.5">
        <div className="flex items-center gap-2 text-xs font-medium text-[var(--text-tertiary)]">
          <Sparkles size={12} className="text-[var(--text-muted)]" />
          <span>{t('settings.modelsNum', { num: models.length })}</span>
          {isCustomProvider && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-[10px] text-[var(--brand-600)] hover:bg-[var(--brand-50)] hover:text-blue-700"
              onClick={(e) => {
                e.stopPropagation()
                setShowAddCustomModel(true)
              }}
            >
              <Plus size={12} className="mr-1" />
              {t('settings.addCustomModel', { defaultValue: '添加自定义模型' })}
            </Button>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[10px] text-[var(--text-tertiary)] hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
          onClick={onCollapse}
        >
          <ChevronUp className="mr-1 h-3 w-3" />
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
            <div className="mb-2 text-[var(--text-subtle)]">
              <Sparkles size={24} className="mx-auto" />
            </div>
            <p className="text-sm text-[var(--text-muted)]">{t('settings.noModelsAvailable')}</p>
            {isCustomProvider && (
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => setShowAddCustomModel(true)}
              >
                <Plus size={14} className="mr-1.5" />
                {t('settings.addCustomModel', { defaultValue: '添加自定义模型' })}
              </Button>
            )}
          </div>
        )}
      </div>

      <AddCustomModelDialog
        open={showAddCustomModel}
        onOpenChange={setShowAddCustomModel}
        provider={provider}
      />
    </div>
  )
}
