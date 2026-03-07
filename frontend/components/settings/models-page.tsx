'use client'

import { AlertTriangle, Loader2, Brain, Plus } from 'lucide-react'
import React from 'react'

import { ModelProviderAddedCard } from '@/app/settings/models/components/provider-added-card'
import { ModelProviderCard } from '@/app/settings/models/components/provider-card'
import { useModelProviders, useModelCredentials, useModelProvidersByConfig } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

export function ModelsPage() {
  const { t } = useTranslation()

  const { data: providers = [], isLoading: providersLoading } = useModelProviders()
  const { data: credentials = [], isLoading: credentialsLoading } = useModelCredentials()
  const {
    credentialsByProvider,
    configuredProviders,
    notConfiguredProviders,
    noValidCredential,
  } = useModelProvidersByConfig(providers, credentials)

  // 分组逻辑：
  // 1. 已配置的供应商（由 credentialsByProvider 决定）
  // 2. 未配置的系统供应商 (provider_type === 'system')
  // 3. 模板供应商 (is_template === true)

  const configuredProvidersList = configuredProviders
  const notConfiguredSystemProviders = notConfiguredProviders.filter(p => p.provider_type === 'system' && !p.is_template)
  const templateProviders = providers.filter(p => p.is_template)

  if (providersLoading || credentialsLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-bold flex items-center gap-2 text-gray-900">
          <Brain className="text-blue-500" size={20} />
          {t('settings.models')}
        </h2>
      </div>

      {noValidCredential && (
        <div className="flex items-center px-4 py-3 mb-4 bg-amber-50 rounded-xl border border-amber-200">
          <AlertTriangle className="mr-2 w-4 h-4 text-amber-500 shrink-0" />
          <span className="text-xs font-medium text-amber-700">
            {t('settings.noValidCredential')}
          </span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {/* 已配置的供应商 */}
        {configuredProvidersList.length > 0 && (
          <div className="pb-4 space-y-3">
            {configuredProvidersList.map(provider => {
              const credential = credentialsByProvider.get(provider.provider_name)
              return (
                <ModelProviderAddedCard
                  key={provider.provider_name}
                  provider={provider}
                  credential={credential}
                />
              )
            })}
          </div>
        )}

        {/* 添加系统模型供应商 */}
        {notConfiguredSystemProviders.length > 0 && (
          <>
            <div className="flex items-center gap-3 mb-3 mt-2">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest shrink-0">
                <Plus size={12} />
                {t('settings.addModelProvider')}
              </div>
              <div className="flex-1 h-px bg-gray-200" />
            </div>
            <div className="grid grid-cols-3 gap-3 pb-4">
              {notConfiguredSystemProviders.map(provider => (
                <ModelProviderCard key={provider.provider_name} provider={provider} />
              ))}
            </div>
          </>
        )}

        {/* 自定义模型/模板（独立分组） */}
        {templateProviders.length > 0 && (
          <>
            <div className="flex items-center gap-3 mb-3 mt-2">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest shrink-0">
                {t('settings.customModels')}
              </div>
              <div className="flex-1 h-px bg-gray-200" />
            </div>
            <div className="grid grid-cols-3 gap-3 pb-4">
              {templateProviders.map(provider => (
                <ModelProviderCard key={provider.provider_name} provider={provider} />
              ))}
            </div>
          </>
        )}

        {providers.length === 0 && (
          <div className="flex flex-col items-center justify-center h-64">
            <div className="p-6 rounded-full bg-gray-100 border border-gray-200 mb-4">
              <Brain size={32} className="text-gray-300" />
            </div>
            <p className="text-sm font-medium text-gray-500">{t('settings.noModelProviders')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
