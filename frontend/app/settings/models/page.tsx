'use client'

import { useMemo, useState } from 'react'
import { AlertTriangle, Loader2, Plus } from 'lucide-react'
import React from 'react'

import {
  useModelProviders,
  useModelCredentials,
  useModelProvidersByConfig,
} from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'
import { Button } from '@/components/ui/button'

import { AddCustomModelDialog } from './components/add-custom-model-dialog'
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

  const providerMap = useMemo(
    () => new Map(providers.map((p) => [p.provider_name, p])),
    [providers],
  )

  const builtinConfigured = useMemo(() => {
    return BUILTIN_PROVIDER_NAMES.filter((name) =>
      configuredProviders.some((p) => p.provider_name === name),
    )
      .map((name) => providerMap.get(name))
      .filter((p): p is NonNullable<typeof p> => Boolean(p))
  }, [providerMap, configuredProviders])

  const builtinNotConfigured = useMemo(() => {
    return BUILTIN_PROVIDER_NAMES.filter((name) =>
      notConfiguredProviders.some((p) => p.provider_name === name),
    )
      .map((name) => providerMap.get(name))
      .filter((p): p is NonNullable<typeof p> => Boolean(p))
  }, [providerMap, notConfiguredProviders])

  /** 已配置的自定义类供应商：模板 custom 或 custom-{ts}，避免与内置混在一起 */
  const customConfigured = useMemo(
    () =>
      configuredProviders.filter(
        (p) =>
          p.provider_type === 'custom' ||
          p.provider_name === CUSTOM_PROVIDER_NAME ||
          (p.provider_name != null && p.provider_name.startsWith('custom-')),
      ),
    [configuredProviders],
  )

  const customProvider = providerMap.get(CUSTOM_PROVIDER_NAME)
  const customNotConfigured =
    customProvider && templateProviders.some((p) => p.provider_name === CUSTOM_PROVIDER_NAME)

  const [showAddCustomModel, setShowAddCustomModel] = useState(false)

  if (providersLoading || credentialsLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center justify-between border-b border-gray-100 bg-white p-6">
        <div>
          <h2 className="text-lg font-bold text-gray-900">{t('settings.modelsTitle')}</h2>
          <p className="mt-1 text-xs text-gray-500">{t('settings.modelsDescription')}</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div
          className={`mb-4 flex h-8 items-center justify-between ${noValidCredential && 'rounded-lg border border-[#FEF0C7] bg-[#FFFAEB] px-3'}`}
        >
          {noValidCredential ? (
            <div className="flex items-center text-xs font-medium text-gray-700">
              <AlertTriangle className="mr-1 h-3 w-3 text-[#F79009]" />
              {t('settings.noValidCredential')}
            </div>
          ) : (
            <div className="text-sm font-medium text-gray-800">{t('settings.models')}</div>
          )}
        </div>

        {/* 系统内置供应商：已配置的 */}
        {builtinConfigured.length > 0 && (
          <div className="mb-6">
            <div className="mb-3 flex items-center text-xs font-semibold text-gray-500">
              {t('settings.builtinProviders', { defaultValue: '系统内置供应商' })}
              <span className="ml-3 h-[1px] grow bg-gradient-to-r from-[#f3f4f6]" />
            </div>
            <div className="space-y-3">
              {builtinConfigured.map((provider) => {
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

        {/* 自定义模型：已配置的（含 custom 模板与 custom-{ts}） */}
        {customConfigured.length > 0 && (
          <div className="mb-6">
            <div className="mb-3 flex items-center text-xs font-semibold text-gray-500">
              {t('settings.customModels', { defaultValue: '自定义模型' })}
              <span className="ml-3 h-[1px] grow bg-gradient-to-r from-[#f3f4f6]" />
            </div>
            <div className="space-y-3">
              {customConfigured.map((provider) => {
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

        {/* 内置供应商（未配置的） */}
        {builtinNotConfigured.length > 0 && (
          <div className="mb-6">
            <div className="mb-3 flex items-center text-xs font-semibold text-gray-500">
              {t('settings.builtinProvidersNotConfigured')}
              <span className="ml-3 h-[1px] grow bg-gradient-to-r from-[#f3f4f6]" />
            </div>
            <div className="grid grid-cols-3 gap-3">
              {builtinNotConfigured.map((provider) => (
                <ModelProviderCard key={provider.provider_name} provider={provider} />
              ))}
            </div>
          </div>
        )}

        {/* 自定义模型：未配置时一步添加入口 */}
        {customNotConfigured && customProvider && (
          <div className="mb-6">
            <div className="mb-3 flex items-center text-xs font-semibold text-gray-500">
              {t('settings.customModels', { defaultValue: '自定义模型' })}
              <span className="ml-3 h-[1px] grow bg-gradient-to-r from-[#f3f4f6]" />
            </div>
            <div className="flex">
              <Button
                type="button"
                variant="outline"
                className="border-violet-200 text-violet-700 hover:border-violet-300 hover:bg-violet-50"
                onClick={() => setShowAddCustomModel(true)}
              >
                <Plus className="mr-2 h-4 w-4" />
                {t('settings.addCustomModel', { defaultValue: '添加自定义模型' })}
              </Button>
            </div>
            <AddCustomModelDialog
              open={showAddCustomModel}
              onOpenChange={setShowAddCustomModel}
              provider={customProvider}
            />
          </div>
        )}

        {providers.length === 0 && (
          <div className="flex h-64 flex-col items-center justify-center text-gray-400">
            <p className="text-sm">{t('settings.noModelProviders')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
