'use client'

import { AlertTriangle, Loader2 } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useMemo } from 'react'

import { useModelProviders, useModelCredentials } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'

import { ModelProviderAddedCard } from './components/provider-added-card'
import { ModelProviderCard } from './components/provider-card'

export default function ModelsPage() {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params?.workspaceId as string | undefined
  
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
        <div className={`flex items-center justify-between mb-4 h-8 ${defaultModelNotConfigured && 'px-3 bg-[#FFFAEB] rounded-lg border border-[#FEF0C7]'}`}>
          {defaultModelNotConfigured ? (
            <div className="flex items-center text-xs font-medium text-gray-700">
              <AlertTriangle className="mr-1 w-3 h-3 text-[#F79009]" />
              {t('settings.credentialNotConfigured')}
            </div>
          ) : (
            <div className="text-sm font-medium text-gray-800">{t('settings.models')}</div>
          )}
        </div>

        {/* Configured providers */}
        {configuredProviders.length > 0 && (
          <div className="space-y-3 mb-6">
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
            <div className="flex items-center mb-3 text-xs font-semibold text-gray-500">
              + {t('settings.addModelProvider')}
              <span className="grow ml-3 h-[1px] bg-gradient-to-r from-[#f3f4f6]" />
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
          <div className="flex flex-col items-center justify-center h-64 text-gray-400">
            <p className="text-sm">{t('settings.noModelProviders')}</p>
          </div>
        )}
      </div>
    </div>
  )
}

