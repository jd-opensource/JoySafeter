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
          <Loader2 className="h-8 w-8 animate-spin text-[var(--brand-500)]" />
          <p className="animate-pulse text-sm font-medium text-[var(--text-secondary)]">
            {t('common.loading', { defaultValue: 'Loading models...' })}
          </p>
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
      className="mx-auto flex h-full max-w-6xl flex-col"
    >
      <header className="surface-panel mb-8 px-6 py-6 sm:px-7">
        <div className="space-y-4">
          <div className="executive-kicker">Model Registry</div>
          <h2 className="flex items-center gap-3 text-2xl font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--divider)] bg-[var(--surface-2)]">
              <Brain className="text-[var(--brand-500)]" size={22} />
            </div>
            {t('settings.models')}
          </h2>
          <p className="max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
            Manage your AI model providers and API configurations
          </p>
        </div>
      </header>

      {noValidCredential && (
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          className="mb-8 flex items-center rounded-[1.25rem] border border-[rgba(155,106,45,0.18)] bg-[rgba(155,106,45,0.08)] px-5 py-4"
        >
          <div className="mr-4 rounded-full bg-[rgba(155,106,45,0.14)] p-2">
            <AlertTriangle className="h-5 w-5 shrink-0 text-[var(--warning)]" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-[var(--text-primary)]">{t('settings.noValidCredentialHeader', { defaultValue: 'Action Required' })}</h4>
            <p className="mt-0.5 text-xs font-medium text-[var(--text-secondary)]">
              {t('settings.noValidCredential')}
            </p>
          </div>
        </motion.div>
      )}

      <div className="flex-1 space-y-10 pb-12 overflow-y-auto pr-2 custom-scrollbar">
        {/* 系统内置供应商：已配置的 */}
        {builtinConfigured.length > 0 && (
          <section>
            <div className="mb-5 flex items-center gap-3">
              <div className="rounded-full border border-[rgba(53,111,97,0.18)] bg-[rgba(53,111,97,0.08)] p-1.5 px-2.5">
                <CheckCircle2 size={14} className="text-[var(--status-healthy)]" />
              </div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                {t('settings.builtinProviders', { defaultValue: '系统内置供应商' })}
              </h3>
              <div className="h-px flex-1 bg-gradient-to-r from-[var(--border)] to-transparent" />
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
            <div className="mb-5 flex items-center gap-3">
              <div className="rounded-full border border-[rgba(36,56,77,0.18)] bg-[rgba(36,56,77,0.08)] p-1.5 px-2.5">
                <CheckCircle2 size={14} className="text-[var(--brand-500)]" />
              </div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                {t('settings.customModels')}
              </h3>
              <div className="h-px flex-1 bg-gradient-to-r from-[var(--border)] to-transparent" />
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
            <div className="mb-5 flex items-center gap-3">
              <div className="rounded-full border border-[rgba(54,93,130,0.18)] bg-[rgba(54,93,130,0.08)] p-1.5 px-2.5">
                <LayoutGrid size={14} className="text-[var(--status-running)]" />
              </div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                {t('settings.builtinProvidersNotConfigured')}
              </h3>
              <div className="h-px flex-1 bg-gradient-to-r from-[var(--border)] to-transparent" />
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
            <div className="mb-5 flex items-center gap-3">
              <div className="rounded-full border border-[rgba(111,129,148,0.22)] bg-[rgba(111,129,148,0.08)] p-1.5 px-2.5">
                <LayoutGrid size={14} className="text-[var(--brand-indigo)]" />
              </div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                {t('settings.addedCustomProviders', { defaultValue: '已添加的自定义供应商' })}
              </h3>
              <div className="h-px flex-1 bg-gradient-to-r from-[var(--border)] to-transparent" />
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
            <div className="mb-5 flex items-center gap-3">
              <div className="rounded-full border border-[rgba(36,56,77,0.18)] bg-[rgba(36,56,77,0.08)] p-1.5 px-2.5">
                <Plus size={14} className="text-[var(--brand-500)]" />
              </div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                {t('settings.customModels')}
              </h3>
              <div className="h-px flex-1 bg-gradient-to-r from-[var(--border)] to-transparent" />
            </div>
            <div className="flex flex-col gap-5">
              {templateProviders.some(p => p.provider_name === 'custom') && (
                <Button
                  type="button"
                  variant="outline"
                  className="w-fit rounded-full border-[var(--border)] bg-white/80 px-5 text-[var(--brand-500)] hover:border-[var(--border-hover)] hover:bg-white"
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
          <div className="surface-panel-flat flex flex-col items-center justify-center rounded-[1.5rem] border-dashed py-20">
            <div className="mb-6 rounded-full border border-[var(--divider)] bg-white/80 p-8 shadow-sm">
              <Brain size={48} className="text-[var(--text-subtle)]" />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-[var(--text-primary)]">No Providers Found</h3>
            <p className="max-w-xs text-center text-sm font-medium leading-relaxed text-[var(--text-secondary)]">
              {t('settings.noModelProviders')}
            </p>
          </div>
        )}
      </div>
    </motion.div>
  )
}
