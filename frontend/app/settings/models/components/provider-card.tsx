'use client'

import { Plus, Sparkles } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import type { ModelProvider } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/core/utils/cn'

import { ModelCredentialDialog } from './credential-dialog'
import { ProviderIcon } from './provider-icon'

interface ModelProviderCardProps {
  provider: ModelProvider
}

export function ModelProviderCard({ provider }: ModelProviderCardProps) {
  const { t } = useTranslation()
  const [showCredentialDialog, setShowCredentialDialog] = React.useState(false)
  const isCustom = provider.provider_type === 'custom'
  const isTemplate = provider.is_template

  const supportedTypes = provider.supported_model_types || []
  const modelCount = (provider as any).model_count || supportedTypes.length

  return (
    <>
      <div
        className={cn(
          'group relative flex flex-col px-4 py-3 h-[140px] rounded-xl border shadow-sm transition-all duration-200 cursor-pointer',
          isCustom
            ? 'bg-gradient-to-br from-violet-50/90 to-indigo-50/90 border-violet-200 hover:border-violet-300 hover:shadow-md hover:shadow-violet-100/50'
            : 'bg-white border-gray-200 hover:border-blue-200 hover:shadow-md'
        )}
        onClick={() => setShowCredentialDialog(true)}
      >
        {isCustom && (
          <span className="absolute top-2 right-10 px-1.5 py-0.5 text-[9px] font-medium text-violet-600 bg-violet-100 rounded">
            {isTemplate ? t('settings.template', { defaultValue: '模板' }) : t('settings.custom', { defaultValue: '自定义' })}
          </span>
        )}
        {/* Header: Icon + Setup link */}
        <div className="flex items-start justify-between mb-2">
          <ProviderIcon provider={provider} />
          <Button
            variant="ghost"
            size="sm"
            className={cn(
              "h-6 px-2 text-[10px] font-medium",
              isTemplate ? "text-violet-600 hover:text-violet-700 hover:bg-violet-50" : "text-blue-600 hover:text-blue-700 hover:bg-blue-50"
            )}
            onClick={(e) => {
              e.stopPropagation()
              setShowCredentialDialog(true)
            }}
          >
            <Plus size={12} />
            {isTemplate ? t('settings.useTemplate', { defaultValue: '使用模板' }) : t('settings.setup')}
          </Button>
        </div>

        {/* Description */}
        {provider.description && (
          <div
            className="flex-1 leading-4 text-[11px] text-gray-500 line-clamp-2 mb-2"
            title={provider.description}
          >
            {provider.description}
          </div>
        )}

        {/* Footer: Model types + count */}
        <div className="flex items-center justify-between mt-auto pt-2 border-t border-gray-100">
          <div className="flex items-center gap-1">
            {supportedTypes.map(modelType => (
              <span
                key={modelType}
                className="px-1.5 py-0.5 text-[9px] font-medium text-gray-500 bg-gray-100 rounded"
              >
                {t(`settings.modelTypes.${modelType}` as any, { defaultValue: modelType })}
              </span>
            ))}
          </div>
          <div className="flex items-center gap-1 text-[10px] text-gray-400">
            <Sparkles size={10} />
            <span>{modelCount} {t('settings.modelsLabel')}</span>
          </div>
        </div>
      </div>

      {showCredentialDialog && (
        <ModelCredentialDialog
          provider={provider}
          open={showCredentialDialog}
          onOpenChange={setShowCredentialDialog}
        />
      )}
    </>
  )
}
