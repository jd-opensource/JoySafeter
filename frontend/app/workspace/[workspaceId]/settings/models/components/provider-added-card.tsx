'use client'

import { ChevronDown, Loader2 } from 'lucide-react'
import React, { useState } from 'react'

import type { ModelProvider, ModelCredential } from '@/hooks/queries/models'
import { useAvailableModels } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

import { ModelCredentialDialog } from './credential-dialog'
import { CredentialPanel } from './credential-panel'
import { ModelList } from './model-list'
import { ProviderIcon } from './provider-icon'

interface ModelProviderAddedCardProps {
  provider: ModelProvider
  credential?: ModelCredential
  workspaceId?: string
}

export function ModelProviderAddedCard({
  provider,
  credential,
  workspaceId,
}: ModelProviderAddedCardProps) {
  const { t } = useTranslation()
  const [collapsed, setCollapsed] = useState(true)
  const [showCredentialDialog, setShowCredentialDialog] = useState(false)
  const { data: models = [], isLoading: modelsLoading } = useAvailableModels('chat', workspaceId)

  const providerModels = models.filter(m => m.provider_name === provider.provider_name)
  const hasModels = providerModels.length > 0

  const supportedTypes = provider.supported_model_types || []

  return (
    <>
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm hover:border-blue-200 hover:shadow-md transition-all duration-200 overflow-hidden">
        <div className="flex pl-4 py-3 pr-3">
          <div className="grow px-1 pt-1 pb-0.5">
            <div className="mb-2">
              <ProviderIcon provider={provider} />
            </div>
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
          </div>
          {provider.credential_schema && (
            <CredentialPanel
              provider={provider}
              credential={credential}
              onSetup={() => setShowCredentialDialog(true)}
            />
          )}
        </div>

        {collapsed && (
          <div 
            className="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 bg-gray-50/50 cursor-pointer hover:bg-gray-100/50 transition-colors"
            onClick={() => setCollapsed(false)}
          >
            <div className="flex items-center gap-2 text-xs font-medium text-gray-500">
              <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
              <span>
                {hasModels
                  ? t('settings.showModelsNum', { num: providerModels.length })
                  : t('settings.showModels')}
              </span>
              {modelsLoading && <Loader2 className="animate-spin w-3 h-3 text-gray-400" />}
            </div>
          </div>
        )}

        {!collapsed && (
          <ModelList
            provider={provider}
            models={providerModels}
            onCollapse={() => setCollapsed(true)}
          />
        )}
      </div>

      {showCredentialDialog && (
        <ModelCredentialDialog
          provider={provider}
          credential={credential}
          workspaceId={workspaceId}
          open={showCredentialDialog}
          onOpenChange={setShowCredentialDialog}
        />
      )}
    </>
  )
}

