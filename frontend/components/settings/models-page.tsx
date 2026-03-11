import { motion } from 'framer-motion'
import { AlertTriangle, Loader2, Brain, Plus, LayoutGrid, CheckCircle2 } from 'lucide-react'
import React, { useState } from 'react'

import { useMemo } from 'react'
import { AddCustomModelDialog } from '@/app/settings/models/components/add-custom-model-dialog'
import { ModelProviderAddedCard } from '@/app/settings/models/components/provider-added-card'
import { ModelProviderCard } from '@/app/settings/models/components/provider-card'
import { Button } from '@/components/ui/button'
import { useModelProviders, useModelCredentials, useModelProvidersByConfig } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

const BUILTIN_PROVIDER_NAMES = ['openaiapicompatible', 'anthropic', 'gemini', 'zhipu'] as const

function isCustomProvider(p: { provider_name?: string | null; provider_type?: string | null }): boolean {
  return p.provider_type === 'custom'
}

export function ModelsPage() {
  const { t } = useTranslation()
  const [showAddCustomModel, setShowAddCustomModel] = useState(false)

  const { data: providers = [], isLoading: providersLoading } = useModelProviders()
  const { data: credentials = [], isLoading: credentialsLoading } = useModelCredentials()
  const {
    credentialsByProvider,
    configuredProviders,
    notConfiguredProviders,
    templateProviders,
    noValidCredential,
  } = useModelProvidersByConfig(providers, credentials)

  // 1. 已配置的内置供应商
  const builtinConfigured = useMemo(
    () => configuredProviders.filter(p => p.provider_type === 'system'),
    [configuredProviders]
  )

  // 2. 已配置的自定义供应商（非模板）
  const customConfigured = useMemo(
    () => configuredProviders.filter(p => p.provider_type === 'custom' && !p.is_template),
    [configuredProviders]
  )

  // 3. 未配置的内置供应商
  const notConfiguredSystemProviders = useMemo(
    () => notConfiguredProviders.filter(p => p.provider_type === 'system' && !p.is_template),
    [notConfiguredProviders]
  )

  // 4. 未配置的自定义供应商（非模板）
  const customNotConfigured = useMemo(
    () => notConfiguredProviders.filter(p => p.provider_type === 'custom' && !p.is_template),
    [notConfiguredProviders]
  )

  if (providersLoading || credentialsLoading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          <p className="text-sm font-medium text-gray-500 animate-pulse">{t('common.loading', { defaultValue: 'Loading models...' })}</p>
        </div>
      </div>
    )
  }

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: { staggerChildren: 0.1 }
    }
  }

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={containerVariants}
      className="flex flex-col h-full max-w-6xl mx-auto"
    >
      <header className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-3 text-gray-900 tracking-tight">
            <div className="p-2 bg-blue-50 rounded-xl">
              <Brain className="text-blue-600" size={24} />
            </div>
            {t('settings.models')}
          </h2>
          <p className="text-sm text-gray-500 mt-1 ml-12">
            Manage your AI model providers and API configurations
          </p>
        </div>
      </header>

      {noValidCredential && (
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex items-center px-5 py-4 mb-8 bg-amber-50/50 rounded-2xl border border-amber-200/60 backdrop-blur-sm"
        >
          <div className="p-2 bg-amber-100 rounded-full mr-4">
            <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-amber-900">{t('settings.noValidCredentialHeader', { defaultValue: 'Action Required' })}</h4>
            <p className="text-xs font-medium text-amber-700/80 mt-0.5">
              {t('settings.noValidCredential')}
            </p>
          </div>
        </motion.div>
      )}

      <div className="flex-1 space-y-10 pb-12 overflow-y-auto pr-2 custom-scrollbar">
        {/* 系统内置供应商：已配置的 */}
        {builtinConfigured.length > 0 && (
          <section>
            <div className="flex items-center gap-3 mb-5">
              <div className="p-1 px-2 bg-green-50 rounded-md">
                <CheckCircle2 size={14} className="text-green-600" />
              </div>
              <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">
                {t('settings.builtinProviders', { defaultValue: '系统内置供应商' })}
              </h3>
              <div className="flex-1 h-px bg-gradient-to-r from-gray-200 to-transparent" />
            </div>
            <div className="grid grid-cols-1 gap-4">
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
          </section>
        )}

        {/* 自定义模型：已配置的（含 custom-{ts}） */}
        {customConfigured.length > 0 && (
          <section>
            <div className="flex items-center gap-3 mb-5">
              <div className="p-1 px-2 bg-violet-50 rounded-md">
                <CheckCircle2 size={14} className="text-violet-600" />
              </div>
              <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">
                {t('settings.customModels')}
              </h3>
              <div className="flex-1 h-px bg-gradient-to-r from-gray-200 to-transparent" />
            </div>
            <div className="grid grid-cols-1 gap-4">
              {customConfigured.map(provider => {
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
          </section>
        )}

        {/* 内置供应商（未配置的） */}
        {notConfiguredSystemProviders.length > 0 && (
          <section>
            <div className="flex items-center gap-3 mb-5">
              <div className="p-1 px-2 bg-blue-50 rounded-md">
                <LayoutGrid size={14} className="text-blue-600" />
              </div>
              <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">
                {t('settings.builtinProvidersNotConfigured')}
              </h3>
              <div className="flex-1 h-px bg-gradient-to-r from-gray-200 to-transparent" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {notConfiguredSystemProviders.map(provider => (
                <ModelProviderCard key={provider.provider_name} provider={provider} />
              ))}
            </div>
          </section>
        )}

        {/* 自定义供应商（已添加未配置的） */}
        {customNotConfigured.length > 0 && (
          <section>
            <div className="flex items-center gap-3 mb-5">
              <div className="p-1 px-2 bg-violet-50 rounded-md">
                <LayoutGrid size={14} className="text-violet-600" />
              </div>
              <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">
                {t('settings.addedCustomProviders', { defaultValue: '已添加的自定义供应商' })}
              </h3>
              <div className="flex-1 h-px bg-gradient-to-r from-gray-200 to-transparent" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {customNotConfigured.map(provider => (
                <ModelProviderCard key={provider.provider_name} provider={provider} />
              ))}
            </div>
          </section>
        )}

        {/* 自定义模型：一步添加入口（协议 + 模型名），不展示 custom 卡片 */}
        {templateProviders.length > 0 && (
          <section>
            <div className="flex items-center gap-3 mb-5">
              <div className="p-1 px-2 bg-violet-50 rounded-md">
                <Plus size={14} className="text-violet-600" />
              </div>
              <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">
                {t('settings.customModels')}
              </h3>
              <div className="flex-1 h-px bg-gradient-to-r from-gray-200 to-transparent" />
            </div>
            <div className="flex flex-col gap-5">
              {templateProviders.some(p => p.provider_name === 'custom') && (
                <Button
                  type="button"
                  variant="outline"
                  className="w-fit border-violet-200 text-violet-700 hover:bg-violet-50 hover:border-violet-300"
                  onClick={() => setShowAddCustomModel(true)}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  {t('settings.addCustomModel')}
                </Button>
              )}
              {templateProviders.filter(p => p.provider_name !== 'custom').length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                  {templateProviders
                    .filter(p => p.provider_name !== 'custom')
                    .map(provider => (
                      <ModelProviderCard key={provider.provider_name} provider={provider} />
                    ))}
                </div>
              )}
            </div>
            {templateProviders.find(p => p.provider_name === 'custom') && (
              <AddCustomModelDialog
                open={showAddCustomModel}
                onOpenChange={setShowAddCustomModel}
                provider={templateProviders.find(p => p.provider_name === 'custom') ?? undefined}
              />
            )}
          </section>
        )}

        {providers.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 bg-gray-50/50 rounded-3xl border border-dashed border-gray-200">
            <div className="p-8 rounded-full bg-white shadow-sm mb-6 border border-gray-100">
              <Brain size={48} className="text-gray-200" />
            </div>
            <h3 className="text-lg font-bold text-gray-900 mb-2">No Providers Found</h3>
            <p className="text-sm font-medium text-gray-500 max-w-xs text-center leading-relaxed">
              {t('settings.noModelProviders')}
            </p>
          </div>
        )}
      </div>
    </motion.div>
  )
}
