'use client'

import { AlertTriangle, Loader2, Brain, Plus } from 'lucide-react'
import React, { useMemo } from 'react'

import { ModelProviderAddedCard } from '@/app/workspace/[workspaceId]/settings/models/components/provider-added-card'
import { ModelProviderCard } from '@/app/workspace/[workspaceId]/settings/models/components/provider-card'
import { useModelProviders, useModelCredentials } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

interface ModelsPageProps {
  workspaceId?: string
}

export function ModelsPage({ workspaceId }: ModelsPageProps = {} as ModelsPageProps) {
  const { t } = useTranslation()

  const { data: providers = [], isLoading: providersLoading } = useModelProviders()
  const { data: credentials = [], isLoading: credentialsLoading } = useModelCredentials(workspaceId)

  // Group credentials by provider
  const credentialsByProvider = useMemo(() => {
    const map = new Map<string, typeof credentials[0]>()
    credentials.forEach(cred => {
      map.set(cred.provider_name, cred)
    })
    return map
  }, [credentials])

  // Separate configured and unconfigured providers
  const [configuredProviders, notConfiguredProviders] = useMemo(() => {
    const configured: typeof providers = []
    const notConfigured: typeof providers = []

    providers.forEach(provider => {
      const credential = credentialsByProvider.get(provider.provider_name)
      if (credential && credential.is_valid) {
        configured.push(provider)
      } else {
        notConfigured.push(provider)
      }
    })

    return [configured, notConfigured]
  }, [providers, credentialsByProvider])

  const defaultModelNotConfigured = configuredProviders.length === 0

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

      {defaultModelNotConfigured && (
        <div className="flex items-center px-4 py-3 mb-4 bg-amber-50 rounded-xl border border-amber-200">
          <AlertTriangle className="mr-2 w-4 h-4 text-amber-500 shrink-0" />
          <span className="text-xs font-medium text-amber-700">
            {t('settings.credentialNotConfigured')}
          </span>
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {/* Configured providers */}
        {configuredProviders.length > 0 && (
          <div className="pb-4 space-y-3">
            {configuredProviders.map(provider => {
              const credential = credentialsByProvider.get(provider.provider_name)
              return (
                <ModelProviderAddedCard
                  key={provider.provider_name}
                  provider={provider}
                  credential={credential}
                  workspaceId={workspaceId}
                />
              )
            })}
          </div>
        )}

        {/* Unconfigured providers */}
        {notConfiguredProviders.length > 0 && (
          <>
            <div className="flex items-center gap-3 mb-3 mt-2">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest shrink-0">
                <Plus size={12} />
                {t('settings.addModelProvider')}
              </div>
              <div className="flex-1 h-px bg-gray-200" />
            </div>
            <div className="grid grid-cols-3 gap-3">
              {notConfiguredProviders.map(provider => (
                <ModelProviderCard
                  key={provider.provider_name}
                  provider={provider}
                  workspaceId={workspaceId}
                />
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
