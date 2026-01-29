'use client'

import { Plus, Sparkles } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import type { ModelProvider } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

import { ModelCredentialDialog } from './credential-dialog'
import { ProviderIcon } from './provider-icon'

interface ModelProviderCardProps {
  provider: ModelProvider
  workspaceId?: string
}

export function ModelProviderCard({ provider, workspaceId }: ModelProviderCardProps) {
  const { t } = useTranslation()
  const [showCredentialDialog, setShowCredentialDialog] = React.useState(false)

  const supportedTypes = provider.supported_model_types || []
  const modelCount = (provider as any).model_count || supportedTypes.length

  return (
    <>
      <div
        className="group relative flex flex-col px-4 py-3 h-[140px] bg-white rounded-xl border border-gray-200 shadow-sm hover:border-blue-200 hover:shadow-md transition-all duration-200 cursor-pointer"
        onClick={() => setShowCredentialDialog(true)}
      >
        {/* Header: Icon + Setup link */}
        <div className="flex items-start justify-between mb-2">
          <ProviderIcon provider={provider} />
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-[10px] font-medium text-blue-600 hover:text-blue-700 hover:bg-blue-50"
            onClick={(e) => {
              e.stopPropagation()
              setShowCredentialDialog(true)
            }}
          >
            <Plus size={12} />
            {t('settings.setup')}
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
          workspaceId={workspaceId}
          open={showCredentialDialog}
          onOpenChange={setShowCredentialDialog}
        />
      )}
    </>
  )
}
