'use client'

import { useMemo } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import React from 'react'

import {
  useModelProviders,
  useModelCredentials,
  useModelProvidersByConfig,
} from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

import { ModelProviderAddedCard } from './components/provider-added-card'
import { ModelProviderCard } from './components/provider-card'

const BUILTIN_PROVIDER_NAMES = ['openaiapicompatible', 'anthropic', 'gemini', 'zhipu'] as const
const CUSTOM_PROVIDER_NAME = 'custom'

export default function ModelsPage() {
  const { t } = useTranslation()

  const { data: providers = [], isLoading: providersLoading } = useModelProviders()
  const { data: credentials = [], isLoading: credentialsLoading } = useModelCredentials()
  const {
    credentialsByProvider,
    configuredProviders,
    notConfiguredProviders,
    templateProviders,
    noValidCredential,
  } = useModelProvidersByConfig(providers, credentials)

  const providerMap = useMemo(() => new Map(providers.map(p => [p.provider_name, p])), [providers])

  const builtinConfigured = useMemo(() => {
    return BUILTIN_PROVIDER_NAMES.filter(name => configuredProviders.some(p => p.provider_name === name))
      .map(name => providerMap.get(name))
      .filter((p): p is NonNullable<typeof p> => Boolean(p))
  }, [providerMap, configuredProviders])

  const builtinNotConfigured = useMemo(() => {
    return BUILTIN_PROVIDER_NAMES.filter(name => notConfiguredProviders.some(p => p.provider_name === name))
      .map(name => providerMap.get(name))
      .filter((p): p is NonNullable<typeof p> => Boolean(p))
  }, [providerMap, notConfiguredProviders])

  const customProvider = providerMap.get(CUSTOM_PROVIDER_NAME)
  const isCustomConfigured = Boolean(customProvider && credentialsByProvider.has(CUSTOM_PROVIDER_NAME))
  const customNotConfigured = customProvider && templateProviders.some(p => p.provider_name === CUSTOM_PROVIDER_NAME)

  if (providersLoading || credentialsLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-white">
        <div>
          <h2 className="text-lg font-bold text-gray-900">{t('settings.modelsTitle')}</h2>
          <p className="text-xs text-gray-500 mt-1">{t('settings.modelsDescription')}</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className={`flex items-center justify-between mb-4 h-8 ${noValidCredential && 'px-3 bg-[#FFFAEB] rounded-lg border border-[#FEF0C7]'}`}>
          {noValidCredential ? (
            <div className="flex items-center text-xs font-medium text-gray-700">
              <AlertTriangle className="mr-1 w-3 h-3 text-[#F79009]" />
              {t('settings.noValidCredential')}
            </div>
          ) : (
            <div className="text-sm font-medium text-gray-800">{t('settings.models')}</div>
          )}
        </div>

        {/* 系统内置供应商：已配置的 */}
        {builtinConfigured.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center mb-3 text-xs font-semibold text-gray-500">
              {t('settings.builtinProviders', { defaultValue: '系统内置供应商' })}
              <span className="grow ml-3 h-[1px] bg-gradient-to-r from-[#f3f4f6]" />
            </div>
            <div className="space-y-3">
              {builtinConfigured.map(provider => {
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
          </div>
        )}

        {/* 自定义模型：已配置的 */}
        {isCustomConfigured && customProvider && (
          <div className="mb-6">
            <div className="flex items-center mb-3 text-xs font-semibold text-gray-500">
              {t('settings.customModels', { defaultValue: '自定义模型' })}
              <span className="grow ml-3 h-[1px] bg-gradient-to-r from-[#f3f4f6]" />
            </div>
            <div className="space-y-3">
              <ModelProviderAddedCard
                provider={customProvider}
                credential={credentialsByProvider.get(CUSTOM_PROVIDER_NAME)}
              />
            </div>
          </div>
        )}

        {/* 添加：系统内置供应商（未配置的） */}
        {builtinNotConfigured.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center mb-3 text-xs font-semibold text-gray-500">
              + {t('settings.addModelProvider')}
              <span className="grow ml-3 h-[1px] bg-gradient-to-r from-[#f3f4f6]" />
            </div>
            <div className="grid grid-cols-3 gap-3">
              {builtinNotConfigured.map(provider => (
                <ModelProviderCard key={provider.provider_name} provider={provider} />
              ))}
            </div>
          </div>
        )}

        {/* 添加：自定义模型（未配置的） */}
        {customNotConfigured && customProvider && (
          <div className="mb-6">
            <div className="flex items-center mb-3 text-xs font-semibold text-gray-500">
              + {t('settings.customModels', { defaultValue: '自定义模型' })}
              <span className="grow ml-3 h-[1px] bg-gradient-to-r from-[#f3f4f6]" />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <ModelProviderCard provider={customProvider} />
            </div>
          </div>
        )}

        {providers.length === 0 && (
          <div className="flex flex-col items-center justify-center h-64 text-gray-400">
            <p className="text-sm">{t('settings.noModelProviders')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
